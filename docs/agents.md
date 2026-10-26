# AI agent registry (BP-14, ADR 0016)

Which AI agents the CRM has, what an organisation lets them do, and how to switch one off.
**Status:** steps AG1 (module, tables, services) and AG2 (the governed model on the four call
sites) are done. The API and notifications are AG3, the admin page AG4.

## The four agents

| Key | What it is | Tools |
|---|---|---|
| `staff_assistant` | answers staff questions about leads, proposes changes for approval | 8 |
| `portal_assistant` | helps signed-in customers with orders, invoices, tickets | 13 |
| `public_chat` | talks to website visitors, saves a lead on request | 1 |
| `knowledge_answers` | answers from the knowledge base with sources | 0 |

The list is in code (`app/modules/agents/catalogue.py`); a test fails if a listed tool does not
match the tools the code really gives the agent.

## What an organisation can set (tenant admins; sales managers can read)

- **On / off** per agent.
- **Monthly token budget** (input + output, calendar month in UTC). Default
  `CRM_AGENT_DEFAULT_MONTHLY_TOKENS` = 2,000,000; there is no "unlimited".
- **Allowed tools**: only fewer than the code offers, never more. Empty = no tools.

No row means: on, default budget, all tools. Every change is audited (`agent.updated`, with
before and after) and refused when the version is stale.

## The rules (`service.check_can_call`)

1. `CRM_AI_DISABLED=true` (platform switch): everything is refused, for every organisation.
2. The agent is off: `agent_unavailable` (503).
3. This month's tokens have reached the budget: `agent_budget_reached` (503).

`record_usage` adds a call to the month in one atomic `INSERT ... ON CONFLICT DO UPDATE` and
reports, exactly once per month and agent, when 80 % of the budget is passed (AG3 turns that
into a notification). A call can overshoot the budget slightly: the check is before the call.

## Data

`agent_settings` (an organisation's overrides) and `agent_usage` (monthly counts only, never
prompts or answers), migration 0043, forced row-level security; usage rows cannot be deleted by
the application role.

## The governed model (AG2)

`governed(model, session, tenant_id, agent_key, limits)` (in `agents/governed.py`, exported by
`agents/api.py`) wraps the model a feature received. Before **every** `reply()` it asks
`check_can_call`; a "no" is raised before the model is touched, so a conversation switched off in
the middle stops at its next step. It then offers the model only the allowed tools, adds the
call's tokens to the month, and removes any call to a tool of this agent that the organisation
removed (counted in `crm_ai_dropped_tool_calls_total`). A tool name the agent never had passes
through: the feature's own dispatcher refuses it and tells the model. Refusals are counted in
`crm_ai_refusals_total{agent,reason}` - no organisation in any label.

| Call site | Where it is wrapped | When off or over budget |
|---|---|---|
| staff assistant | `staff_service.answer` | HTTP 503 `agent_unavailable` / `agent_budget_reached` |
| portal assistant | `service.send_message` | the same |
| knowledge answers | `answers.answer_question` (after the "nothing close enough" refusal, which needs no model) | the same |
| website chat | `public_chat.service.handle_message` | a normal 200 reply with the fixed "resting" sentence; no lead is saved |

The services take an optional `limits` (the platform switch and default budget); the two routers
pass `Limits.from_settings(settings)`, the knowledge and website-chat sites read it from the
`settings` they already receive. A test per site over HTTP proves that `CRM_AI_DISABLED` reaches
the model of none of them. Evaluation cases (`governance` block, outcomes `agent_off` and
`over_budget`, `expect.model_called`) are in `docs/agent-evals.md`.

Not counted: tokens of a request that fails after the model call and rolls back.

## API, audit and notifications (AG3)

| Endpoint | Who | What |
|---|---|---|
| `GET /api/v1/agents` | tenant admins, sales managers | the four agents with switch, budget (and whether it is the default), allowed tools, this month's usage and `percent_used`, `version` |
| `GET /api/v1/agents/{key}` | the same | one agent (404 `agent_not_found`) |
| `PATCH /api/v1/agents/{key}` | tenant admins | `enabled`, `monthly_token_budget` (1 - 10,000,000,000), `allowed_tools`; only the fields sent change, `null` for the budget or the tools means the default; send the `version` you read once the agent has settings (409 `version_conflict` otherwise) |

The body accepts nothing else (no tenant, no key): an unknown tool, a tool of another agent, a
budget out of range or an empty change is 422. Every change is audited (`agent.updated`, before
and after). Events carry ids and codes only: `agent.switched` (only when the switch really
flips) and `agent.budget_warning` (once per month and agent) notify the other tenant admins
(not the one who acted) with a link to `/automation/agents` (the page comes in AG4). Both types
appear on the notification settings page (in-app by default).
