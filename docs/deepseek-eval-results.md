# DeepSeek end-to-end evaluation results (BP-10)

A one-page summary that can be shared as it is. Every number comes from a stored report in
`backend/evals/baseline/` or from `docs/agent-evals.md`; nothing here was re-run for this page.

## What was tested

The CRM's AI features (staff assistant, customer-portal assistant, public website chat, cited
knowledge answers, deal desk, account research, lead agent) were played through their **real code
and a real PostgreSQL database**, with the only difference that the model was a real one,
`deepseek-chat`, instead of a scripted stand-in. Each case checks which tools the model called, with
which arguments, what changed in the CRM, and whether the answer claimed something was done.

Cost: the whole of each pass was under one US cent to about four cents (`--estimate` is free and
was shown first). Only fictional demo data was used. Each paid run needed the owner's yes
(`CRM_RUN_LIVE_EVALS=1`).

## Results

| Run | Date | Live cases | Passed | Failed | Forbidden tool used | False "done" claims |
|---|---|---:|---:|---:|---:|---:|
| Staff, portal, website chat, cited answers | 2026-10-26 | 26 | 15 | 11 | 0 | 0 |
| Lead agent (with the written qualification steps) | 2026-11-05 | 7 | 6 | 1 | 0 | 0 |
| Deal desk and account research | 2026-11-08 | 13 | 8 | 5 | 0 | 0 |
| Website chat in Hindi | 2026-11-12 | 2 | 1 | 1 | 0 | 0 |
| Website chat in Telugu | 2026-11-12 | 2 | 2 | 0 | 0 | 0 |

By area in the first run: cited answers 11 of 11, customer-portal assistant 2 of 4, website chat
1 of 3, staff assistant 1 of 8. Tool precision 46 %, recall 46 %, argument accuracy 41 %.

## How to read it

- **The safety numbers held in every run.** The model never called a tool it was not allowed to,
  never changed the CRM directly (everything it suggested waited for a person's approval) and never
  said something was done when it was not.
- **The failures are about wording and habits, not safety.** Most are a required phrase missing
  ("could not find", "waiting") because the model answers in its own words, or the model did not
  call the tool at all (for example it searched instead of proposing). In the deal desk run the
  model wrote different task wording and due dates than the script, and wrote 5-7 sentences where
  the case expected fewer.
- **One paid pass is a snapshot.** Real models vary a little between runs; the harness keeps a
  5-point tolerance for that. The cited-answer stand-in measures word overlap, not meaning.
- **These are measurements, not fixes.** Tightening prompts or loosening the phrase checks is a
  separate, reviewed step.

## What protects the CRM regardless of the model

The scripted-model cases (all free) run in CI on every pull request as a hard gate and
prove the protections can fail when removed: nothing changes without a different person's approval,
no AI call can reach another organisation's data, links and instructions in model output are
blocked, and an agent switched off or over its budget never reaches the model.

Sources: `backend/evals/baseline/deepseek.md`, `deepseek-deal-desk.md`, `docs/agent-evals.md`
(sections 6e, 6i, 6m).
