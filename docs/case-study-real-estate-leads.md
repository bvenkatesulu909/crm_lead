# Case study: from a website chat to a qualified lead (real-estate sales)

> **DRAFT for the owner (CRM-113). Not for publishing yet.** **[verified]** = can be checked in this
> repository (the document or test is named). **[TO FILL]** = a fact only the client or the pilot can
> supply, left blank on purpose: a case study with invented numbers is worse than none. The page ends at
> the line below; the to-do list after it is not part of the page.

**Client:** [TO FILL - a real-estate agency in (city); name it only with the client's written OK]
**Built by:** [TO FILL - your name] **Pilot period:** [TO FILL]
**Status today:** a working, tested system; not yet running for the client's customers.

## The problem
Home buyers contact an agency through its website at any hour. Whoever answers must ask the same
questions every time (name, phone, property type, budget, area) and then judge which leads deserve a
salesperson's evening. Details get lost and each person judges "serious" differently.
[TO FILL - in the client's words: how enquiries arrive, how long the first reply takes, what is lost.]

## Scope
A CRM for the sales team, one customer-facing piece (a **website chat** that collects the buyer's details)
and one team-facing piece (an assistant that **suggests** whether a lead is qualified). The assistant never
changes a lead by itself; nothing is decided without a person.

## What was built
- **A chat that saves leads.** No account for the visitor; it collects name, phone and wish (property type,
  budget in rupees, area), saves **one lead per conversation**, cannot read any CRM data, and notifies the
  managers, who read the whole conversation on the lead. **[verified]** `docs/public-chat.md`
- **Qualification by the agency's own written steps.** The assistant reads a lead and those steps and
  suggests: qualify, mark unqualified, call first, or ask the buyer for missing details. **A different
  person must approve it**, and it can never mark a lead "converted". **[verified]** `docs/qualifier.md`,
  22 evaluation cases in CI
- **A safety net around every AI suggestion:** an approval queue, a rule-based check that blocks links and
  hidden instructions, a switch and a monthly budget per AI feature, and a cost estimate per feature.
  **[verified]** `docs/approvals.md`, `docs/sentinel.md`, `docs/agents.md`
- **Data kept apart:** a salesperson sees only their own leads, and one agency never sees another's - row-level
  security is forced on every table holding an organisation's data (60 of 60 at the latest migration,
  checked on a fresh database on 2026-11-03), and a test fails the build if a new one lacks it.
  **[verified]** `backend/tests/db/test_rls_tenant_tables.py`
- **Built to be run:** one-server deployment with HTTPS and encrypted nightly backups, rehearsed on a PC.
  **[verified]** `deploy/one-host/`

## Result
**Proven today [verified]:** about 3,500 backend tests plus frontend, browser and AI-evaluation tests pass;
a backup was really encrypted, restored and compared; a 22-check smoke test of the whole stack behind HTTPS
passes. This shows the system *works*, not that it *paid off*.

**What the pilot must show [TO FILL - leave blank until real data exists]:**

| Measure | Before (client) | After (system) |
|---|---|---|
| First message to a saved lead | [TO FILL] | [TO FILL] |
| Chats that end with a lead | [TO FILL] | [TO FILL] |
| Leads with budget and area filled in | [TO FILL] | [TO FILL] |
| New lead to first call | [TO FILL] | [TO FILL] |
| Suggestions approved vs. rejected | - | [TO FILL] |
| Estimated AI cost per saved lead | - | [TO FILL] |

Client quote, if given: [TO FILL - with their written OK].

## What I learned
- AI is most useful where it may **suggest, not act**: an approval costs seconds and removes the whole class
  of "it changed my data" mistakes. The evaluation cases that try to make it convert, link or obey a lead's
  own text fail, as they should. **[verified]**
- Running it for real found what tests alone had missed (a backup command that hung; a certificate problem
  that only appeared with the whole stack up). **[verified]** `docs/adr/0021-one-host-deployment.md`
- [TO FILL - one thing the client's feedback changed.]

---

## NOT PART OF THE PAGE - what you need to do before this can be published

1. **Get the client's OK in writing** (a message is enough) to name them, use their numbers and quote them.
   Until then write "a real-estate agency in (city)".
2. **This repository is public.** Do not commit the client's name, numbers or quote here. Keep the finished
   page for your resume and LinkedIn; the version in `docs/` stays a template.
3. **A result needs a pilot.** The chat is not online yet (it needs the server and your "go live" -
   `docs/deployment.md`). Plan two to four weeks of real use and write down the client's **"before" numbers
   first** (how long the first reply takes today, enquiries a week): they cannot be recovered afterwards.
4. **The "after" numbers come from the system:** chats and leads carry timestamps, the approval queue records
   approved and rejected suggestions, and the AI agents page shows an estimated cost. I can add a small
   read-only report that prints these for a date range so the table is filled from data - say so and I will
   propose it as its own step.
5. **Never include a buyer's real name, phone number or message.**
6. Replace every **[TO FILL]**, delete the **[verified]** tags and this list, and read the page aloud: if a
   sentence is not something the client would sign, change it.
