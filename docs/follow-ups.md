# Automatic follow-up messages (ADR 0036)

The CRM can draft a follow-up e-mail when a lead's follow-up task falls due. **It never sends one by
itself**: every draft waits in the approval queue until a person (the lead's owner or a manager)
reads it, may reword it, and approves it. Only then does the normal e-mail path send it, with its
consent, address and hourly-limit checks.

Decision record: [ADR 0036](adr/0036-automatic-follow-up-messages.md). Details of the approval
queue: [approvals.md](approvals.md) (sections on follow-up drafts, the rules, the scan and FM5).

## In one picture

1. A rep plans a **task** on a lead, due today.
2. About once a minute the **worker's scan** looks at today's due tasks (step FM4). For each lead it
   asks the **rules** (FM3) whether a draft may be made.
3. If yes, it fills in the organisation's **e-mail template** and **proposes** the draft as the
   CRM's Automation identity (author "the follow-up assistant"). The Sentinel checks the text.
4. The owner and the managers get a **notification**. The lead page shows "Follow-up e-mail: …"
   under *AI proposals*.
5. The owner or a manager opens it, sees **exactly what will be sent**, may **reword** the subject
   or text (checked again; links are refused) and **approves** it, or rejects it with a reason.
6. Only after approval is the e-mail queued; the worker sends it with Reply-To the approver.

## What stops a draft (all checked by code, tested)

| Reason code | Meaning |
|---|---|
| `consent_withdrawn` | The lead opted out of e-mails. Always stops, also at sending time. |
| `consent_unknown` | Nobody asked yet, and the lead did not start the conversation (website chat or form, or a logged e-mail from them). |
| `no_address` | The lead has no e-mail address. |
| `lead_closed` | Converted or unqualified. |
| `no_owner` / `owner_inactive` | Nobody owns the lead, or the owner left. |
| `reply_received` | The lead wrote to us after the task was set. |
| `draft_waiting` | A draft for this lead already waits. |
| `cooldown` | A draft was made for this lead within the cooldown (7 days by default). |
| `monthly_cap` | Already the maximum number of drafts for this lead in 30 days (3 by default). |
| `daily_cap` | The organisation's drafts for today are used up (100 by default; 100 is the most). |
| `owner_pending_cap` | The owner already has this many drafts waiting (20 by default). |

Each organisation switches the feature on itself; the platform switch `CRM_FOLLOW_UPS_DISABLED=true`
stops every organisation at once.

## Screens

- **Automation > Follow-ups** (administrators, permission `follow_up:manage`): switch on, choose the
  template, set the five limits. The history of every change is kept and audited.
- **Approvals** and the **lead page**: the draft with its full text; *Approve* opens a dialog with
  the subject and text ready to reword.
- **Reports > Follow-ups: drafts and replies** (managers and administrators): see below.

## The figures (step FM7)

Report key `follow_ups` (`GET /api/v1/reports/follow_ups?start=…&end=…`, also as CSV). Two sections,
counts only (no lead, name, address or text):

1. **Follow-up drafts and what people did with them**, one row per rule: drafts made in the period,
   approved, approved after rewording, rejected, expired, could not be sent, still waiting; the
   approved share (approved of approved + rejected), the reworded share (of approved) and the
   median minutes to a decision.
2. **Replies within 14 days of an approved follow-up**, one row per rule: follow-ups approved, how
   many leads wrote back within 14 days after the approval, and the reply rate. A "reply" is a
   received e-mail someone **logged** on the lead, so a reply nobody logged is not counted: the
   rate is a lower bound.

Rejection notes stay on each proposal (the colleague who asked sees why); the report counts
rejections but does not show the free-text notes, which may name people.

## Not built

- **FM6, the optional writer agent** (a model writes the draft instead of the template): the owner
  decided templates first and the writer only if wanted later.
- **Bounce handling** (an address that bounces) is to be decided before an organisation reaches
  about 100 follow-ups a day.
- Only one rule exists (`task_due_today`); others need a new ADR decision.

## How to try it locally

1. Create an e-mail template (E-mail > Templates).
2. As an administrator, open Automation > Follow-ups, tick *Make follow-up drafts*, choose the
   template, save.
3. On a lead with an e-mail address and consent "Agreed to e-mails", plan a task due today.
4. Run the worker once: `python -m app.worker --once` (in `backend`, venv active).
5. The draft appears under *AI proposals* on the lead; approve it, run the worker again, and the
   e-mail arrives in Mailpit (http://localhost:8025).

The Playwright journey `frontend/e2e/follow-ups.spec.ts` does exactly this.
