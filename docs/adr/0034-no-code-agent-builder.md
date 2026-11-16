# ADR 0034 — A no-code agent builder for administrators

- **Status:** Proposed (2026-11-16, waiting for the owner's answers in section 6)
- **Date:** 2026-11-16
- **Deciders:** Project owner
- **Depends on:** ADR 0014 (approval queue), ADR 0016 (agent registry, budgets, kill switch), ADR 0017 and
  0018 (Sentinel and cleaning of untrusted text), ADR 0009 (row-level security), ADR 0024 (deal desk, the
  parallel-reviewer pattern)
- **Master plan:** BP-18, second half ("admins configure simple agents from allowed tools"). The first half,
  the deal desk, is done (ADR 0024).

## 1. The problem

Every AI agent today (staff assistant, portal assistant, website chat, Qualifier, lead agent, deal desk,
account research, deck writer) was written as code by a developer. An organisation that wants a small,
specific helper - "every Monday suggest a follow-up task for each lead I own that has gone quiet", "read a
new ticket and suggest a category" - has to ask a developer. The goal of this ADR is that a **tenant
administrator** can define such a helper on a screen, **without being able to give it any power the CRM does
not already give an AI agent**.

The risk is the reason this needs an ADR: a builder that lets someone write "do anything" would undo every
protection built in ADR 0014-0018. So the design is mostly about what the builder can **not** do.

## 2. What exists

The agent registry (switch, monthly token budget, tool filter, platform kill switch) wraps every model call
(`governed`). The approval queue holds every AI-suggested change until a different person approves it, and the
Sentinel checks each proposal (links, instructions, state, limits). Each agent so far has its own code, its
own prompt and its own fixed list of tools. Nothing stores an agent's definition in the database.

## 3. Decisions (proposed)

**AB1 - A custom agent is a recipe, never code.** A definition is data: a name, a plain-language purpose, the
instruction text, one **read set** (which kinds of record it may look at, from a fixed list), one **suggestion
set** (which existing proposal kinds it may make, from the approval queue's catalogue) and its limits. There is
no field that holds a script, an address, a key or a query.

**AB2 - Powers come only from a fixed menu, and only narrower than a person's own.** Read sets are the
existing "facts" readers (a lead and its notes, an account and its health, a deal's quotes and activity). They
run **as the person who starts the agent**, so the person's own record-level rules decide what is visible; a
custom agent never sees more than its starter. The suggestion set is limited to the kinds that already
exist (`lead.set_status`, `lead.assign`, `activity.create_task`, `quote.deck_summary`); a new kind is
a developer's change and a new ADR amendment. **Nothing in a custom agent can approve, edit or delete** - the
same rule as every other agent.

**AB3 - Every custom agent is an entry in the agent registry.** It gets the same switch (off until an
administrator switches it on), monthly token budget, tool filter and the platform kill switch, and its tokens
and estimated cost appear on the AI agents page. Deleting a definition keeps its usage rows (they cannot be
deleted).

**AB4 - The instruction text is untrusted input and is screened like one.** It goes through the same cleaning
as other typed text (links, markup and hidden characters out; instruction-like phrases that try to switch off
the safety rules are refused). It is **versioned**: a change makes a new version, the old one is kept, and
every run records which version it used. The model is told the instruction is the organisation's request,
that record text is data, and that it can only call its allowed tools.

**AB5 - Suggestions, not actions; the Sentinel still applies.** A custom agent's only way to change anything
is to create a proposal through the approvals module, so every rule of ADR 0014 and 0017 applies unchanged:
validated arguments, no self-approval, per-person pending limits, expiry, audit. A proposal says it came from
"the custom agent <name>". Hourly and daily limits per agent and per organisation are set by the platform, not
by the definition (an administrator can lower them, never raise them).

**AB6 - Try before you switch on.** A **dry run** on one chosen record shows what the agent would read and
what it would suggest, stores nothing and creates no proposal (like the Qualifier's dry run). An agent cannot
be switched on until it has had at least one successful dry run on its current version.

**AB7 - v1 starts only by a person pressing a button.** No schedules, no event triggers, no run for every new
record. (The Qualifier and lead agent already have an opt-in automatic run; a general trigger system is a
second step and a new decision.) Each run is for one record.

**AB8 - Limits of the first version.** At most 10 custom agents per organisation; instruction up to 4,000
characters; at most 3 read sets and 2 suggestion kinds per agent; one model call per run; the platform's
standard token cap per run. No web access, no fetching a page, no e-mail sending, no file reading.

## 4. What the builder deliberately cannot do

It cannot add a tool, an endpoint, a web address, an e-mail send, a credit or discount change, a stage change
of a deal, a status "converted", a delete, an export, or a read outside the starter's own permissions. It
cannot raise a limit or switch off the Sentinel. It cannot make an agent that runs on its own. These are
tested, not just documented (section 5).

## 5. Steps and tests (each step ends with a stop)

| Step | What | Done when |
|---|---|---|
| AB0 | This ADR and the owner's answers | Status Accepted |
| AB1 | Tables `custom_agents` and `custom_agent_versions` (forced RLS, versions insert-only), the fixed menus of read sets and suggestion kinds, pure rules (screening, limits) | pure tests; RLS guard passes |
| AB2 | Service: create, edit (new version), switch, dry run, run; registry entry per agent; runs through `governed` and the approvals module; audit with ids and codes only | database tests: tenant isolation, role denial, a colleague's record 404, a menu entry not on the list refused, no self-approval, limits |
| AB3 | API under `/api/v1/custom-agents`; permission `custom_agent:manage` (tenant admins) and `custom_agent:run` (staff who may run the Qualifier) | API tests incl. ID tampering |
| AB4 | Screens: a builder page for administrators, a "Run <name>" button on lead and account pages, the approval card names the custom agent | component tests + a Playwright journey |
| AB5 | BP-10 evaluation cases through the real service with a scripted model: every forbidden power above is refused; an injection in a record or in the instruction does not escape | evaluation gate in CI; deliberate breaks caught |

Each step is a separate, reviewed change. Nothing is switched on in staging by default.

## 6. Questions for the owner (recommended answer first)

1. **Who may build?** *Recommended: tenant administrators only* (they already control the agent registry).
   Alternative: sales managers may also build agents that only read leads they can see.
2. **How are agents started in v1?** *Recommended: by a person pressing a button, one record at a time.*
   Alternative: also on a schedule (needs the worker and a new set of limits; a second decision).
3. **Which suggestion kinds are on the menu?** *Recommended: the three existing ones that need no money or
   stage change* (`lead.set_status`, `lead.assign`, `activity.create_task`) *plus the deck summary later.*
4. **Is a dry run required before switching on?** *Recommended: yes* (AB6).
5. **Per-organisation cap on custom agents?** *Recommended: 10.*
6. **Naming on the approval card:** *Recommended: "the custom agent <name>"*, so a reviewer can tell it from the
   built-in agents.

## 7. Alternatives considered

- **A free-form "skill" or code editor.** Rejected: it would let an administrator create powers the
  protections were built to stop, and a mistake would be hard to see.
- **Letting administrators add tools by pasting an API address.** Rejected: it is the way a poisoned text
  sends data out (ADR 0018) and it breaks tenant isolation.
- **Waiting until the built-in agents are all finished.** Possible, but this ADR keeps the builder small
  enough to start now, because every ingredient (registry, approvals, Sentinel, dry run) already exists.

## 8. Consequences

A new module `custom_agents`, two tables, two permissions, one builder page and some buttons. Cost: more
review surface (the menu of read sets and suggestion kinds must be kept in step with the modules they read).
Benefit: organisations tune a helper without a developer, inside the same safety rules.
