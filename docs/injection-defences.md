# Injection defences (BP-29, ADR 0018)

An AI feature reads text that people wrote: a website visitor, a customer, a colleague's note.
Some of that text may try to give the AI orders ("prompt injection") or to make it send data to
another site (a link or an image whose address carries the data). This page lists what stops that,
where it lives, and which test proves it. Nothing here replaces the main rule: **an AI only
proposes, and a different person approves** (ADR 0014).

## The layers

| Layer | What it does | Where | Proved by |
|---|---|---|---|
| Door: what a person types | hidden characters, markup, images and floods are cleaned; a hidden or split instruction is refused | `assistant/guardrails.py` `inspect_input` | `test_input_screening*`, eval cases `*-hidden-instruction-refused` |
| Door: what the website chat stores | name, location and notes are screened before the lead exists; links, images, hidden text out; an instruction is kept but the lead says so; a name that is a link is refused | `public_chat/service.py` `_save_lead`, `leads/api.py` | `tests/db/test_public_chat_defences.py`, eval cases `public-defence-door-*` |
| Records read by a model | text from the CRM is cleaned before it goes into a prompt or a tool result; the model is told when a record reads like an instruction | `core/screening.py` `clean_records` | SN3 tests, eval case `staff-sentinel-record-instruction-*` |
| Sentinel | a proposal with a link, an instruction, an address, a duplicate or a wrong state is refused or warned before an approver sees it | `approvals/sentinel.py` | `test_sentinel*`, eval cases `*-sentinel-*` |
| Plan and outcome | every proposal stores what it will change; the approval records what really changed and flags a difference | `approvals/artifact.py` | `test_artifact.py`, `test_artifacts.py`, `test_approvals_plan_api.py` |
| Exit: what an answer may contain | images and links to other sites are removed (the words stay); links inside the CRM stay | `assistant/guardrails.py` `sanitise_output` | `test_injection_defences.py`, eval cases `*-defence-exit-*` |
| Tools | no tool takes an identity (who is asking comes only from the verified token); no tool fetches an address; unknown arguments are refused | tool schemas of the three assistants | `test_injection_defences.py` (every tool of every assistant) |
| Browser | a `Content-Security-Policy-Report-Only` header: outside images and plug-ins would be blocked, framing refused. It only reports for now | `frontend/next.config.ts` | `approval-plan.test.tsx` |

## Reading the signs

- A lead timeline note **"Some text from the website chat was cleaned"** lists only the *kinds* of
  finding (`link`, `external_image`, `hidden_characters`, `instruction_phrase`...), never the removed
  text.
- The approval card shows **Safety check** (Sentinel warnings), **Would change** (the plan) and
  **What happened** (the outcome). A result that did not match the plan is red and is audited as
  `agent_action.mismatch`.
- `[link removed]` / `[image removed]` in an answer means something was taken out.

## Known limits

- The Sentinel's record-text rules read free text of leads only (not yet accounts or contacts).
- The CSP is report-only: it does not block anything yet. Enforcing it is a separate decision after
  the browser console has shown what the screens load.
- A mismatch between plan and outcome is recorded and audited, not undone: the action has already run
  under the approver's name.
- The evaluation cases use a scripted model; a real model has not been tried on the defence cases.
