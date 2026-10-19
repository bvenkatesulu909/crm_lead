# Customer relationship depth (Phase B2)

This phase makes the CRM *use* customer data, not just store it. Everything below is stored in PostgreSQL or calculated from stored records, and every number can be explained.

## What was added

| Requirement | What the CRM does now | Where |
|---|---|---|
| **Customer segmentation** | New account fields: country (ISO code), region, city, lifecycle stage (prospect → onboarding → active → at risk → churned), account type (company / headquarters / subsidiary / branch), preferred language. The list filters by segment, country, lifecycle stage, industry, owner and **customer value** (issued invoices ≥ an amount in one currency). | Accounts list and forms; `GET /accounts?country=&lifecycle_stage=&industry=&account_type=&min_value=&value_currency=` |
| **Account hierarchy** | Parent/child links (Phase B), plus the account type for head offices, subsidiaries and branches. | Account page → Company hierarchy |
| **Communication preferences** | Preferred language for accounts and contacts, alongside channel, e-mail consent and do-not-call (Phase B). | Account and contact forms |
| **Duplicate detection** | Before creating an account or contact, the CRM looks for possible matches and asks for confirmation. Matches you may not see are only **counted**, never named. | Create forms; `GET /accounts/duplicates`, `GET /contacts/duplicates` |
| **Relationship ownership and transfer** | Managers transfer a customer to another sales employee with a **reason**. By default the previous owner's contacts, **open** deals and **open** tasks on that customer move too. Closed deals keep whoever won them. Everything happens in one transaction and is audited. | Account page → "Transfer customer"; `POST /accounts/{id}/transfer` |
| **Customer retention / health** | A health score (0–100) built from visible factors, an **inactive** indicator (no interaction for 90+ days, or never), and the lifetime value. A Customer health page lists customers least healthy first. | Account page → Customer health; Accounts → Customer health; `GET /accounts/{id}/health`, `GET /customer-health` |
| **Lead scoring** | Every lead gets a 0–100 score and a priority (hot 70+, warm 40–69, cold under 40). Lists can be sorted and filtered by score, and the lead page lists every factor. | Leads list and lead page; `GET /leads?sort=-score&priority=hot`, `GET /leads/{id}/score` |
| **Customer feedback** | Tickets have a category (question / problem / request / **complaint** / feedback). Customers rate a resolved ticket from 1 to 5 stars, once, with an optional comment. The executive dashboard shows complaints and average satisfaction. | Portal ticket page; staff ticket page and list; `POST /portal/tickets/{id}/rating` |
| **Interaction history, follow-ups, 360°** | Already delivered in Phases B and D (relationship timeline, activities, tasks, reminders). | Account, contact, lead and deal pages |

## How the numbers are made

### Duplicate matching (`app/core/matching.py`)
A record counts as a possible duplicate when any of these match:

| Match | Rule |
|---|---|
| **Company name** | Compared ignoring capitals, punctuation and legal forms, so "Example Ltd" = "example limited" = "EXAMPLE GmbH". |
| **Website** | The same domain ("https://www.example.com/about" = "example.com"). |
| **Phone** | The last 9 digits, so "+44 20 7946 0018" = "020 7946 0018". |
| **Contact e-mail** | The same address, ignoring capitals. |
| **Contact name** | The same first and last name. |

The same rules exist in Python (for what you type) and in SQL (for stored records). Tests check that both agree.

### Customer health (`app/modules/relationships/health.py`)
The score starts at 100. Then:

| Signal | Points |
|---|---|
| No interaction ever | −20 |
| Last interaction 30–89 days ago | −10 |
| Last interaction 90–179 days ago | −30 (also marked *inactive*) |
| Last interaction 180+ days ago | −45 |
| Each overdue invoice | −10 (at most −30) |
| Support tickets past their SLA | −15 |
| Open complaints | −10 |
| Average satisfaction below 3 | −10 |
| Average satisfaction 4.5 or higher | +5 |
| Deals won in the last year | +5 |
| Lifecycle stage "churned" | −40 |

- **"Interaction"** means the latest of: a done call, meeting, e-mail, note or task (on the account, its contacts or its deals), an order, or a ticket.
- **Labels:** healthy 75+, watch 50–74, at risk under 50.

### Lead score (`app/modules/leads/scoring.py`)

| Factor | Points |
|---|---|
| E-mail address | +15 |
| Phone number | +10 |
| Company known | +10 |
| Job title known | +5 (+15 instead for senior titles: chief, director, head, VP, owner, founder…) |
| Source | referral +20, partner +15, event or web +10, advertisement +5 |
| Status | contacted +5, qualified +20 |
| Engagement | a call, e-mail, meeting or note in the last 14 days +15; nothing for over 30 days −10 |
| Each activity | +3 (at most +12) |

- The result is capped to 0–100.
- **Disqualified leads always score 0.**
- The score is calculated in SQL (so lists can sort and filter by it) and in Python (to explain it). A test checks both give the same number.

**Weights:** the health and lead-score weights are fixed for now. Settings each organisation can tune come with the administration phase.

## Security
- **Duplicate checks** search the whole organisation, because a duplicate owned by a colleague is still a duplicate. But they only *name* records you may open. Other matches are only counted, and other organisations are never searched.
- **Transfers:** managers and admins only, checked both by the endpoint and inside the business rule. The new owner must be an active sales employee of the same organisation.
- **Customer health:** only for accounts you may see (404 otherwise). It shows counts only, such as "2 overdue invoices", never the invoice details.
- **Ratings:**
  - only the customer, only on their own resolved tickets, and only once;
  - the server records when the rating was given;
  - staff cannot rate on a customer's behalf.

## Not in this phase
| Requested | Status |
|---|---|
| Customer **documents** (proposals, agreements, attachments) | Needs file storage (MinIO). Phase C, with an architecture decision (ADR). |
| **Renewal alerts** | Need contracts, which come in the Orders, Contracts & Renewals phase. |
| **Teams** in ownership | Phase C. |
| Communication Center (e-mail composer, templates, conversations) | Needs the outbox/worker and an e-mail setup (Phase C, then the communication phase). |

## Tests
- **Backend:**
  - `tests/test_relationship_rules.py`: 17 tests of the matching and health rules, without a database.
  - `tests/db/test_relationships_api.py`: 24 tests on real PostgreSQL. They cover segmentation, the value filter, duplicates (incl. hidden matches and other tenants), transfers (what moves and what stays, and the role, tenant, version and owner rules), health, lead scores (SQL = Python), ratings and complaints.

  14 deliberate bugs (mutation checks) were each caught by a failing test.
- **Unit:** the frontend form rules for the new fields, ticket categories and ratings.
- **E2E:** `frontend/e2e/relationships.spec.ts` runs five journeys:
  - the duplicate warning;
  - a manager transfer;
  - customer health;
  - lead scoring;
  - complaint → resolve → rating.
