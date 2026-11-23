# Projects and units (ADR 0040, step RP1)

This is the first building block of the UPI reserve-pay feature. A **project** is a development you sell
from (for example "Green Valley"). A **unit** is one thing a buyer can reserve: a flat, a villa, a plot or
a shop. The reservation rules come in later steps (RP2 onwards); this step only lets staff keep the list of
what can be reserved.

## What you can do

| Who | What |
|---|---|
| Tenant administrators and sales managers | add and change projects and units, block or release a unit |
| Sales agents | read projects and units |
| Support agents, customers, other organisations | nothing (403 / not found) |

API (all under `/api/v1`, see `docs/api/openapi.json`):

- `GET/POST /projects`, `GET/PATCH /projects/{id}` - name (unique per organisation, capitals ignored),
  location, RERA number (kept as typed, **never checked** against any registry), `is_active`.
- `GET/POST /units`, `GET/PATCH /units/{id}` - project, unit code (unique inside the project, capitals
  ignored), type (`apartment`, `villa`, `plot`, `commercial`), price in rupees, area in square feet.
  Filters on the list: `project_id`, `status`, `unit_type`, `q` (part of the code).

## Rules the code and the database enforce

- **Money is `Decimal`** (`NUMERIC(18,2)`), never a float; the API shows it as text with its paise. The
  currency is INR. A price above 10,000,000,000 or with more than two decimals is refused.
- **Status.** A unit is `available` or `blocked` (set by staff) - or `reserved` / `sold`. The last two can
  **only** be set by the reservation steps (not built yet); no request can send them, and a reserved or
  sold unit cannot be edited or released by hand, not even its price (409 `unit_status_locked`). This is
  what will make "one buyer per unit" real in RP4.
- **Nothing is deleted.** A project is deactivated (an inactive project takes no new units, 409
  `project_inactive`); a unit is blocked.
- **Tenant isolation.** Both tables have `tenant_id`, forced row-level security and a tenant policy; a unit
  must belong to a project of the same organisation (composite foreign key). The organisation comes only
  from the signed-in user; a project or unit id from another organisation answers 404.
- **Changes are audited** (`project.created/updated`, `unit.created/updated`) with old and new values
  (prices as exact text). A change needs the `version` the screen last read (409 `version_conflict`).

## What is not here yet

Reservations, the token amount rules, the payment link, expiry and refunds (RP2-RP9), and any screen
(the units screens are part of RP8, or earlier if the owner asks). Other modules read a unit only through
`app/modules/units/api.py` (`unit_info`).

Tests: `backend/tests/db/test_units_api.py` (who may, validation, server-controlled fields, status lock,
tenant isolation, ID tampering, audit, database checks).
