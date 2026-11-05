# The lead agent (CRM-114, ADR 0022)

An optional AI helper that looks at one lead and **suggests** whether its status should change. It
judges the lead by **your organisation's written qualification steps** - the same steps the
Qualifier uses (Automation -> Qualifier, docs/qualifier.md). It never changes a lead: every suggestion waits in the approval queue until a **different** person
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
| steps | The organisation's active qualification procedure (written for the Qualifier). None written, or the procedure switched off: it stops with "No qualification procedure has been written yet." before any model call; nothing is stored or counted. (A switched-off or over-budget agent says so first.) | No |
| decide | One call of the language model, shown the numbered steps and the lead as data, with ONE tool, `submit_suggestion`: a status (`contacted`, `qualified`, `unqualified`) or `none`, plus a short reason. Anything else is refused. | No |
| propose | At most one pending proposal in the approval queue, through the safety check (the Sentinel, ADR 0017). | No - only a proposal |

It never suggests `converted`: only a person converts a lead.

## 2. Who may use it

The same people who may run the Qualifier (permission `qualifier:run`: sales agents, sales
managers, tenant administrators). Agents only on their own leads; managers and administrators on
every lead of their organisation. Support agents and customers are refused.

## 3. Switching it on

1. Sign in as a tenant administrator.
2. Write the qualification steps under **Automation -> Qualifier** if your organisation has none
   yet. Write them so they also say what to do with leads that are new, contacted or already
   qualified (see section 8).
3. Open **Automation -> AI agents**. The card **Lead agent** says it is off.
4. Switch it on and save. You can also set a monthly token budget or take its one tool away there.

The platform-wide AI switch (`CRM_AI_DISABLED`) also stops it.

## 4. Using it

- **On a lead page:** the card **Lead agent** has a button **Ask the lead agent**. The page then says
  whether a suggestion is waiting, nothing was suggested, or the safety check refused it.
- **Through the API:** `POST /api/v1/lead-agent/runs` with the body `{"lead_id": "..."}` and nothing
  else. Answers `201` with `outcome` (`proposed`, `no_suggestion`, `blocked`), the proposal's link
  and, if blocked, the safety check's words. Switched off or over budget: `503`; over a limit:
  `429`; a lead you may not read: `404`; no qualification steps written: `404`
  `no_active_qualification_procedure`; an unusable model answer: `422`.
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
of 80 lakh or more -> "qualified"; a budget below 30 lakh -> "unqualified"; otherwise nothing. It does not read the
steps, but the agent still refuses to run until some are written. The settings refuse the fake
model in production. Then write the steps and switch the agent on (section 3) and press the
button on a lead page.

## 7. How it is tested

- `backend/tests/test_lead_agent_graph.py` - the graph on its own (order, stopping, the step limit,
  no step that writes, LangGraph imported by one file only).
- `backend/tests/db/test_lead_agent.py`, `test_lead_agent_checks.py`, `test_lead_agent_api.py` -
  the service, the two read-only looks, the API and the automatic trigger against the real
  database (roles, tenant isolation, record-level denial, ID tampering, limits).
- `backend/evals/agents/lead_agent.json` + `backend/tests/db/test_agent_evals_lead_agent.py` - 20
  evaluation cases played through the real service (docs/agent-evals.md section 6i).
- `frontend/src/lib/lead-agent.test.tsx`, `lead-agent-actions.test.ts` - the card, the button and
  the Server Action.

- `frontend/e2e/lead-agent.spec.ts` - the journey with the scripted model (run with
  `E2E_FAKE_ASSISTANT=1` and the API on `CRM_AI_PROVIDER=fake`): an administrator switches it on, an
  agent asks, a suggestion waits and the lead is unchanged, a second ask within the hour is refused, a
  manager approves and only then the lead becomes "Contacted"; switched off again, the button says so.
  Run 2026-11-05: passed.

### A first run with a real model (DeepSeek, 2026-11-05)

The 8 `live` evaluation cases were played once with `deepseek-chat` (cost under one cent). 2 passed,
6 failed: the model answered `none` ("no change") for every lead, including a new lead with a phone
number and a lead with a budget far below the property wished for. Nothing unsafe happened (no
forbidden tool, no false "done" claim, nothing changed directly). The likely reason: unlike the
Qualifier, the lead agent is given no rules for when a status should change, so the model plays safe.
Giving it criteria (for example the Qualifier's written steps) is a product decision for the owner.

**Decision (owner, 2026-11-05):** the lead agent judges by the Qualifier's written steps (section 1).

### A second run with a real model, with the written steps (DeepSeek, 2026-11-05)

The cases now play with six fictional steps that the test leads can be judged by from their fields
(`LEAD_AGENT_STEPS` in `backend/agent_evals/play.py`: contact details, a budget of at least 50 lakh,
a property type and a location -> qualified; a budget below 50 lakh -> unqualified; contact details
but something missing -> contact the lead). 7 `live` cases, cost under one cent: **6 passed, 1
failed**. The model qualified the matching lead, unqualified the low budget, suggested calling the
lead without a budget, refused nothing it should not and claimed nothing as done.

The failure is a lesson about writing steps, not about the code: for a lead that is **already
qualified** but has no budget on file, the steps said "contact the lead to ask", so the model
suggested moving it back to "contacted". Nothing changed (a person must approve), but steps should
say what to do with leads that already have a status. The test steps were left as they are, so the
finding stays visible.

## 8. Writing steps the lead agent can use

- Make each step checkable from what the lead page shows: contact details, budget, property type,
  location, status.
- Say which result each combination leads to (qualified, unqualified, contact the lead).
- Say what happens to leads that already have a status, for example "A lead that is already
  qualified stays qualified."
- The steps are data for the model, never instructions to it; a step that reads like an
  instruction to an AI, or is only a link, is refused when it is saved.
