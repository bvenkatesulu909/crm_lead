# The lead agent (CRM-114, ADR 0022)

An optional AI helper that looks at one lead and **suggests** whether its status should change. It
never changes a lead: every suggestion waits in the approval queue until a **different** person
approves it. It is **switched off** until an administrator switches it on.

The design and the reasons behind it are in [ADR 0022](adr/0022-lead-agent-langgraph.md). The ticket
text for CRM-114 is not in the repository; the ADR was built from the ticket's title and the owner
confirmed that reading on 2026-11-04.

## 1. What it does, step by step

The agent is a small graph of five steps, built with the LangGraph library
(`backend/app/modules/lead_agent/graph.py`). Each step is a plain function; the graph only decides
the order, when to stop and how many steps are allowed.

| Step | What happens | Can it change anything? |
|---|---|---|
| read | The lead's few fields, only if the person asking may read the lead. Phone and e-mail arrive only as "present" / "missing". A lead they may not read stops here with "Lead not found." | No |
| web evidence | The newest three web checks already on file for the lead (source, verdict, status, valid-until). It never starts a check and never shows the page text or the query. | No |
| duplicate check | How many other leads the person may read share the e-mail or phone. A number only. | No |
| decide | One call of the language model with ONE tool, `submit_suggestion`: a status (`contacted`, `qualified`, `unqualified`) or `none`, plus a short reason. Anything else is refused. | No |
| propose | At most one pending proposal in the approval queue, through the safety check (the Sentinel, ADR 0017). | No - only a proposal |

It never suggests `converted`: only a person converts a lead.

## 2. Who may use it

The same people who may run the Qualifier (permission `qualifier:run`: sales agents, sales
managers, tenant administrators). Agents only on their own leads; managers and administrators on
every lead of their organisation. Support agents and customers are refused.

## 3. Switching it on

1. Sign in as a tenant administrator.
2. Open **Automation -> AI agents**. The card **Lead agent** says it is off.
3. Switch it on and save. You can also set a monthly token budget or take its one tool away there.

The platform-wide AI switch (`CRM_AI_DISABLED`) also stops it.

## 4. Using it

- **On a lead page:** the card **Lead agent** has a button **Ask the lead agent**. The page then says
  whether a suggestion is waiting, nothing was suggested, or the safety check refused it.
- **Through the API:** `POST /api/v1/lead-agent/runs` with the body `{"lead_id": "..."}` and nothing
  else. Answers `201` with `outcome` (`proposed`, `no_suggestion`, `blocked`), the proposal's link
  and, if blocked, the safety check's words. Switched off or over budget: `503`; over a limit:
  `429`; a lead you may not read: `404`; an unusable model answer: `422`.
- **Automatically for new website leads (optional):** set `CRM_LEAD_AGENT_AUTO_WEB_LEADS=true` and
  restart the worker. Each new website lead is then looked at once, as the organisation's Automation
  identity. The switch, budget, limits, safety check and "someone else approves" all still apply.
  Off by default. (The Qualifier has its own setting, `CRM_QUALIFIER_AUTO_WEB_LEADS`; turning both
  on gives two separate suggestions for one lead.)

## 5. Limits

| Setting | Default | Meaning |
|---|---|---|
| `CRM_LEAD_AGENT_PER_LEAD_HOUR` | 1 | How often one lead may be looked at per hour |
| `CRM_LEAD_AGENT_PER_TENANT_DAY` | 200 | How many looks one organisation may have per day |

Every finished run is audited as `lead_agent.ran` (ids and codes only, never the model's text).

## 6. Trying it on this PC without a paid key

Run from Windows CMD in `backend`, with the virtual environment active:

```bat
alembic upgrade head
set CRM_AI_PROVIDER=fake
uvicorn app.main:create_app --factory --reload
```

`alembic upgrade head` applies migration 0050, which lets the lead agent author proposals.
`CRM_AI_PROVIDER=fake` uses a scripted demo model (`backend/app/modules/lead_agent/llm.py`) that
applies fixed, visible rules: a new lead with a phone -> "contacted"; a contacted lead with a budget
of 80 lakh or more -> "qualified"; a budget below 30 lakh -> "unqualified"; otherwise nothing. The
settings refuse the fake model in production. Then switch the agent on (section 3) and press the
button on a lead page.

## 7. How it is tested

- `backend/tests/test_lead_agent_graph.py` - the graph on its own (order, stopping, the step limit,
  no step that writes, LangGraph imported by one file only).
- `backend/tests/db/test_lead_agent.py`, `test_lead_agent_checks.py`, `test_lead_agent_api.py` -
  the service, the two read-only looks, the API and the automatic trigger against the real
  database (roles, tenant isolation, record-level denial, ID tampering, limits).
- `backend/evals/agents/lead_agent.json` + `backend/tests/db/test_agent_evals_lead_agent.py` - 18
  evaluation cases played through the real service (docs/agent-evals.md section 6i).
- `frontend/src/lib/lead-agent.test.tsx`, `lead-agent-actions.test.ts` - the card, the button and
  the Server Action.

Not done yet: a Playwright journey and a look in a browser (this PC keeps port 3000 reserved, which
the Keycloak sign-in needs), and a run with a real model.
