# Sentinel and input screening (BP-21, ADR 0017)

A deterministic second check on every AI proposal, plus one function that cleans untrusted text.
**Status:** steps SN1 (rules and screening, pure functions) and SN2 (hooked into `propose()` and
`approve()`) are done. The guardrails, the staff prompt and the "Safety check" warnings on the
approval card are SN3.

## Screening (`app/core/screening.py`)

`screen(text)` returns the text cleaned and what it found. It takes out of the clean text: hidden
and control characters (including ASCII hidden as "tag" characters), HTML comments, scripts and
tags, images, links and e-mail addresses (each replaced by a visible marker such as
`[link removed]`), and text that repeats itself (a line more than 5 times, a word more than 20 in
a row, one character more than 200 times). It only *reports* phrases that read like instructions
to an AI (`instruction_phrase`) - deleting words would change their meaning. Findings carry a
stable code and a sentence and never repeat the text they found.

Zero-width joiners inside Indic scripts (Telugu, Hindi) are ordinary and kept; a joiner next to
Latin letters or several in a row is hidden text.

## The rules (`app/modules/approvals/sentinel.py`)

`verify(candidate, facts, limits)` runs five groups and returns a verdict (findings + the groups
checked). A **block** refuses the proposal, a **warning** is stored and shown to the approver.

| Group | Block | Warn |
|---|---|---|
| words (reason, task subject) | every screening finding: link, e-mail address, markup, external image, hidden / control characters, instruction phrase, repeated text | phone-number-like digits |
| pattern | identical proposal already waiting; 10 proposals / hour; 3 assignments / hour | 3 or more proposals for one record in a day |
| state | any change to a converted lead; a status "change" to the same status | qualified -> unqualified; assigning a lead someone else owns; a task for someone other than the asker |
| tenant | record or assignee of another organisation | |
| the record's own text | the reason repeats an instruction found in the record | the record contains an instruction, hidden text or a link |

A rule that raises makes the verdict a block (`sentinel_error`): it fails closed. At approval
(`recheck=True`) only the state and tenant groups run again. `Verdict.to_json()` is what will be
stored with an accepted proposal: groups and warnings, never record text.

## The attack library (`backend/evals/attacks/library.json`)

55 texts in six families: instructions (13), hidden characters (9), links / images / markup /
addresses (13), floods (3), a phone number (1) and 16 ordinary texts (English, Telugu, Hindi,
rupee amounts, "ignore the noise", "act on it") that must pass untouched. Each case says exactly
which findings are expected and what must be gone from the clean text. Both test files read it, so
a new attack is one line of JSON.

Tests: `tests/test_screening.py` (199), `tests/test_sentinel.py` (89). With the link rule and one
instruction pattern switched off, 19 of them fail.

## Where it runs (SN2)

**`propose()`** (after the payload, visibility and pending-limit checks): the facts are read from
the database - the lead's tenant, status, owner and free text (company, job title, names, the last
10 activities, through `leads_api.lead_snapshot`), the asker's proposals in the last hour and of
assignments, the proposals for this record in the last 24 hours, an identical waiting proposal
(any asker), and whether the named colleague is an active member of this organisation - then
`sentinel.verify` runs. A block raises `ProposalBlockedError` (HTTP 422, `proposal_blocked`, the
reasons as sentences, `codes`); nothing is stored. An accepted proposal stores
`agent_actions.verification` (migration 0044): `{"version": 1, "checked": [...], "warnings":
[{code, message}]}` and the API returns the warnings as `warnings` on every proposal.

**Audit of a refusal.** The staff assistant proposes inside a savepoint that is rolled back when a
proposal is refused, so the audit entry is written *after* it by `approvals_api.audit_blocked`
(`agent_action.blocked`: kind, record id, asker, agent, rule codes - no text). Any other caller
must do the same, in a transaction it commits. The staff assistant tells the model the reasons,
so it can retry without the link.

**`approve()`** re-checks the state and tenant rules (`recheck=True`) inside the same savepoint as
the action: a lead that was converted or got the status while the proposal waited makes the
approval end as **failed** ("The lead already has this status."), nothing is changed.

**Settings:** `CRM_SENTINEL_PROPOSALS_PER_HOUR` (10), `CRM_SENTINEL_ASSIGNMENTS_PER_HOUR` (3),
`CRM_SENTINEL_BUSY_RECORD_PER_DAY` (3, a warning only). **Metric:**
`crm_ai_sentinel_findings_total{rule,severity}` (no tenant label).

**Limits to know.** Only leads have their free text screened; for an account or a contact the
record-text rules see nothing (their words, tenant and pattern rules still run). Hourly counts
include proposals that were rejected or expired: a flood is a flood.

Tests: `tests/db/test_sentinel_hook.py` (30, against the real database).
