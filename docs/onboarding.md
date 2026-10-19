# User onboarding and administration (ADR 0004)

How people get into crm-lead. The core rule: **a login on its own grants nothing.** Every
person needs a CRM user in exactly one organisation, and only an administrator can create
that link. Passwords are only ever entered on Keycloak's pages; the CRM never sees them.

## Three ways in

| Way | Who starts it | What happens |
|---|---|---|
| **Admin adds a staff member** | Tenant Admin, on **Users** | Keycloak login + CRM user (organisation = the admin's own) + "set your password" e-mail |
| **Portal invitation** | Tenant Admin (any account) or the Sales Agent who owns the account, on the account page ("Portal access") | Customer login + access to **that one account**. An existing portal user just gets one more account |
| **Sign up, then approval** | The person, via "Create an account" on the login page | Keycloak account with verified e-mail → `/pending` page → enters the organisation's **sign-up code** → a Tenant Admin approves (staff role, or customer + accounts) or rejects |

A **Super Admin** creates new organisations with their first Tenant Admin (**Organisations**).
They still see no business data of any organisation.

## The sign-up code

- Each organisation has a random code like `U67J-H38G-UTDF`. Tenant Admins see it on **Users**
  and can replace it ("Create new code"); the old code stops working.
- It is random, not the organisation's name, so organisations can't be guessed or listed.
- A wrong code gets a neutral message. After **5 wrong codes in an hour** the person must wait.
- The e-mail must be **verified** first.
- Name and e-mail of a request come from the verified login, never from what the person types.
- While waiting, the person sees **no CRM data**: every API call answers `403 access_pending`.

## Rules for administrators

- Roles that can be given out: Tenant Admin, Sales Manager, Sales Agent, Support Agent,
  and Customer (portal). **Super Admin can never be given out from the CRM.**
- You can't change your own role or deactivate yourself.
- The last active Tenant Admin can't be removed. Both rules prevent a lock-out.
- **Role changes** apply at the person's next token refresh (within about 5 minutes).
- **Deactivating** blocks sign-in and ends all sessions at once. The person sees an
  "Account deactivated" page, and their records stay. Reactivating lets them sign in again.
- "Resend invitation" sends a new set-your-password link, valid for 72 hours.
- Every change is written to the audit log: `user.invited`, `user.role_changed`,
  `user.deactivated`, `user.reactivated`, `user.invite_resent`, `portal.user_invited`,
  `portal.access_granted`, `portal.access_revoked`, `access_request.approved` / `rejected`,
  `tenant.signup_code_regenerated`, `tenant.created`.

## How it works inside

- **Keycloak** keeps its data in its own PostgreSQL database `keycloak`, so created users
  survive restarts.
- **Mailpit** (http://localhost:8025) catches every e-mail Keycloak sends.
- The backend talks to Keycloak's admin API through the service client **`crm-user-admin`**
  (`backend/app/core/auth/identity_admin.py`). It can only manage users of realm `crm`. Its
  secret is `CRM_KEYCLOAK_ADMIN_CLIENT_SECRET` in `backend/.env`; without it, these actions
  answer 503 and the rest of the CRM keeps working.
- Keycloak and PostgreSQL can't share one transaction. If anything fails after a login was
  created in Keycloak (for example the e-mail can't be sent), that login is **deleted again**,
  so no orphan logins remain. This is tested.
- The organisation of a new user always comes from the admin's own session (or, for sign-ups,
  from the code). It is never part of a request: such fields are rejected with 422.

## API

| Endpoint | Who |
|---|---|
| `GET /tenant/users`, `POST /tenant/users`, `PUT /tenant/users/{id}/role`, `POST /tenant/users/{id}/deactivate` · `/reactivate` · `/resend-invite` | Tenant Admin |
| `GET /tenant/signup-code`, `POST /tenant/signup-code/regenerate` | Tenant Admin |
| `GET /tenant/access-requests`, `POST /tenant/access-requests/{id}/approve` · `/reject` | Tenant Admin |
| `GET /accounts/{id}/portal-users` | staff who can see the account |
| `POST /accounts/{id}/portal-users`, `DELETE /accounts/{id}/portal-users/{user_id}` | Tenant Admin (any account), Sales Agent (own accounts) |
| `GET /onboarding/status`, `POST /onboarding/requests` | anyone signed in, also without CRM access |
| `POST /platform/tenants` | Super Admin |

Error codes: `email_in_use`, `cannot_change_yourself`, `last_tenant_admin`,
`invalid_signup_code`, `too_many_attempts`, `email_not_verified`, `invalid_approval`,
`access_pending`, `account_disabled`, `identity_admin_unavailable`.

## Screens

| Route | What |
|---|---|
| `/login` | "Create an account" link (opens Keycloak's sign-up form) |
| `/pending` | Enter the sign-up code, see the request status, "Continue" after approval (it gets fresh tokens with the new role), or the deactivated notice |
| `/users` | Waiting for approval (Approve: role, or customer + accounts / Reject), sign-up code, staff list, customer portal users, with Change role / Resend invitation / Deactivate / Reactivate |
| `/accounts/[id]` | **Portal access** card: who sees this account in the portal, Invite, Remove |
| `/platform` | Super Admin: organisations, "New organisation" |

## Database (migration `0008`)

- `tenants.signup_code` is filled by the database function `crm_new_signup_code()`, which uses
  strong randomness.
- `access_requests`: one pending request per login at a time.
- `signup_code_attempts`: wrong codes, for the limit.

## Tests

- `backend/tests/db/test_onboarding_api.py` (45 tests, with an in-memory fake of Keycloak's
  admin API) and `backend/tests/test_identity_admin_keycloak.py` (the real Keycloak + Mailpit).
- Mutation checks: six rules were broken on purpose and each was caught.
- End to end (`frontend/e2e/onboarding.spec.ts`): an admin invites a staff member, who sets
  a password from the Mailpit e-mail and signs in, then is deactivated. Someone signs up,
  verifies the e-mail, uses a wrong and then the right code, and is approved as a customer of
  exactly one account. A sales agent invites a contact for their own account.

## Known limits

- The ID token is not re-issued on approval: the "Continue" button refreshes the session.
  Otherwise the new role appears within 5 minutes.
- No bulk invitations, teams or custom roles yet. Production needs real SMTP and HTTPS.
- E2E runs leave fictional test logins in the local Keycloak. They are harmless, and a reset of
  the `keycloak` database removes them (ask first: it is destructive).
