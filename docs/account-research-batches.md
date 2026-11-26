# Researching many accounts at once

Design: [ADR 0042](adr/0042-bulk-account-research.md). This page explains how the feature works
and how to use it.

## What it does

Account research (ADR 0024) writes a short brief about ONE account from the CRM's own records. A
**research batch** does the same for up to **100 accounts**, one after the other, in the
background. Nobody waits on a web page: the batch runs in the worker and its page updates itself.

Every account is researched **on its own**: the AI sees only that account's records, in a fresh
conversation, and never another account's name, deals or contacts. Nothing in the CRM is changed
and nothing is proposed; a batch only writes briefs.

## Who may use it

- **Sales managers and tenant administrators** (permission `research_batch:run`). Sales agents,
  support staff and customers cannot start or see batches.
- The accounts are always chosen **under the person's own read rules**: an id they may not read is
  left out and counted as "not available"; archived accounts are left out and counted apart.
- Two switches on the **AI agents** page must be on: **Account research** (the AI calls and their
  monthly budget) and **Batch account research** (off by default; switching it off stops bulk
  research while single research stays on). The AI agents page counts "N batches this month".

## Using it

1. **Accounts** list: tick the accounts (the box in the header ticks the whole page), or apply a
   **saved filter**. The "AI research" bar under the filters offers **Research ticked accounts**
   and, when a saved filter is in use, **Research every account of "<filter>"**.
2. Optional: **Research again even if researched in the last day**. Without it, an account with a
   brief under a day old reuses that brief and costs nothing.
3. A dialog shows the figures before anything starts: how many accounts, how many reuse a recent
   brief, how many the AI will read, what was left out, the usual and the highest number of
   tokens, the cap the batch stops before, what is left of the month's budget, and an estimated
   cost. **Start research** starts it; **Cancel** starts nothing.
4. The **batch page** (Accounts → **Research batches**) shows the state, a progress bar, the tokens
   used against the cap, and a table: each account's state, why it failed (in plain words), and
   the brief's figures (sentences and what they came from) with a **Read it** link to the account.
   An account the viewer may not read shows as "Not available to you".
5. **Stop the batch** (while it runs): the account being researched finishes; the rest is "Not
   run". Briefs already written are kept.
6. When a batch ended with failed or not-run accounts, **Try them again** starts a **new** batch
   with those accounts (the failed, the not run, or both) after its own confirmation.

## The limits

- At most 100 accounts per batch (a setting may lower it, never raise it).
- The batch has a **hard cap** of tokens, held to what is left of the month's budget. Before each
  account it checks that the account's worst case still fits; if not, the batch stops
  ("Stopped: the AI budget or a switch") and the rest is not run.
- The person confirms the highest figure they were shown; if the cost has moved by more than 20 %
  when they press Start, the start is refused and they look at the new estimate.
- The usual one-per-hour limit per account and the daily limits of account research apply.
- A model that cannot be reached is tried three times for an account; then the account is
  recorded as failed and the batch goes on. One failed account never stops the others.

## What is stored

- `research_batches` and `research_batch_items` (migrations 0078, 0079): the batch, its frozen list
  of accounts, each account's state, failure code, tokens and brief id. Forced row-level
  security; kept 12 months.
- The briefs themselves are ordinary account research briefs (`account_briefs`).
- Audit entries `research_batch.started`, `.finished`, `.cancelled`, `.stopped_budget`,
  `.stopped_error`, `.cancel_requested` with ids and counts only. The person who started a batch is
  notified when it ends.

## For developers

- API: `/api/v1/research-batches` (estimate, start, list, read, cancel, retry estimate, retry);
  see `docs/api/openapi.json`.
- Backend: `backend/app/modules/research_batches/` (service, worker step `research_batch.step`).
- Web: `frontend/src/lib/research-batches.ts`, `src/components/research-batch-*.tsx`,
  `src/app/(app)/accounts/batches/`.
- Tests: `backend/tests/db/test_research_batch_*.py`, the evaluation cases in
  `backend/evals/batches/` (docs/agent-evals.md 6t), `frontend/src/lib/research-batches.test.tsx`,
  Playwright `frontend/e2e/research-batches.spec.ts` (needs the scripted model and runs the worker
  itself).
