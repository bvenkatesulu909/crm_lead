# AI agent registry (BP-14, ADR 0016)

Which AI agents the CRM has, what an organisation lets them do, and how to switch one off.
**Status:** all steps are done: AG1 (module, tables, services), AG2 (the governed model on the four call
sites), AG3 (API, audit, events, notifications) and AG4 (the admin page).

## The agents

| Key | What it is | Tools |
|---|---|---|
| `staff_assistant` | answers staff questions about leads, proposes changes for approval, queues a web check (`check_rera`) | 9 |
| `portal_assistant` | helps signed-in customers with orders, invoices, tickets | 13 |
| `public_chat` | talks to website visitors, saves a lead on request | 1 |
| `knowledge_answers` | answers from the knowledge base with sources | 0 |
| `web_check` | looks up a RERA number or a company on a public registry (ADR 0019) - **uses no model** | 0 |
| `mcp_client` | lets an outside AI client (Claude Code, Cursor ...) suggest changes through the MCP server (ADR 0020) - **uses no model of ours, off until switched on** | 0 |

`web_check` is governed like an agent but calls no language model (`uses_model = false`): an
organisation can switch it off (then no check can be asked for, by a person or by the assistant's
`check_rera` tool), the page counts **checks** instead of tokens, and it has no token budget and no
tools to choose - the API refuses a budget or a tool list for it. The AI platform switch
(`CRM_AI_DISABLED`) does not apply to it; it has its own (`CRM_WEBCHECK_DISABLED`, see
[webcheck.md](webcheck.md)).

`mcp_client` also uses no model of ours (the model is the client's, so there is no budget and no
tools to choose) but, unlike `web_check`, **the AI platform switch stops it** and an organisation
starts with it **switched off** (`default_enabled = false`): a tenant admin turns it on on the AI
agents page. See [approvals.md](approvals.md).

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

## The admin page (AG4)

**AI agents** (`/automation/agents`), in the menu for tenant admins and sales managers (and linked
from the Automation page). One card per agent: what it is, its state as a word (On, Switched off,
Near its limit from 80 %, Limit reached), a usage bar ("1,000 of 2,000,000 tokens used this month",
"(the standard limit)" when nobody set one), the number of calls and of allowed tools.

Tenant admins also see the settings under each card: **Switched on**, **Monthly token budget**
(empty = the standard limit; whole numbers, commas fine) and the **tools it may use** (tick
off, never add). One Save button sends all three; the API checks everything again (role, tool
names, version). Sales managers see the cards and a note that only a tenant administrator can
change them; everyone else gets "no permission" and no menu entry. Notifications about a switch or
the 80 % warning link here.

Code: `frontend/src/app/(app)/automation/agents/` (page, Server Action), `components/agent-views.tsx`,
`components/agent-settings-form.tsx`, `lib/agents.ts`. Tests: `src/lib/agents.test.tsx` (29),
Playwright `e2e/agents.spec.ts` (a real admin switches, caps and narrows; a manager only reads; an
agent has no entry; the settings are put back at the end).
