# ADR 0003 — AI assistant: provider, knowledge search and build order

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** Project owner

## Context

The project owner asked for a customer-facing AI assistant in the customer portal: chat,
RAG over FAQs / product information / support policies, tools for account, order, invoice and
ticket status, voice, audit, and handoff to human support — with strict security (verified
identity, tenant and record-level checks on every tool call, prompt-injection protection, no
API keys in the frontend, approval for sensitive actions).

At decision time the customer portal UI, support tickets, orders and invoices did not exist.

## Decisions

1. **Build order — prerequisites first.** Customer portal UI → support tickets (also provides
   human handoff) → orders → invoices → AI assistant (text chat first, then voice). Each is its
   own phase with owner approval. The assistant's tools only ever wrap real, permission-checked
   APIs; no tool is built against data that doesn't exist yet.
2. **LLM provider — Anthropic Claude API.** Strong tool use and prompt-injection resistance.
   The API key lives only in the backend's environment; the browser talks to our API, never to
   Anthropic. Customer questions and the tool results the assistant sees are sent to Anthropic.
3. **Knowledge search — local embeddings + pgvector.** An open-source embedding model runs
   locally; vectors are stored in the existing PostgreSQL via the `pgvector` extension.
   Knowledge-base text never leaves the machine for indexing.

## Security design (to be implemented in the assistant phase)

- The assistant runs in the **backend**, as the signed-in customer: every tool calls the same
  service/API functions as the portal, so tenant, portal-grant and record-level checks apply
  unchanged. The model never receives database access or unrestricted queries.
- Tool arguments from the model are untrusted input (validated like any request). Records and
  documents the model reads are data, not instructions (prompt-injection defence); tool results
  are size-limited.
- Sensitive actions require explicit confirmation by the customer in the UI.
- Every conversation turn and tool call is audited (who, which tool, allowed/denied).
- Evaluation tests cover permitted and forbidden customer scenarios (e.g. asking for another
  customer's invoice must be refused).

## Consequences

- The assistant arrives after four other phases, but on solid ground.
- Using a cloud LLM means customer conversation content is processed by Anthropic; this must be
  reflected in the privacy notice before real customers use it.
- PostgreSQL needs the `pgvector` extension (an image change in `infrastructure/`, done in the
  assistant phase).
