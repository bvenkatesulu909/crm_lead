# ADR 0002 — Determine the tenant from the CRM user mapping, not from a token claim

- **Status:** Accepted (changes architecture.md §5)
- **Date:** 2026-10-18
- **Deciders:** Project owner

## Context

The first architecture draft planned a `tenant_id` claim in every Keycloak access token,
filled from a user attribute or group. Requirements: never trust a tenant or user ID from an
unverified client request, and never let one tenant reach another tenant's records.

Problems with a token claim:

- In Keycloak, user attributes can become user-editable through the account console unless the
  user profile is configured carefully; a mistake there would let a user move themselves into
  another tenant.
- Moving a user between tenants, disabling a user or suspending a tenant would only take
  effect when old tokens expire.

## Decision

- Tokens carry identity (`iss`, `sub`) and roles only.
- The API looks up the CRM `users` row by `(idp_issuer, idp_subject)`. A unique constraint makes
  each Keycloak identity belong to **exactly one** CRM user in **one** tenant.
- `tenant_id`, `user_id` and `user_type` come from that row; `is_active` and the tenant's
  `status` are checked on every request.
- Super admins (platform operators) have no CRM user row and no tenant.

## Consequences

**Good**: the tenant can't be influenced by anything the user controls; disabling users or
suspending tenants takes effect immediately; Keycloak needs no custom attributes or mappers.

**Costs**: one indexed database lookup per request (cacheable later). One person who works for two
tenants needs two Keycloak identities. When PostgreSQL Row-Level Security is added (Phase 5), this
lookup happens before the tenant is known and needs a narrow, audited exception.

## Revisit when

A user must switch between several tenants with one login. That would add an explicit,
server-validated tenant selection, still never a raw client-supplied tenant ID.
