# Custom agents (the no-code agent builder, ADR 0034)

An administrator defines a small AI helper as data; staff run it on one record; it can only
**suggest**, and a different person approves every suggestion in the approval queue. This page
describes what exists today (steps AB1-AB4: tables, service, run, the API and the screens). The
evaluation cases are AB5.

## The screens (AB4)

- **Administrators** (menu entry **Custom agents**, `/automation/custom-agents`): the list with each
  agent's state in words ("Needs a dry run, then switching on", "Ready to switch on", "Switched on");
  **New custom agent** (name, what it is for, instruction, and two groups of checkboxes - what it may
  read, grouped by kind of record, and what it may suggest - straight from the API's menus; a lead
  status is greyed out for an agent that reads an account or a deal); one agent's page with
  **Dry run and switch** (pick a real record, see what the agent WOULD do, nothing is proposed;
  **Switch on** stays disabled until the current version had a dry run), **Definition** (saving makes
  the next version and needs a new dry run), **Versions**, **Recent runs** and **Retire** (asks
  first). A refused save keeps what was typed and chosen.
- **Sales staff**: a **Custom agents** card on a lead, an account or a deal page with one
  **Run <name>** button per agent that is switched on, has had a dry run of its current version and
  works on that kind of record. Nothing is shown when there is nothing to run. The result says that
  nothing changes until a different person approves, and links to the suggestion.
- **Approvals**: the proposal card says "Asked by ... through the custom agent "<name>"" (also after
  the agent was retired).
- Everything a model wrote is shown as plain text. The screens only help: the API decides who may do
  what and checks every menu and limit again.

## What an agent is

A definition has a **name**, a **purpose**, an **instruction** (written in plain words, up to 4,000
characters), 1-3 **read sets** (what it may look at) and 1-2 **suggestion kinds** (what it may
suggest). The administrator chooses read sets and kinds from fixed menus - there is no field for a
script, an address, a key or a query.

| Read sets (one kind of record per agent) | Record |
|---|---|
| `lead`, `lead_activity` | lead |
| `account`, `account_health` | account |
| `deal`, `deal_quotes` | deal |

Suggestion kinds: `lead.set_status` (a lead agent only; never "converted") and
`activity.create_task` (goes to the owner of the record). Nothing that approves, deletes, converts,
assigns, moves money or changes a deal's stage exists on the menu.

## The life of an agent

1. **Define** (`POST /api/v1/custom-agents`, tenant administrators). The typed text is cleaned like
   every other text (links, markup and hidden characters out, reported by code; words that try to
   change the AI's safety rules are refused). The agent starts **switched off** in the AI agents
   registry and can have at most 10 active agents per organisation.
2. **Change** (`PUT /{id}` with the `version` you read): every save is the next insert-only version;
   the old ones stay. A no-change save and a stale screen are refused.
3. **Dry run** (`POST /{id}/try`, administrators): the same call on one real record the
   administrator may read, but no proposal. It works while the agent is switched off. A valid answer
   counts as the dry run of the **current version**.
4. **Switch on** (`PATCH /api/v1/agents/{agent_key}` with `enabled: true`): refused until the
   current version has had a dry run. The usual budget, tool filter and platform kill switch apply.
5. **Run** (`POST /{id}/runs`, sales staff): the record must be one the person may read (otherwise
   "not found", and the model is never called). The result is at most one pending proposal; nothing
   in the CRM changes until a **different** person approves it.
6. **Retire** (`POST /{id}/archive`): it can no longer be run or edited; history and usage stay.

A new version needs a new dry run before it can be run. Limits (platform settings, not the
definition): 1 run per record per hour, 20 per person per hour, 200 per organisation per day
(`CRM_CUSTOM_AGENT_PER_RECORD_HOUR`, `_PER_USER_HOUR`, `_PER_TENANT_DAY`).

## Who may do what

| | Administrator | Sales manager / agent | Support, customer |
|---|---|---|---|
| Define, change, retire, dry run, history | yes | no | no |
| See the list (the instruction is hidden from non-administrators) | yes | yes | no |
| Run on a record they may read | yes | yes | no |

## What is stored

`custom_agents` (name, registry key `custom_` + 12 letters), `custom_agent_versions` (insert-only:
purpose, instruction, read sets, kinds) and `custom_agent_runs` (insert-only: which version ran on
which record, who asked, the outcome, the proposal - ids and codes only, never what the model
wrote). All three have forced row-level security. The audit trail records `custom_agent.created`,
`.updated`, `.archived`, `.dry_run` and `.ran` with ids and codes only.

## Trying it without a paid model

`CRM_AI_PROVIDER=fake` uses a scripted model that suggests a follow-up task (or a status change, or
nothing, depending on what the agent may suggest). It is refused in production.
