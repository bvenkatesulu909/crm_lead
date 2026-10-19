# ADR 0001 — Start as a modular monolith

- **Status:** Accepted
- **Date:** 2026-10-17
- **Deciders:** Project owner

## Context

crm-lead needs 17 business modules (accounts, leads, sales, billing, support, portal, …). It is
built by a small team (one developer who is learning, plus Claude Code), runs locally on one
Windows machine with Docker Desktop, and must be production-oriented: secure, tested, and
easy to change later.

Options considered:

1. **Classic monolith** — one codebase with no internal boundaries.
2. **Microservices** — a separate service (and often database) per module.
3. **Modular monolith** — one deployable application, split internally into modules with
   enforced boundaries.

## Decision

We build a **modular monolith**:

- One FastAPI backend (`apps/api`) and one PostgreSQL database.
- Each business module lives in `app/modules/<name>/` and owns its tables.
- A module may import only `app.core` and other modules' public `api.py`, never their internals.
  **import-linter** enforces this automatically.
- Modules react to each other through **domain events** stored in an outbox table and processed
  by a worker, instead of writing into each other's tables.

## Consequences

**Good**

- One process to run, debug and test; one database transaction can cover a whole use case
  (e.g. lead conversion creating an account, contact and opportunity).
- Much simpler local setup than microservices (no service discovery, no distributed tracing,
  no network failures between modules).
- Clear boundaries keep the code understandable and allow a module to be extracted into its
  own service later if there is a real reason.

**Costs / risks**

- Boundaries are only as strong as their enforcement; import-linter must run in the test suite.
- All modules share one deploy and one database, so a heavy module (e.g. reporting) can affect
  others. Mitigation: read-only reporting views, background jobs, and indexes.
- The shared database makes it tempting to join across module tables. This is allowed only in
  the `reporting` module, through read-only views.

## Revisit when

- A module needs independent scaling or release cycles, or
- A separate team takes ownership of a module.
