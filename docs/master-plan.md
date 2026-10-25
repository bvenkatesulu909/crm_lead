# Master plan — everything in "CRM-Lead — Final Status Review (Venkatesh).pdf"

- **Written:** 2026-10-24, from the PDF (state of `main` at `ec41dbc`, 22 Oct) checked against
  `main` at `5c578f6` (24 Oct).
- **Status:** plan only. Nothing here is built yet. Each object starts only when the owner says so.

## 0. How we work (applies to every object below)

**One object at a time. An object is finished before the next one starts.**

For each object:

1. **Design first.** The PDF gives full detail for only 5 blueprints (BP-01, 04, 05, 16, 29); the
   other 25 are titles only. So every object starts with a short design (an ADR when it adds a
   module, a public endpoint, an outside service or anything that sends data outside). The owner
   approves it.
2. **Steps.** Split the object into small steps (like CC1–CC6). Each step: read code → test first
   → build layer by layer (models → migration with forced RLS → rules → repository → policies →
   schemas → service → router → api.py) → run tests → commit → **stop for review**.
3. **Finish.** Full test run (backend, Vitest, Playwright, build) → one PR → CI green → review →
   merge → mark done in `implementation-plan.md` and `CLAUDE.md`.

Corrections to the PDF that apply everywhere:

- Migration numbers in the PDF ("after 0028", "0029", "0030", "0045") are out of date. The head
  is **0037**; the Communication Center takes **0038**; every later object takes the next free
  number when it is built.
- ADR numbers: 0011 is taken, 0012 is the Communication Center. New ADRs start at **0013**.
- The PDF suggests SQLite for local tests. Project rule: tests use **real PostgreSQL**. Not used.
- The PDF's "Phase 1–4" clashes with the plan's Phases 0–21. In this plan they are called
  **AI Track A1–A4**.
- Model names, laws and limits in the PDF ("DeepSeek V4.1 Flash 1017", TRAI Sept 2026 caller
  series, NPCI ₹15,000 Reserve-Pay cap, RBI 24-hour mandate) must be **checked against the
  official source** before any rule is coded on them.
- Paid outside services (Sarvam, Exotel/Plivo, Razorpay, HeyGen, Photoroom, Twelve Labs, Exa,
  Browserbase…) run in **test/sandbox mode or a local fake** until the owner says "go live"
  (ADR 0007). No real money and no real customer data leave the computer before that.

## 1. Owner track — things only Venkatesh can do (no code)

| # | Item (PDF reference) | Status | Needed before |
|---|---|---|---|
| O1 | **CRM-101 / T0.1:** open the affected agent's Role mapping in Keycloak; remove `sales_manager` / `tenant_admin` if present; sign out and in; send the 2 screenshots (role mapping, Leads list as that agent) | Open | Closing CRM-101 |
| O2 | **CRM-103 / T1.2:** protect `main` on GitHub (Settings → Branches: require a PR and passing CI) | Open (GitHub says "Branch not protected") | Next PR |
| O5 | **T2.2:** choose a host for the API (ADR 0007) so Netlify can reach it | Open | Live demo |
| O6 | Keep Docker Desktop + `docker compose up -d` running for database tests (T0.2, T3.1) | Done today | Every object |
| O7 | Career work: resume v1, LinkedIn/Naukri text, 10 applications and 5 referral messages a day, job tracker, interview stories, 33 target employers (referral steps F.1–F.7) | Owner's own | — |

## 2. Tickets and Tasks 0–3

| Item | What | Status today | What is left |
|---|---|---|---|
| CRM-101 / Task 0 | One agent sees another agent's leads | Code done: RLS on leads (tenant + owner), role boundary tests | O1 (screenshots, role check) |
| CRM-102 | The fix for CRM-101 | Done (PR #1) | — |
| CRM-103 / Task 1 | Failing settings test via PR, then protect `main` | Test fixed (PR #7) | O2 |
| Task 3 | RLS on core tables (target 7 of 47) | Done, more than asked: 50 of 50 tables | — |
| **CRM-104 / Task 2** | Approved chatbot with real-estate lead capture | Not started | = object **BP-01** below |

## 3. Order of all objects

| Order | Object | Why here |
|---|---|---|
| 1 | **Communication Center (CC1–CC6)** | Already started (CC0 done, baseline green). Rule: finish what is started. BP-12 needs it. |
| 2 | **BP-01** (CRM-104 / Task 2) | The last open PDF task; the demo depends on it |
| 3 | **BP-04 leftovers** | Small finish of an almost-done object |
| 4–6 | BP-05 → BP-10 → BP-11 | Rest of AI Track A1 (safety first: approvals, evals) |
| 7–13 | BP-14 → BP-21 → BP-29 → BP-09 → BP-08 → BP-15 → BP-20 | AI Track A2 (governance) |
| 14–21 | BP-02 → BP-03 → BP-12 → BP-13 → BP-18 → BP-22 → BP-23 → BP-28 | AI Track A3 (autonomous workflows) |
| 22–31 | BP-07 → BP-06 → BP-16 → BP-27 → BP-17 → BP-24 → BP-19 → BP-25 → BP-26 → BP-30 | AI Track A4 (voice, payments, media) |
| After | Marketing (Phase 16), Integrations (Phase 19), Teams | Existing plan; Integrations may move earlier if BP-17/BP-27 need its webhook base |

**Decided (owner, 2026-10-24):** keep this order — Communication Center (CC1–CC6) first, then
BP-01. The PDF's 26 Oct demo date is not kept. This file is committed together with CC1.

## 4. The objects in detail

Size: **S** = 1–2 steps, **M** = 3–5 steps, **L** = 6+ steps or outside services.
"Builds on" = code that already exists and must be reused, not rebuilt.

### Object 1 — Communication Center (ADR 0012, steps CC1–CC6)
See `docs/adr/0012-communication-center.md` and Phase CC in `implementation-plan.md`.

### AI Track A1 — security and the conversational base

| # | Blueprint | What it means in this CRM | Builds on | Design | Size |
|---|---|---|---|---|---|
| BP-01 | Public chat that saves a lead (`feature/public-chat-save-lead`) | **A:** DeepSeek tool calling in `DeepSeekChatModel` (OpenAI format; Anthropic unchanged). **B:** lead fields `property_type`, `budget_min_inr`, `budget_max_inr` (whole rupees), `location` + checks. **C:** `public_chat` module, `POST /api/v1/public/chat` with one `save_lead` tool, guardrails, server-side tenant, per-IP rate limit, `fake` provider for tests, Next.js `/api/chat` + `/chat` page, Playwright journey | `assistant/llm.py`, `guardrails.py`, leads module | **ADR 0013** (first endpoint where anyone without login creates data) | L |
| BP-04 | Identity-bound permissions, PII guard, FORCE RLS | **Done** (RLS on leads by owner, all tables forced, Aadhaar/PAN scrubbing). **Finished 2026-10-25:** role badge in the user menu ("own" vs "all tenant") and a Playwright check that agent 1 gets "not found" on agent 2's lead | identity, `knowledge/pii.py` | none | S |
| BP-05 | Approval queue for AI actions (`feature/agent-approvals`) | New `approvals` module: `agent_actions` (pending/approved/rejected/expired, forced RLS); AI proposes, manager approves; no self-approval; action runs in the same transaction with audit and a row lock; cards on the Automation page | workflows, audit, notifications | **ADR** | M |
| BP-10 | Agent evaluation harness in CI (design note: `docs/agent-evals.md`, approved; EV1 done) | Fixed test conversations with a fake model: right tool chosen, right arguments, no forbidden tool; RAG answer set with expected citations; runs in CI without paid keys | existing opt-in live evals | short design | M |
| BP-11 | CRM MCP server | A read-only `crm-lead` MCP server already works in Claude sessions, but its code is **not in this repository**. Step 1: locate it and bring it into the repo with tests and Keycloak sign-in; later, write tools only through BP-05 approvals | identity | **ADR** | M |

### AI Track A2 — governance, firewall, cited RAG

| # | Blueprint | What it means in this CRM | Builds on | Design | Size |
|---|---|---|---|---|---|
| BP-14 | Agent registry, budget caps, kill switch | Table of the CRM's AI agents (chat, assistant, research…): owner, allowed tools, per-tenant monthly budget, on/off switch checked before every AI call | BP-05, settings | **ADR** | M |
| BP-21 | "Sentinel" action verifier + prompt-injection firewall | A second, rule-based check on every AI-proposed action before it reaches the approval queue (allowed fields, value ranges, tenant match); stronger input screening | BP-05, guardrails | design | M |
| BP-29 | Verification artifacts + ForcedLeak / BodySnatcher defences | Each proposed action stores a record: state before/after, rules checked. Inputs from public forms are cleaned (hidden HTML, zero-width characters, external image links) before any prompt; identity only from the verified token, never from tool arguments | BP-05, BP-21 | design | M |
| BP-09 | AI usage and cost per tenant | `ai_usage` table (tenant, feature, model, tokens, cost in `Decimal`, latency) and a usage page. Prometheus metrics stay without tenant labels (current privacy rule) | `observability/metrics.py`, price settings | design | M |
| BP-08 | Cited RERA / brochure answers + "I don't know" gate | Property brochures and RERA numbers in the knowledge base; answers must cite a source or refuse | knowledge module (pgvector, citations, feedback) | design | M |
| BP-15 | Live RERA / company web check | An agent looks up a RERA number or company on public websites and stores the evidence | BP-14 budgets, BP-05 | **ADR** (sends data outside; site terms; SSRF protection) | L |
| BP-20 | CI security gate | Add dependency audit (`pip-audit`, `npm audit`), secret scan, "no float for money" check, RLS guard (exists) as required CI jobs | CI workflow | short design | S–M |

### AI Track A3 — autonomous CRM workflows

| # | Blueprint | What it means in this CRM | Builds on | Design | Size |
|---|---|---|---|---|---|
| BP-02 | One-click lead and company enrichment | Button on a lead: fill company size, website, industry from an outside data source; every change shown before saving | BP-14, BP-05 | **ADR** (lead data sent outside) | L |
| BP-03 | Qualification procedures (AOPs) | Admin writes plain-English qualification steps; the AI follows them and **proposes** stage changes through BP-05 | BP-05, workflows | design | M |
| BP-12 | Automatic follow-up sequences | Timed e-mail sequences (day 0, 2, 7) that stop when the lead replies or converts | **Communication Center**, outbox, workflows | design | M |
| BP-13 | Deal risk and forecast | Risk score per deal (no activity, stage age, missing contact) and a forecast view | sales, dashboard, reports | design | M |
| BP-18 | Multi-agent deal desk + no-code agent builder | Several AI roles (pricing, terms, risk) prepare a deal review; admins configure simple agents from allowed tools | BP-05, 14, 21 | **ADR** | L |
| BP-22 | Buyer memory with fact / assumption / gap labels | Per lead or contact, a structured memory; every item labelled fact, assumption or open question, with its source | leads, contacts, assistant | design | M |
| BP-23 | Site-visit brief and negotiation helper | 5 minutes before a site visit, the agent gets a brief (buyer memory, budget, open questions); scheduling help. "Agent-to-agent negotiation" needs a clear definition first | activities, notifications, BP-22 | design | L |
| BP-28 | Parallel research over many accounts | Run research for up to 50 accounts in the worker, within budget caps, results in a grid | BP-14, BP-15, worker | design | L |

### AI Track A4 — voice, telephony, payments, media

| # | Blueprint | What it means in this CRM | Builds on | Design | Size |
|---|---|---|---|---|---|
| BP-07 | Voice lead capture in English / Hindi / Telugu | Add a Sarvam provider next to the existing `openai`, `elevenlabs`, `local` voice providers; language choice in the recorder | `voice/provider.py` | design | M |
| BP-06 | Call / site-visit scribe (MEDDIC / BANT) | Transcript of a call or visit → structured fields proposed on the deal | BP-07, BP-05 | design (recording consent) | M |
| BP-16 | Telugu voice receptionist with locked prices | Spoken answers about price and EMI only from catalogue figures (integer rupees); any other number in the reply is blocked; recording consent required | BP-07, catalogue | **ADR** | L |
| BP-27 | Telephony bridge (Exotel / Plivo) + call clarity | Real phone calls into the voice flow | BP-16, Integrations webhooks | **ADR** (telecom rules, outside accounts) | L |
| BP-17 | Razorpay booking-token payment link + signed webhook | Send a payment link; a verified, idempotent webhook marks the booking paid | invoices, Integrations webhooks | **ADR** (payments; test mode only) | L |
| BP-24 | UPI limits and mandate rules | Guards on the BP-17 flow; the limits must come from official NPCI/RBI documents | BP-17 | design | M |
| BP-19 | Property photo enhancer + video search | Improve listing photos; search inside walkthrough videos | documents | **ADR** (outside services) | L |
| BP-25 | Sales-call highlight clips | Short clips from recorded calls with their transcript | BP-06, BP-27 | design | L |
| BP-26 | Personal video briefs (avatar) | Short multilingual video for a buyer's deal room | BP-05 approvals | **ADR** (consent for likeness/voice, outside paid service) | L |
| BP-30 | Brand-locked proposal deck | Proposal document in the tenant's colours and logo, made from quote data | quote PDF (ReportLab), documents | design | M |

## 5. The "Top-250 / Top-77 / Top-500" lists

These lists in the PDF are **not separate work items**:

- The **"Source inspiration"** column names the company product each blueprint copies an idea
  from (e.g. BP-01 ← Salesforce Agentforce, BP-05 ← Palantir). It goes into the design note and
  the interview talking point, not the code.
- The **33 India target employers** table is career material (owner track O7).
- In the PDF the last table is cut off after BP-14, and the endpoint column of the quick index is
  cut at the page edge, so those details must come from the design step of each object.

## 6. Done definition for the whole plan

- Every object above merged through a PR with green CI and owner review.
- `implementation-plan.md` and `CLAUDE.md` updated after each object, with dates and real test
  numbers.
- No secrets in git; no paid service called with real data before "go live".
