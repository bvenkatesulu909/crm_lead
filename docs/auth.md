# Authentication & authorization

How a request proves **who** it comes from, and how the API decides **what** that person may see.
Status: the foundation is implemented and used by every shipped staff and portal module
(identity, accounts, contacts, leads, sales, activities, catalogue, orders, billing, support,
portal, documents, reports, workflows, assistant). Row-Level Security is enforced on every tenant table (ADR 0009, `docs/rls-audit.md`); Teams are still open.

## 1. The big picture

```
 Browser ──(1) login──► Keycloak login page  (password checked by Keycloak, never by the CRM)
    │                        │
    │◄──(2) one-time code────┘   redirect to http://localhost:3000/api/auth/callback/keycloak
    ▼
 Next.js server ──(3) code + PKCE verifier + client secret──► Keycloak ──► access token (JWT)
    │
    └──(4) Authorization: Bearer <access token> ──► FastAPI
                                                      │ (5) verify token: signature, iss, aud, exp, typ
                                                      │ (6) look up CRM user by (iss, sub) → tenant, user type
                                                      │ (7) roles from token ∩ roles allowed for that user type
                                                      │ (8) permissions = fixed role→permission table
                                                      │ (9) record-level SQL filter (tenant + own/all/granted)
                                                      ▼
                                                  PostgreSQL
```

**Authorization Code flow with PKCE** (steps 1–3): the browser only ever carries a one-time
code. PKCE adds a random secret (*code verifier*) that the Next.js server created before the
login; Keycloak only hands out tokens to whoever can present it, so a stolen code is useless.
The `crm-web` client is also *confidential* (has a client secret), so only our server can
exchange codes. Tokens stay on the server (Backend-for-Frontend); browser JavaScript never sees them.

The frontend itself is built in Phase 3. The Keycloak side is configured now and tested with a
real login (see §7).

## 2. Keycloak configuration (`infrastructure/keycloak/realm-crm.json`)

| Setting | Value | Why |
|---|---|---|
| Realm | `crm` | All CRM users, roles and clients. |
| Issuer | `http://localhost:8080/realms/crm` | Fixed via `KC_HOSTNAME`; the API accepts tokens only from this issuer. |
| Client `crm-web` | confidential, **Standard flow only** | Implicit, password (direct access), device and CIBA grants are **disabled**. |
| PKCE | `S256` **required** | Requests without PKCE, or with the weak `plain` method, are refused. |
| Redirect URI | exactly `http://localhost:3000/api/auth/callback/keycloak` | No wildcards: codes can't be sent elsewhere. |
| Audience mapper | adds `crm-api` to `aud` | The API rejects tokens not meant for it. |
| `fullScopeAllowed` | `false` + scope mapping of the 6 CRM roles | Tokens carry only CRM roles, nothing else. |
| Client `crm-api` | bearer-only, all flows off | Exists only as the token audience; cannot log in. |
| Access-token lifetime | 5 minutes | Short-lived; refreshed by the Next.js server. |
| Brute-force protection | on (temporary lockout after 10 failures) | Slows password guessing. |
| Password policy | ≥ 12 characters, not the username | |
| Registration | **on**, e-mail verification required (ADR 0004) | Anyone may create a *login*, but gets no CRM access until a Tenant Admin approves (see [onboarding.md](onboarding.md)). |
| Client `crm-user-admin` | confidential, service account only, all login flows off | The backend uses it to create/manage users of realm `crm`. Its service account has only `manage-users`, `view-users`, `query-users` (verified: 403 for realm settings and other realms). |
| SMTP | `mailpit:1025` | All e-mails (invitations, verification, reset) go to Mailpit: http://localhost:8025 |
| Admin-sent links | valid 72 hours | Set-your-password links in invitations. |

Secrets are **not** in this file: it contains `${CRM_WEB_CLIENT_SECRET}`,
`${CRM_USER_ADMIN_CLIENT_SECRET}` and `${CRM_DEV_USER_PASSWORD}` placeholders that Keycloak fills from environment variables
(`infrastructure/.env`, git-ignored). The Keycloak admin login also comes only from that file.

**Keycloak database (ADR 0004).** Keycloak keeps its data in its own PostgreSQL database
`keycloak` (role `KEYCLOAK_DB_USER`, no access to the CRM databases), so users created through
the CRM survive restarts. The realm file is imported only on the **first** start. On a data
volume created before ADR 0004, create the database once (safe to repeat):

```bat
cd E:\crm-lead\infrastructure
docker compose up -d postgres mailpit
docker compose exec -T postgres sh /docker-entrypoint-initdb.d/02-create-keycloak-database.sh
docker compose up -d keycloak
```

**Changing the realm file later:** because the realm already exists, edits to
`realm-crm.json` are not applied automatically. For local development the simplest way is to
recreate the `keycloak` database (this deletes all Keycloak logins, including invited and
signed-up people; the test users are re-imported) - ask first, it is destructive.

## 3. Token validation in the API (`backend/app/core/auth/tokens.py`)

A token is accepted only if **all** of these hold, otherwise the API answers `401` with the same
generic message (the reason is logged on the server, the token never is):

| Check | Blocks |
|---|---|
| Algorithm is exactly `RS256` | `alg=none`, HMAC "algorithm confusion" attacks |
| Signature matches a key from Keycloak's JWKS | forged or modified tokens |
| `iss` equals `CRM_OIDC_ISSUER` | tokens from any other identity provider / realm |
| `aud` contains `CRM_OIDC_AUDIENCE` (`crm-api`) | tokens issued for other applications |
| `exp` in the future, `nbf`/`iat` not in the future (±30 s) | expired / replayed / pre-dated tokens |
| `sub` present, `typ` = `Bearer` | ID tokens used as access tokens |

Keycloak's public keys are fetched from the JWKS URL and cached; an unknown key ID triggers a
refetch (key rotation). If Keycloak can't be reached, the API answers `503`, not `200`.

## 4. From token to Principal (`backend/app/modules/identity/service.py`)

The **Principal** is the server's view of the caller. It is built **only** from the verified
token and the database — never from request bodies, query strings or headers like `X-Tenant-ID`.

1. Find the CRM user by `(issuer, subject)`. Each Keycloak identity maps to **exactly one**
   CRM user in **one** tenant (unique constraint), so the token fully determines the tenant.
2. No CRM user → only allowed for `super_admin` (platform operator, no tenant). Anyone else:
   `403` with code `access_pending` (they signed up and wait for approval - see onboarding.md).
   A role in the token alone grants nothing.
3. Disabled user → `403` `account_disabled`; suspended tenant → `403`.
4. The last sign-in time is recorded (at most every 15 minutes).
5. Roles = roles in the token **∩** roles allowed for the user type:
   staff users get only staff roles, customers only `customer`, and tenant members never get
   `super_admin`. Unknown role names are ignored.
6. Permissions = the fixed role → permission table below.

**Row-Level Security (ADR 0009).** Every table with `tenant_id` is protected by PostgreSQL RLS,
so the database itself refuses other tenants' rows. Step 1 above cannot read `users` directly
(no tenant is known yet): it calls the narrow function `identity_lookup_user(issuer, subject)`,
which returns only id, tenant and active flag. Then `bind_tenant()` sets `app.tenant_id` for the
transaction (and `bind_user()` the lead scope), and only after that is the full user row
loaded. Without a binding a query sees **no rows** - it fails closed. The full list of the
narrow exceptions (login, sign-up, worker claim, metrics counts) is in `docs/rls-audit.md`.

## 5. Roles and permissions (`backend/app/core/auth/rbac.py`)

| Permission | Super Admin | Tenant Admin | Sales Manager | Sales Agent | Support Agent | Customer |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| `platform:tenant:read` / `platform:tenant:manage` | ✔ |  |  |  |  |  |
| `tenant:user:read` / `tenant:user:manage` |  | ✔ |  |  |  |  |
| `portal:user:invite` (admins: any account; agents: accounts they own) |  | ✔ |  | ✔ |  |  |
| `account:read:all` |  | ✔ | ✔ |  | ✔ |  |
| `account:read:own` |  |  |  | ✔ |  |  |
| `account:write:all` |  | ✔ | ✔ |  |  |  |
| `account:write:own` |  |  |  | ✔ |  |  |
| `contact:read:all` |  | ✔ | ✔ |  | ✔ |  |
| `contact:read:own` / `contact:write:own` |  |  |  | ✔ |  |  |
| `contact:write:all` |  | ✔ | ✔ |  |  |  |
| `lead:read:all` / `lead:write:all` |  | ✔ | ✔ |  |  |  |
| `lead:read:own` / `lead:write:own` |  |  |  | ✔ |  |  |
| `lead:assign` |  | ✔ | ✔ |  |  |  |
| `lead:convert` (within write scope) |  | ✔ | ✔ | ✔ |  |  |
| `opportunity:read:all` / `opportunity:write:all` |  | ✔ | ✔ |  |  |  |
| `opportunity:read:own` / `opportunity:write:own` |  |  |  | ✔ |  |  |
| `activity:read:all` / `activity:write:all` / `activity:assign` |  | ✔ | ✔ |  |  |  |
| `activity:read:own` / `activity:write:own` |  |  |  | ✔ | ✔ |  |
| `catalog:read` |  | ✔ | ✔ | ✔ | ✔ |  |
| `catalog:manage` |  | ✔ | ✔ |  |  |  |
| `quote:read:all` / `quote:write:all` / `quote:approve` |  | ✔ | ✔ |  |  |  |
| `quote:read:own` / `quote:write:own` |  |  |  | ✔ |  |  |
| `quote:settings:manage` (the approval limit per organisation) |  | ✔ |  |  |  |  |
| `document:read` |  | ✔ | ✔ | ✔ | ✔ |  |
| `document:write` |  | ✔ | ✔ | ✔ |  |  |
| `document:delete` |  | ✔ | ✔ |  |  |  |
| `ticket:read:all` |  | ✔ | ✔ |  | ✔ |  |
| `ticket:read:own_accounts` (tickets on accounts they own) |  |  |  | ✔ |  |  |
| `ticket:manage` |  | ✔ |  |  | ✔ |  |
| `order:read:all` |  | ✔ | ✔ |  | ✔ |  |
| `order:read:own_accounts` / `order:write:own_accounts` |  |  |  | ✔ |  |  |
| `order:write:all` |  | ✔ | ✔ |  |  |  |
| `order:fulfil` (in fulfilment / shipped / delivered) |  | ✔ | ✔ |  |  |  |
| `invoice:read:all` |  | ✔ | ✔ |  | ✔ |  |
| `invoice:read:own_accounts` |  |  |  | ✔ |  |  |
| `invoice:manage` (create from order, issue, discard, credit notes) |  | ✔ | ✔ |  |  |  |
| `payment:record` (record and reverse payments) |  | ✔ | ✔ |  |  |  |
| `notification:read` |  | ✔ | ✔ | ✔ | ✔ |  |
| `workflow:manage` (automation rules) |  | ✔ |  |  |  |  |
| `knowledge:read` (knowledge base; RAG R1) |  | ✔ | ✔ | ✔ | ✔ |  |
| `knowledge:manage` (upload/delete knowledge documents) |  | ✔ |  |  |  |  |
| `dashboard:sales:all` |  | ✔ | ✔ |  |  |  |
| `dashboard:sales:own` |  |  |  | ✔ |  |  |
| `dashboard:executive` |  | ✔ |  |  |  |  |
| `portal:account:read` (granted accounts only) |  |  |  |  |  | ✔ |
| `portal:ticket:read` / `portal:ticket:write` (granted accounts only) |  |  |  |  |  | ✔ |
| `portal:order:read` (confirmed orders of granted accounts only) |  |  |  |  |  | ✔ |
| `portal:invoice:read` (issued invoices of granted accounts only) |  |  |  |  |  | ✔ |
| `portal:quote:read` / `portal:quote:respond` (sent quotes, accept/decline) |  |  |  |  |  | ✔ |
| `portal:document:read` (public documents of granted accounts) |  |  |  |  |  | ✔ |
| `portal:assistant:use` (AI assistant on own data) |  |  |  |  |  | ✔ |
| `portal:knowledge:read` (portal knowledge answers: public + granted-account chunks) |  |  |  |  |  | ✔ |

- **Super Admin** runs the platform (tenants). By design it sees **no tenant business data**.
- `own` = records whose `owner_id` is the caller; `all` = all records **of the caller's tenant**.
  No permission ever crosses tenants.
- The table lives in code (reviewed, versioned, tested), not in the database, so a database
  write can never grant extra rights. `ROLE_PERMISSIONS` in `backend/app/core/auth/rbac.py` is
  the source of truth - keep this table in sync when a permission changes. Every shipped module
  enforces its permission on every endpoint.

**Colleague directory** — `GET /api/v1/users` (`?assignable=true`): staff of the caller's own
tenant, names and IDs only (no e-mails), used for owner names and assignment. Customers and
platform users get 403.

## 6. Tenant-level and record-level rules

Every query adds a SQL condition from the module's `policies.py`
(`backend/app/modules/accounts/policies.py`):

- **Always:** `tenant_id = principal.tenant_id` and not soft-deleted.
- `account:read:all` → nothing more. `account:read:own` → `owner_id = principal.user_id`.
- **Customers:** `id IN (accounts granted in portal_access_grants)`.
- Platform users (no tenant) → nothing.

Because filtering happens in SQL, unauthorized rows are never loaded. Asking for an account you
may not see returns **404 — exactly like a non-existent ID** — so attackers can't probe IDs.

**Customer ↔ account links** live in `portal_access_grants`. The database guarantees, with
composite foreign keys, that the user is a *customer* of the *same tenant* as the account
(staff can't get grants; cross-tenant grants are impossible; a customer with grants can't be
switched to staff without removing them first).

Staff endpoints (`/api/v1/accounts`) refuse customers; portal endpoints (`/api/v1/portal/...`)
refuse staff; portal responses contain only customer-safe fields.

## 7. Local test identities

All share **one** password: `CRM_DEV_USER_PASSWORD` in `infrastructure\.env` (generated, git-ignored).
All names and addresses are invented. IDs are fixed so `scripts/seed_dev_data.py` can link them.

| Username | Role | Tenant | Sees |
|---|---|---|---|
| `superadmin` | super_admin | — | tenant list only |
| `alpha.admin` | tenant_admin | Alpha Demo | all Alpha accounts |
| `alpha.manager` | sales_manager | Alpha Demo | all Alpha accounts |
| `alpha.agent1` | sales_agent | Alpha Demo | own account: Example Customer One |
| `alpha.agent2` | sales_agent | Alpha Demo | own account: Example Customer Two |
| `alpha.support` | support_agent | Alpha Demo | all Alpha accounts (read only) |
| `alpha.customer1` | customer | Alpha Demo | portal: Example Customer One |
| `alpha.customer2` | customer | Alpha Demo | portal: Example Customer Two |
| `beta.admin` | tenant_admin | Beta Demo | all Beta accounts |
| `beta.customer` | customer | Beta Demo | portal: Example Customer Three |

The Keycloak admin console (`http://localhost:8080/admin`) uses `KEYCLOAK_ADMIN_USER` /
`KEYCLOAK_ADMIN_PASSWORD` from the same `.env` file.

## 8. Development setup (Windows CMD)

```bat
cd E:\crm-lead\infrastructure
docker compose up -d
docker compose ps
```

Wait until both services show `(healthy)` (Keycloak takes about a minute). Then:

```bat
cd E:\crm-lead\backend
.venv\Scripts\activate
alembic upgrade head
python -m scripts.seed_dev_data
uvicorn app.main:create_app --factory --reload
```

`backend\.env` needs `CRM_OIDC_ISSUER=http://localhost:8080/realms/crm` (see `.env.example`).
For the Keycloak integration tests it also needs `CRM_TEST_KEYCLOAK_WEB_CLIENT_SECRET` and
`CRM_TEST_KEYCLOAK_USER_PASSWORD` (the same values as in `infrastructure\.env`); without them
those tests are skipped.

## 9. Tests

| File | What it proves |
|---|---|
| `tests/test_token_verification.py` | 17 kinds of bad token rejected (forged, expired, wrong iss/aud, alg=none, HS256 confusion, tampered roles/subject, ID token…), generic 401 without echoing the token |
| `tests/db/test_authorization.py` | tenant isolation, role checks, own-vs-all, customer grants, 404-not-403, ignored client IDs/headers, role-escalation attempts, super admin sees no tenant data |
| `tests/db/test_identity_constraints.py` | database rejects cross-tenant grants, staff grants, duplicate identities |
| `tests/db/test_onboarding_api.py` | user administration, portal invitations, sign-up with approval, platform organisations (fake Keycloak admin): tenant isolation, role denial, Super Admin never assignable, last-admin and self-change guards, compensation when the e-mail fails, code attempt limit |
| `tests/test_identity_admin_keycloak.py` | the real admin client against Keycloak + Mailpit: roles replaced (not added), invitation e-mail arrives, e-mail conflicts, disable/enable |
| `tests/db/test_keycloak_integration.py` | real Keycloak: PKCE login works; no-PKCE, `plain` PKCE, missing/wrong verifier, wrong client secret, password grant all refused; real token → API → only own records |

## 10. Not done yet (planned)

- Teams/hierarchies for sales managers (today an `all` scope means the whole tenant).
- Production Keycloak: `start` mode with HTTPS, real SMTP, real secrets management (prepared in
  ADR 0007: `infrastructure/keycloak/Dockerfile.production` + `realm-crm-production.json`).
