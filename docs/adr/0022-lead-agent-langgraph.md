# ADR 0022 — An optional lead agent built with LangGraph (CRM-114)

- **Status:** Accepted (2026-11-04): the owner confirmed the reading of the ticket and said to proceed; the
  recommended answers to section 5 apply (build LA1 only, then decide after the pilot; LangGraph behind one module; off by default)
- **Date:** 2026-11-04
- **Deciders:** Project owner
- **Depends on:** ADR 0014 (approval queue), ADR 0016 (agent registry), ADR 0017/0018 (Sentinel and
  injection defences), the Qualifier (`docs/qualifier.md`)

> **Honest note about the source.** The ticket text for CRM-114 is not in the repository. All I have is its
> title from old notes: *"optional: lead agent in LangGraph"*. Everything below is **my reading of that title**
> and is marked as an assumption. Correct it in section 5 before any code is written.

## 1. The problem (assumption)

Today a new website lead goes through **one** model call: the Qualifier reads the lead and the manager's steps
and proposes at most one change (a status, an owner or a follow-up task), which a person approves. That is
safe and cheap, but it is a single step. A real "lead agent" would work a lead through **several** steps —
read the lead, check the web (RERA), look for duplicates, decide, then propose — and would remember where it
was if a step failed.

LangGraph is a library for exactly that: a program written as a **graph** of steps (nodes) with a shared
state, where a step can loop, branch or stop and wait.

## 2. The decision (proposal)

Build the lead agent as a **small, optional LangGraph graph** that sits *behind the existing Qualifier
door* and changes nothing about who may act:

```
start → read lead → (optional) web check → duplicate check → decide → propose → end
```

Rules that do not change (they are the point of the existing ADRs):

1. **It only ever proposes.** The last node calls the approvals module's `propose()`; a different person
   approves. No node writes to the CRM directly.
2. **Every model call goes through `governed()`** (switch, token budget, tool filter, metrics) — the lead
   agent is a seventh entry of the agent registry, **off by default**.
3. **Every proposal passes the Sentinel**, and all text it reads is cleaned with `screen()` (ADR 0017/0018).
4. **Tools are the module APIs we already have** (`leads_api`, `webcheck`, `approvals_api`), as the
   signed-in person or the Automation identity — never a new back door, never a client-supplied ID.
5. **Hard limits:** at most N steps per run, one run per lead per hour, a daily cap per organisation — the
   same shape as the Qualifier's limits.
6. **LangGraph stays a dependency of one module only** (`app/modules/lead_agent/`), imported nowhere else, so
   removing it means deleting one folder. A guard test enforces that, like the HTTP-client guard.

## 3. Why "optional" and why not now (my recommendation)

- The Qualifier already does the valuable part with one call, and it has not yet run in a real pilot. A
  multi-step agent multiplies cost, latency and attack surface **before** we know the one-step version pays off.
- LangGraph is a large dependency with its own release pace; adding it must be a deliberate choice.
- So the plan below is **small and reversible**, and the first step builds it with a **scripted model and no
  new dependency use in production paths** until you say it is wanted.

## 4. Steps (each stops for review, tests first)

| Step | Content |
|---|---|
| LA1 | Add `langgraph` pinned in `requirements.txt` (one module imports it); the graph with a **scripted model**: nodes read → decide → propose; run-state is plain data; tests incl. step limit, no direct write, tenant isolation, role denial, ID tampering |
| LA2 (done 2026-11-04) | Registry entry `lead_agent` (off by default), migration 0050 (the agent name is allowed in proposals), `governed()` around the model, one tool `submit_suggestion` (a status change, never `converted`), Sentinel on the proposal, limits `CRM_LEAD_AGENT_PER_LEAD_HOUR` / `_PER_TENANT_DAY`, audit `lead_agent.ran`. No endpoint or screen yet (LA4) |
| LA3 (done 2026-11-04) | Two read-only steps between read and decide: the web evidence already on file (`webcheck_api.evidence_summary`: source, verdict, status, valid-until of the newest three; never the excerpt or the query; it never starts a check) and a duplicate count (`leads_api.duplicate_count`: how many other leads the asker may read share the e-mail or phone; a number only). Both are cleaned like all record text before the model sees them |
| LA4 (done 2026-11-04) | `POST /api/v1/lead-agent/runs` (body: the lead id only; same people as the Qualifier; 201 with outcome, proposal link, the safety check's words), a "Lead agent" card with an "Ask the lead agent" button on the lead page, and `CRM_LEAD_AGENT_AUTO_WEB_LEADS` (off by default): the worker runs the same service for every new website lead as the Automation identity, once per lead. A scripted model for `CRM_AI_PROVIDER=fake` |
| LA5 (done 2026-11-05) | 18 BP-10 cases in `backend/evals/agents/lead_agent.json`, played through the real `run_lead_agent` (`tests/db/test_agent_evals_lead_agent.py`, a hard CI gate); `docs/lead-agent.md`; the agent is listed in `docs/agents.md` |

## 5. Questions for the owner (recommended answer first)

1. **Is the reading in section 1 right?** *Recommended:* yes. If CRM-114 means something else (for example
   routing leads between agents, or replacing the Qualifier), paste the ticket text and I will redo this note.
2. **Build it now or park it?** *Recommended:* build LA1 only (scripted model, no cost), then decide after the
   pilot whether LA2–LA5 earn their keep.
3. **LangGraph or plain code?** *Recommended:* LangGraph as asked, behind one module with the guard test.
4. **Automatic for new website leads?** *Recommended:* off by default, like the Qualifier.
5. **Which real model for it?** *Recommended:* the same provider setting as the other agents; no new keys.
