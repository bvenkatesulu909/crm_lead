# ADR 0004 — User onboarding: admin-created users, portal invitations, sign-up with approval

- **Status:** Accepted (implemented 2026-10-18, see docs/onboarding.md)
- **Date:** 2026-10-18
- **Deciders:** Project owner

## Context

Until now every login was a fixed test identity loaded from `infrastructure/keycloak/realm-crm.json`,
with a matching CRM user created by the seed script. There was no way to add a person. The
owner asked for **both**:

1. administrators create users (staff and portal customers), and
2. people can sign up on the login page, but get access only after an administrator approves.

Constraints that shape the design:

- A Keycloak login alone grants **nothing**: the CRM finds the person's organisation (tenant) and
  role from its own `users` row (ADR 0002). Whoever creates that row decides what the person can
  see, so it must never be the person themselves.
- Keycloak runs with `start-dev` and keeps its data **inside the container**. The realm is
  re-imported from the JSON file, so users created at runtime would be lost when the container
  is recreated.
- Roles are Keycloak realm roles. They travel in the access token, and the CRM keeps a copy in
  `users.roles`.
- No secrets in code; everything runs locally; e-mails must not reach real inboxes.

## Decisions

1. **Keycloak keeps its data in PostgreSQL.** It gets its own database `keycloak` and its own
   role, in the existing PostgreSQL container. The password is in `infrastructure/.env`, and
   the role has no rights on the CRM databases. The realm JSON is still imported on first start
   only. Users created through the CRM then survive container restarts. One-time migration:
   create the role and database with a documented command (init scripts run only on an empty
   volume); the CRM data is not touched.
2. **Mailpit catches all e-mail.** It is a new container (SMTP on 1025, web inbox on
   http://localhost:8025, both bound to 127.0.0.1). Keycloak sends its e-mails there:
   set-your-password, verify-e-mail and reset-password. Nothing leaves the machine.
3. **The CRM manages Keycloak users through a dedicated service client.** This is a new
   confidential client, `crm-user-admin`. Its service account gets only `manage-users`,
   `view-users` and `query-users` in realm `crm`: no realm settings, no other realms. Its
   secret lives in `infrastructure/.env` and `backend/.env` (placeholders in the examples).
   Only the backend uses it; the browser never does.
4. **Admin-created staff users.** A Tenant Admin gets a **Users** screen. From there they can:
   - add a person with name, e-mail and role;
   - change a person's role;
   - deactivate or reactivate a person.

   Rules:
   - The organisation is always the admin's own; it is never taken from the request.
   - Allowed roles: Tenant Admin, Sales Manager, Sales Agent, Support Agent. Super Admin can
     never be given out from the CRM.
   - An admin cannot change their own role or deactivate themselves, and the last active Tenant
     Admin cannot lose that role. This prevents a lock-out.
   - The invited person receives a **set-your-password e-mail**. The link is valid for 72 hours;
     the CRM never sees or stores the password.
   - Role changes are written to Keycloak first. They take effect at the person's next token
     refresh (at most about 5 minutes). The CRM copy is updated immediately. Everything is audited.
   - Keycloak and the database cannot share one transaction. So the Keycloak user is created
     first; if saving the CRM user then fails, the Keycloak user is deleted again (a
     "compensating action").
5. **Portal invitations for customers.** From an account page, a Tenant Admin (or the Sales
   Agent who owns the account) can invite a customer contact by e-mail. This creates a portal
   user with a portal access grant **for that one account**. Further accounts can be granted
   and grants removed. The customer receives the same set-your-password e-mail.
6. **Self sign-up waits for approval.** The login page gets a **Register** link, with Keycloak
   registration turned on and e-mail verification required. After signing in, a person without
   a CRM user sees a "waiting for approval" page and has **no access to any data**: every API
   call except the request itself answers 403 `access_pending`.
   - To be routed to the right company, they enter their **organisation sign-up code**. Each
     tenant has a random code that its admins can see and regenerate. It is not the
     organisation's name, so codes can't be guessed or listed.
   - A wrong code gets a neutral message. Attempts are limited (5 per hour per identity).
   - The request (verified e-mail and name from the token; nothing typed in is trusted) appears
     in that tenant's Users screen. The admin approves it by choosing a staff role, or
     "customer" plus account(s), which creates the CRM user and grants. Or the admin rejects it.
     Everything is audited.
7. **Super Admin** stays platform-only. It can create organisations and their first Tenant
   Admin, but sees no tenant business data (unchanged).

## Consequences

- New: migration 0008 with `access_requests` and a per-tenant sign-up code; an identity admin
  service in the backend; Users and access-request screens; portal invite; a "pending" page.
- Infrastructure changes: two containers/services are added (Keycloak database role and
  Mailpit), plus a new client secret. `docker compose up -d` recreates the Keycloak container
  once. The realm file stays the source of the **test** users.
- Risk: the `crm-user-admin` secret can create users in realm `crm`. It is kept only in local
  `.env` files and limited to user management. Tests check that a Tenant Admin can never
  create or change users of another tenant, nor give out Super Admin.
- Sign-up spam is possible, but harmless: pending people see nothing and requests can be rejected.

## Alternatives considered

- **Self sign-up straight into a company:** rejected, because a stranger would see customer data.
- **The CRM storing passwords itself:** rejected; this was already ruled out in the auth phase.
- **Roles stored only in the CRM database:** possible later, but it would change how tokens and
  permissions work everywhere. For now Keycloak stays the source of roles.
