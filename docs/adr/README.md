# Architecture Decision Records (ADRs)

An ADR is a short document that records **one important decision**: the situation, the choice,
and its consequences. They explain *why* the project looks the way it does.

Rules:

- One decision per file, numbered: `NNNN-short-title.md`.
- Never rewrite an accepted ADR. If a decision changes, write a new ADR that supersedes it and
  mark the old one `Superseded by ADR NNNN`.
- Decisions marked **[ADR]** in [architecture.md](../../architecture.md) need an ADR and owner approval to change.

| # | Title | Status |
|---|---|---|
| [0001](0001-modular-monolith.md) | Start as a modular monolith | Accepted |
| [0002](0002-tenant-from-crm-user-mapping.md) | Tenant from CRM user mapping, not a token claim | Accepted |
| [0003](0003-ai-assistant-foundations.md) | AI assistant: Claude API, local embeddings + pgvector, prerequisites first | Accepted |
| [0004](0004-user-onboarding.md) | User onboarding: admin-created users, portal invitations, sign-up with approval | Accepted |
| [0005](0005-file-storage-outbox-worker.md) | S3 file storage (SeaweedFS), outbox + worker, e-mailed quote PDFs | Accepted |
| [0006](0006-domain-events-notifications-workflows.md) | Domain events, notifications and workflow rules | Accepted |
| [0007](0007-online-deployment.md) | Online deployment (Netlify for the web app, hosting for the rest) | Accepted |
| [0008](0008-teams-visibility.md) | Teams and team-scoped visibility | Proposed |
| [0009](0009-row-level-security.md) | PostgreSQL Row-Level Security as defence in depth | Accepted (staged) |
| [0010](0010-knowledge-search-pgvector-embeddings.md) | Knowledge search: pgvector image, embedding model and index | Accepted |
| [0011](0011-chunking-and-hybrid-search.md) | Chunking and hybrid search: starting settings | Accepted |
| [0012](0012-communication-center.md) | Communication Center: one-to-one e-mail, templates, conversation history | Accepted |
| [0013](0013-public-chat-save-lead.md) | Public website chat that saves real-estate leads (BP-01) | Accepted |
| [0014](0014-agent-action-approvals.md) | Approval queue for AI-proposed actions (BP-05) | Proposed |
