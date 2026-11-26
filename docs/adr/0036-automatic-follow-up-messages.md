# ADR 0036 — Automatic follow-up messages (drafted by the system, sent only after a person approves)

- **Status:** Accepted (2026-11-21, the owner answered section 7; the answers are recorded in section 7a)
- **Date:** 2026-11-21
- **Deciders:** Project owner
- **Depends on:** ADR 0012 (Communication Center), ADR 0014 (approval queue), ADR 0016 (agent registry, budgets,
  kill switch), ADR 0017 and 0018 (Sentinel, cleaning of untrusted text), ADR 0006 (events and the workflow
  engine), ADR 0009 (row-level security)
- **Owner's list:** item 13, "Automatic follow-up messages"

## 1. The problem

Follow-ups are where leads are lost: a rep promises to write "in two days" and forgets. Today a rep can send an
e-mail by hand from the Communication Center, and a workflow rule can create a *task* ("follow up"), but nothing
prepares the message itself. The owner wants follow-up messages to appear **automatically**.

"Automatic" is the dangerous word. A message that leaves the company is outward-facing and cannot be taken back.
It goes to a real person who may have withdrawn consent, and its text may be written by a model that has read
text typed by strangers. So this ADR separates two things:

- **Automatic preparation** - the system notices that a follow-up is due and a **draft** appears (v1: always).
- **Sending** - happens **only after a person approves** (v1: always). No setting in v1 removes that person.

## 2. What exists (and is reused, not rebuilt)

| Piece | What it gives us |
|---|---|
| `communications` module | `email_templates` with six fixed placeholders, `email_messages`, `send_email()` that checks the recipient is readable, has an address, has not withdrawn consent, and is under the hourly limit; the worker job `communication.email` that **re-checks consent just before sending** and is safe to run twice; the failure event and notification; audit `email.queued` |
| Approval queue (ADR 0014) | A catalogue of proposal kinds with strict payloads; a **different** person approves; version and expiry checks; the action runs through the owning module's `api.py` as the approver; per-person pending limits; audit |
| Sentinel (ADR 0017/0018) | Blocks links, instruction-like text, addresses, duplicates, wrong state; runs again at approval time |
| Agent registry (ADR 0016) | Switch (off by default), monthly token budget, tool filter, platform kill switch, usage on the AI agents page |
| Events and workflow engine (ADR 0006) | Domain events published in the same transaction; a worker that dispatches them; a scheduler that already finds "a task is overdue" and "a quote is expiring"; rules with a loop-depth limit and an hourly limit |
| Activities | Tasks with due dates on leads, accounts, contacts and deals (the natural "a follow-up is due" signal) |

Two facts found while reading the code, which shape the design:

1. **Consent exists only on contacts** (`email_consent`: unknown / yes / no). A **lead has no consent field**, so
   today `send_email` to a lead can never be refused for consent, and the worker's consent re-check looks at
   contacts only. A follow-up engine that mails leads would have no "stop" at all for the people it is most
   likely to mail. This must be closed first (decision FM2).
2. Nothing sends a message *as the system*. `send_email` needs a signed-in sender, whose address becomes the
   Reply-To and whose hourly limit is used. A follow-up keeps that: it is sent **in the name of a real, named
   person** (the approver), never anonymously.

## 3. Decisions (proposed)

**FM1 - Drafts are proposals, and the approval queue is the only road to sending.** A new approval kind
**`communication.send_follow_up`** is added to the fixed catalogue (ADR 0014 decision 3). Its payload is strict
(extra fields refused): the target record (a lead or a contact), the template id **or** a subject and body, and
a reason code (why this follow-up, e.g. `no_reply_5_days`, `task_due`, `quote_sent_no_answer`). Approving it calls
`communications_api.send_email` **as the approver** through the existing path - so the recipient check, the
address check, the consent check, the hourly limit, the queue, the consent re-check in the worker and the audit
all apply unchanged. There is no second sending path and no new job kind for sending.

**FM2 - Consent is made real for leads before anything is automatic.** Add `email_consent` (unknown / yes / no,
with the date) to leads with the same rules as contacts, carried over on conversion, and honoured by
`send_email` for leads exactly as for contacts. The website chat may set it to `yes` only when the visitor said
so. **A "no" stops every message to that person, whatever created it** (manual, template, follow-up), and it is
re-checked at three moments: when the draft is made (no draft is created), when it is approved (the approval
fails with "consent withdrawn"), and in the worker just before sending (the existing re-check, extended to
leads). A follow-up to a person whose consent is `unknown` is allowed in v1 only for **service follow-ups about a
conversation the person started** (they filled the form, wrote to us or asked for a quote), not for marketing;
see question 2. *(This is a separate small step with its own migration and screens; it is useful on its own.)*

**FM3 - A deterministic rule finds who needs a follow-up; a model, if used at all, only writes words.** The
"is a follow-up due?" decision is **code**, not a model: a **follow-up policy** per organisation made of simple
rules from a fixed menu, for example
- "a lead in status `contacted` with no logged activity or e-mail for N days",
- "a sent quote with no answer N days after it was sent",
- "a follow-up task on a lead became due today",
- (later) "a contact has had no interaction for N days and has an open deal".

The menu is fixed in code like the workflow catalogue; an administrator picks rules, sets N (within limits) and
switches them on. Each rule produces at most **one draft per person per rule per cooldown** (default 7 days), and
at most **3 follow-ups per person per month** in total (default), whatever the rules say. Stop conditions are
checked first: consent `no`, the lead or deal is closed (won, lost, converted, unqualified), a reply arrived
after the trigger, an unanswered draft is already waiting for that person.

**FM4 - Where the words come from: templates first, a model optional and second.**
1. **v1a - templates only.** The draft is an existing active e-mail template with the six fixed placeholders
   filled by the existing preview code. No model, no tokens, no generated text to worry about. This alone
   delivers "the follow-up is ready, one click to approve".
2. **v1b - optional agent "Follow-up writer".** A new registry entry (`follow_up_writer`, **off by default**, a
   token budget, tool filter, platform switch) may *personalise* the draft: it reads cleaned facts (the lead's
   stage, the last notes, the quote summary - as the owner would see them) and writes a short subject and body
   through **one tool** `submit_draft`. The answer is checked strictly (length limits, no link, no address, and
   no promise of a price, discount, date or legal commitment: a cleaning rule refuses such a draft, it does not
   repair it). The text then passes the Sentinel like every other proposal. Record text is data, never
   instructions, as everywhere else.

**FM5 - The approver sees exactly what will be sent.** The approval card shows the recipient (name; the address
masked in lists, full on the detail page for people who may read it), the subject, the full body as plain text,
the reason in words ("No reply for 5 days after the quote was sent"), the consent state, and the Sentinel's
safety check. The approver may **edit the text before approving** (an edit is re-screened; the audit records who
changed which field, never the text). Rejecting records a reason that feeds the figures in FM7.

**FM6 - Who approves.** The "requester" of a system-made draft is the **Automation identity** (already used by
the Qualifier and the website chat), so the no-self-approval rule of ADR 0014 holds naturally. The practical
default: **the record's owner** approves drafts for their own leads, and a sales manager can approve any.
Question 3 asks whether only managers should approve.

**FM7 - How a draft is created (the moving parts).** The worker's scheduler (once a minute, already exists) gets
one new scheduled job, `follow_up.scan`, per organisation that has the feature switched on. It runs the FM3
rules as the Automation identity under tenant scope and row-level security, **in small batches** (at most 50
candidates per run), and for each candidate calls the approvals module `propose()`. Candidates come from new read
functions in the owning modules' `api.py` (leads, activities, quotes, contacts); the `communications` module owns
the policy tables and the scan and imports only other modules' `api.py` (import-linter contracts unchanged). New
domain events **`follow_up.proposed`**, **`follow_up.sent`** and **`follow_up.rejected`** (ids and the reason
code only) notify the owner through the existing notification system and feed the cooldown and the figures.
The scan is **safe to run twice** (a unique key on person + rule + cooldown window).

**FM8 - Limits and kill switches (all tested).**
- Per person: at most 3 follow-ups a month by default; administrators may lower it, never raise it above 8.
- Per organisation: at most 200 drafts a day; at most 20 waiting drafts per owner; a waiting draft expires after
  7 days, and an expired draft is not re-created until its cooldown has passed.
- One switch "Automatic follow-ups" per organisation (off by default; it stops every rule) plus the platform
  switch `CRM_FOLLOW_UPS_DISABLED`. While off, new drafts stop at once and waiting drafts can be rejected but
  **not approved**.
- Withdrawn consent (FM2) needs no setting and cannot be switched off.

**FM9 - Audit, privacy, isolation.** Every new table has `tenant_id`, forced RLS and an insert-only history (a
rule change is a new row). Audit entries (`follow_up.policy_changed`, `follow_up.proposed`,
`follow_up.approved`, `follow_up.rejected`) carry ids, rule keys and codes only - **never the subject, the body or
the address**. The draft text lives only in the proposal and, once sent, in `email_messages`, under the same
read rules as other e-mails. The tenant comes only from the verified token; the client can send neither a tenant
nor an address; a recipient is a lead or contact id loaded through the scoped repository (404 if not readable).

**FM10 - What this ADR deliberately does not do (v1).**
- It does **not** send without a person's approval. "Auto-send" of low-risk template-only follow-ups is a possible
  later ADR, only after the figures show a very low rejection rate, and never when consent is `unknown`.
- No SMS, WhatsApp or calls (each channel needs its own consent and provider rules).
- No marketing sequences or bulk campaigns (Phase 16).
- The system never changes a lead's status, owner or a deal's stage because of a follow-up.
- No open or click tracking (privacy); "a reply arrived" is read from logged received e-mails.
- No model-written text without the Sentinel and without a person reading it.

## 4. Steps (each is a small, reviewed change that ends with a stop)

| Step | What | Done when |
|---|---|---|
| FM0 | This ADR and the owner's answers | Status Accepted |
| FM1 | **Consent on leads**: migration (`leads.email_consent`, `_at`, database checks), API, form, lead page; `send_email` and the worker re-check honour it; carried over on conversion; website chat sets `yes` only on an explicit statement | tests: refused for `no`, re-check in the worker, tenant isolation, role denial, ID tampering; RLS guard passes |
| FM2 | **Approval kind** `communication.send_follow_up`: payload, description, plan and outcome, Sentinel rules (no link or address, consent, state, one waiting draft per person); the action calls `communications_api.send_email` as the approver | database tests incl. consent withdrawn between draft and approval, a colleague's lead gives 404, no self-approval, expiry |
| FM3 | **Policy tables** (`follow_up_policies`, insert-only, forced RLS) and the pure rules module (fixed menu of rules, cooldowns, monthly cap, stop conditions) | pure tests for every rule and stop condition; each protection shown to fail when removed |
| FM4 | **The scan**: worker job `follow_up.scan`, new read functions in other modules' `api.py`, the three events, notifications, batch and organisation limits, idempotency key | database tests incl. the real worker, running twice, both kill switches, limits |
| FM5 | **API and screens**: settings page for administrators, approval card with the full text and edit-before-approve, "Follow-ups waiting" card on the lead page | component tests and a Playwright journey (rule on, draft appears, owner edits and approves, real e-mail in Mailpit with Reply-To the owner, consent `no` stops the next one) |
| FM6 | **Optional writer agent** `follow_up_writer` (registry entry off by default, one tool, strict answer, banned-promise rules) and BP-10 evaluation cases (scripted CI gate; a paid run only with the owner's yes) | evaluation gate in CI; deliberate breaks caught |
| FM7 | **Figures** in the Reports module (drafts made, approved, edited, rejected with reasons, replies after a follow-up, per rule) and `docs/follow-ups.md`; refreshed inventory | numbers match the database in tests |

FM1 is useful alone and is the prerequisite for everything else. FM6 is optional and may be skipped.

## 5. Alternatives considered

- **Send automatically, notify afterwards.** Rejected for v1: an e-mail cannot be recalled, a bad rule or a model
  could mail the wrong person, and consent on leads does not exist yet.
- **A workflow "send e-mail" action.** None exists, and adding one would create a second sending path that skips
  the approval queue. The engine's scheduler is used only as the **clock**.
- **Let a model decide who to follow up.** Rejected: the decision is simple, testable and explainable as code
  ("5 days, no reply"); a model would be costly, unpredictable and open to injection from lead text.
- **Tasks only** (what rules can already create). Still available and complementary; a rule may create a draft
  and a task.
- **A separate drafts table outside the approval queue.** Rejected: it would duplicate expiry, limits, the
  Sentinel, no-self-approval and audit that the queue already has.

## 6. Risks and how they are handled

| Risk | Handling |
|---|---|
| Mailing someone who said no | FM2: consent on leads, three checks (draft, approval, worker), cannot be switched off, tested at each moment |
| Spamming a person | monthly cap, cooldown per rule, one waiting draft per person, the existing hourly send limit |
| A model writes a link, a price promise or leaks data | writer is optional and last; strict answer check; banned-promise rule; Sentinel; a person reads every word; the model sees only cleaned data the owner may see |
| Poisoned text in a lead steers the writer | record text is data; Sentinel warns or blocks; the card shows the safety check (ADR 0017/0018) |
| Approval fatigue (clicking Approve without reading) | the card shows the full text and the reason; rejection reasons and the edit rate are measured (FM7); no bulk approve in v1 |
| A wrong rule floods the queue | batch size, daily and pending caps, expiry, organisation switch, platform switch |
| Mail reputation (Brevo) | low volume by the caps; bounce and complaint handling is **not** in v1 (question 10) |
| Personal data in logs and audit | ids and codes only (FM9); tested |
| Owner has left the company | a deactivated person cannot approve; their waiting drafts expire or move with the lead |

## 7. Questions for the owner (recommended answer first)

1. **Is "a person approves every message" right for v1?** *Recommended: yes, always.* Alternative: later, let an
   administrator allow template-only follow-ups to contacts with consent `yes` to go without approval (a new ADR).
2. **What if consent is `unknown`?** *Recommended: a follow-up may be drafted only about a conversation the
   person started (form, chat, quote request); promotional follow-ups need `yes`.* Alternative: require `yes`
   for everything (safest, but almost no website lead would ever get a follow-up).
3. **Who approves a system-made draft?** *Recommended: the record's owner, and managers can approve any.*
   Alternative: only managers.
4. **Which rules are on the first menu?** *Recommended: three - contacted lead with no activity for N days, sent
   quote with no answer N days after sending, follow-up task due today.*
5. **Defaults for the caps?** *Recommended: 3 per person per month, 7-day cooldown per rule, 7-day expiry of a
   waiting draft, 200 drafts per organisation per day.*
6. **Templates first, model later?** *Recommended: yes - FM1 to FM5 with templates only, then decide on the writer
   agent (FM6) after seeing real approvals.* Alternative: build the writer in the first pass.
7. **Reuse the existing e-mail templates?** *Recommended: yes, with a new optional "follow-up" label so each rule
   can name its template.*
8. **Consent of existing leads?** *Recommended: all current leads start as `unknown`; contacts keep their value;
   nothing is set to `yes` except an explicit statement (a form tick or a chat confirmation).*
9. **Language?** *Recommended: use the lead's preferred language (ADR 0027) when a template exists for it, else
   English; Hindi and Telugu templates are written by the organisation.*
10. **Bounce and complaint handling?** *Recommended: not in v1; a small ADR before the organisation sends more than
    about 100 follow-ups a day.*

## 7a. The owner's answers (2026-11-21)

1. Yes: a person approves every message in v1.
2. Yes: with consent `unknown`, a draft only about a conversation the person started; promotional needs `yes`.
3. Yes to both: the record's owner approves their own drafts and a sales manager can approve any.
4. **Only one rule on the first menu: "a follow-up task on a lead is due today".** The other rules (no activity
   for N days, quote with no answer) are not built now; they would be a later amendment.
5. 7-day cooldown per rule; the other caps stay at the recommended defaults (3 per person per month, 7-day expiry
   of a waiting draft, 200 drafts per organisation per day).
6. Yes: templates first (FM1 to FM5), the writer agent (FM6) only afterwards and only if wanted.
7. Yes: reuse the existing e-mail templates with an optional "follow-up" label.
8. Yes: existing leads start as `unknown`; nothing becomes `yes` without an explicit statement.
9. **English and Telugu** (no Hindi templates for follow-ups in v1): the lead's preferred language when it is
   English or Telugu and a template exists, else English.
10. Bounce and complaint handling is not in v1; a small ADR is needed **before an organisation passes about 100
    follow-ups a day**. Until then the 200-per-day cap is lowered to **100 drafts per organisation per day**.

Effect on the steps: FM3 builds the rule menu with the single rule `task_due_today`; FM4's scan reads due
follow-up tasks of leads (and contacts) through the activities module's `api.py`.

## 8. Consequences

New: `follow_up_policies` (plus consent columns on `leads`), one approval kind, one worker scan, a settings page,
an approval-card extension and an optional agent. Cost: more review surface in the approval card and a real
change to leads (consent). Benefit: no follow-up is forgotten, no message leaves without a person's eyes and a
consent check at three moments, and every protection already built is reused instead of bypassed.
