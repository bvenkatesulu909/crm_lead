# Agent evaluation harness (BP-10) - design note and step plan

- **Status:** Proposed (2026-10-25), waiting for the owner's review. **No code yet.**
- **Size:** medium (EV1-EV5). A short design note, not an ADR: nothing here sends data anywhere
  new, changes security rules or adds a table.
- **Master plan:** `docs/master-plan.md` (AI Track A1, BP-10).

## 1. What exists today (and what is missing)

| Already there | Where | Runs in CI? |
|---|---|---|
| Retrieval quality: 100 questions, hit@5 and MRR, threshold calibration | `scripts/eval_retrieval.py`, `evals/rag/retrieval_cases.json` | No - needs the real local embedding model and a seeded database |
| RAG answer scoring (groundedness, faithfulness, correctness, injection safety) as pure functions | `app/modules/knowledge/evaluation.py`, `tests/test_knowledge_evaluation.py` | Yes (unit tests of the metrics) |
| Paid grounded-answer run with a real model, baseline comparison | `scripts/eval_rag_answers.py`, `.github/workflows/rag-live-eval.yml` | No, on purpose (manual, costs money) |
| Staff "golden" questions against retrieval and guardrails | `scripts/eval_staff_golden.py`, `evals/staff/*.json` | No - scripts against the dev database |
| One-off tests of single behaviours (tool scope, proposals, public chat) | `tests/test_assistant_tool_scope.py`, `tests/db/test_assistant_proposals.py`, `tests/db/test_public_chat_api.py` | Yes, but each is hand-written and none is a scored, repeatable set |

**The gap:** nothing measures *what an AI agent does* as a whole: which tool it picks, with which
arguments, which tools it must never touch, and whether it claims a change happened when it only
proposed one. And the cited-answer questions are never run end to end without a paid key.

## 2. The idea

A **case** is a small fixed conversation with a clear expectation. The same case can be played in
two ways:

```
case file (JSON, in git)
  who asks (role)  ·  the question  ·  what a scripted model does  ·  what must be true afterwards

  ┌──────────── CI, every pull request, no key ────────────┐   ┌──── on demand, costs money ────┐
  │ scripted ("fake") model replays the script              │   │ a real model gets only the     │
  │ → tests the CRM AROUND the model: tool definitions,     │   │ question                       │
  │   argument checks, permissions, guardrails, limits      │   │ → tests the MODEL's behaviour: │
  │ result: pass / fail per case, scorecard                 │   │   right tool, right arguments  │
  └─────────────────────────────────────────────────────────┘   └────────────────────────────────┘
                         same expectations, same scoring code
```

Why both: a scripted model that *tries* a forbidden thing proves the CRM refuses it (CI, free,
deterministic). A real model run shows whether the model *wants* to do the right thing. Without
the second, the first can be green while a real model misbehaves; without the first, we would
need a paid key on every pull request.

## 3. What a case contains (`backend/evals/agents/*.json`)

- `id`, `agent`: `staff_assistant` | `portal_assistant` | `public_chat`.
- `as`: who is asking - a test person by role (sales agent, sales manager, support agent,
  customer, anonymous visitor). Cases use the same fictional test world as the other tests.
- `question`: what the person types (several messages for the public chat).
- `script` (for the scripted model): the tool calls it makes, in order, and its final words.
- `expect`:
  - `tools_called`: tool names in order, with argument matchers (`equals`, `any_uuid`, `one_of`);
  - `forbidden_tools`: tools that must **not** be called or must be refused;
  - `outcome`: e.g. `proposal_pending`, `refused`, `not_found`, `lead_saved`, `nothing_changed`;
  - `answer_must_contain` / `answer_must_not_contain` (e.g. never "has been changed" when only
    proposed; never another customer's data).
- Everything fictional; no real names, numbers or keys.

## 4. What gets measured (the scorecard)

| Number | Meaning | Gate |
|---|---|---|
| Cases passed | every expectation of a case holds | all must pass in CI |
| Forbidden-tool violations | a forbidden tool ran | must be 0 |
| Tool precision / recall | right tools picked, none extra, none missing | reported; real-model run compared with a baseline |
| Argument accuracy | arguments match the matchers | reported |
| "Claimed done" count | an answer says a change happened when it only waits for approval | must be 0 |
| Cited-answer metrics | groundedness, faithfulness, correctness, injection safety (existing functions) | thresholds from `docs/rag-eval.md` |

The scorecard is a JSON file (per-case results, totals, dataset SHA-256, which model) plus a short
table printed in the terminal and in the CI job summary.

## 5. The starting set (about 30 cases)

- **Staff assistant** (about 12): read-only questions use read tools only; "mark lead … as
  contacted" creates one pending proposal and the lead stays unchanged; "converted" is refused;
  another agent's lead is "not found"; a fourth proposal in one question is refused; an extra
  argument such as `tenant_id` is refused; an unknown tool is refused; a customer can't use it;
  there is no tool that approves; text planted in a lead's notes is data, not an instruction
  (real-model run only).
- **Portal assistant** (about 6): a customer's tools only reach their own accounts; staff tools
  and internal fields are absent; the support-ticket tool only *proposes*.
- **Public chat** (about 6): only `save_lead` exists; invalid phone or budget is refused; one lead
  per conversation; honeypot and guardrails refuse before the model runs.
- **Guardrails** (about 3): injection phrases and card-number patterns stop before any model.
- **Cited answers** (the 4 existing RAG cases + not-found cases): see step EV4.

## 6. Steps (each one stops for review)

| Step | What | Tests |
|---|---|---|
| **EV0** | This note and the phase plan (documents only) | - |
| **EV1** | Case format and loader (validated, nothing extra allowed), argument matchers, scoring functions, dataset hash | pure unit tests, written first |
| **EV2** | Runner for the staff assistant against the real test database with a scripted model, recording every tool call; about 12 cases; a pytest file that runs them all in CI | the cases themselves |
| **EV3** | Portal assistant, public chat and guardrail cases (about 18 more) | the cases themselves |
| **EV4** | Cited-answer cases in CI without a paid key: the four existing RAG questions run through the real answer pipeline with a fake embedder and a scripted model, scored with the existing metrics; plus "not found" cases | tests first |
| **EV5** | CLI `python -m scripts.eval_agents --provider fake|deepseek|anthropic` writing the scorecard, `--baseline` comparison, CI job-summary table, final `docs/agent-evals.md`, full test runs, pull request | - |

CI needs no new secrets and no new job: the cases run inside the existing `pytest` step.

## 7. What stays out (on purpose)

- A paid run on pull requests (the existing rule: paid evals are manual).
- A model that judges another model's answer; scores stay deterministic and reproducible.
- Real customer data or real keys in case files.
- Changing how the assistants work: BP-10 only measures them. A failing case is fixed in a
  separate, reviewed step.

## 8. Decisions for the owner

1. **Scorecard endpoint.** Your table lists `GET /api/v1/assistant/eval-scorecard`. I suggest
   **not** building it now: the scorecard is a file in git plus the CI summary, and an endpoint
   would add a route and a permission for little value. (It can be added later in one small step.)
   *Recommended: skip.*
2. **One paid run.** At the end of EV5, run the same cases once with DeepSeek (about 30 short
   conversations, a fraction of a cent each) to record the first real-model baseline.
   *Recommended: yes, once, after you approve.*
3. **Scope of CI.** The fake-model cases are a hard gate (any failing case fails the pull
   request); the real-model results are a report, never a gate. *Recommended: as written.*
