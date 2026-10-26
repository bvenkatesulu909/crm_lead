# AI agent registry (BP-14, ADR 0016)

Which AI agents the CRM has, what an organisation lets them do, and how to switch one off.
**Status:** step AG1 (module, tables, services). The governed model on the four call sites is AG2,
the API AG3, the admin page AG4: until AG2, nothing consults the registry yet.

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
