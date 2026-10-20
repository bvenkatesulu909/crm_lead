# AI assistant — customer portal, text chat (Phase 20a, ADR 0003)

Customers ask questions in the portal ("Where is my order?", "Which invoices are still open?").
The assistant answers using **only their own data**. When a person must decide, it **prepares**
a support ticket that the customer confirms with one click.

Phase 20 is built in steps:
- **20a, this step:** text chat with permission-checked tools and a human handover.
- **20b:** knowledge base (FAQs, policies) with local embeddings + pgvector. This needs a
  PostgreSQL image with pgvector, which is a separate, approved change. Design:
  [rag-knowledge-base.md](rag-knowledge-base.md) and proposed
  [ADR 0010](adr/0010-knowledge-search-pgvector-embeddings.md).
- **20c:** voice.

## How a message is answered

```
customer types ──► Next.js server action ──► POST /api/v1/portal/assistant/messages
                                               │  (backend, as the signed-in customer)
                                               ▼
              limits (30 messages/hour, 2,000 characters, 100 messages per conversation)
                                               ▼
       Claude (Anthropic API) ◄──► tools: list_my_accounts, list_orders, get_order,
                                    list_invoices, get_invoice, list_tickets, get_ticket,
                                    propose_support_ticket
                                               ▼
                 answer stored + returned; every tool call written to an audit table
```

- The **API key lives only in `backend/.env`** (`CRM_ANTHROPIC_API_KEY`). The browser talks
  only to our own server. Without a key, the portal says "not available" and offers a ticket.
- The model gets a fixed **system prompt**, the last 20 messages of the conversation, and the
  tool list. It never gets database access.
- **Each tool calls the same functions as the portal pages, AS the customer.** Tenant
  isolation, portal grants, "no drafts" and "no internal notes" therefore apply unchanged. The
  model can only ever see what the customer could open in the portal themselves.
- At most **6 tool rounds** per answer (`CRM_ASSISTANT_MAX_TOOL_ROUNDS`). After that the
  assistant says it couldn't work it out and offers a handover.

## Security design

| Risk | Protection |
|---|---|
| Asking for another customer's or company's data | Tools run as the customer. Anything not visible is "not found" (tested with another customer of the same company and of another company, by order number, invoice number and account ID) |
| **Prompt injection**: instructions hidden in data, e.g. a reference "ignore your rules…" | The system prompt says data is never an instruction. **More importantly**, even a model that obeys can't reach other accounts. Tested with a scripted model that follows the injected instruction: refused, nothing stored |
| The model doing things | It has **no write tools**. `propose_support_ticket` only stores a *proposal*. The ticket is created when the customer clicks **Create ticket**, and the normal portal rules are checked again at that moment |
| Made-up tools or arguments (`run_sql`, SQL in a number, extra `tenant_id`) | Strict validation per tool. Unknown tools are refused and bad arguments invalid; all of it is logged |
| Endless loops, cost | Tool-round cap, per-hour message limit, length limits, `max_tokens` (1024) |
| Another customer reading your conversation or confirming your prepared ticket | Conversations and proposals are bound to the customer user. 404 otherwise, also for a colleague on the **same** account |
| Staff using the customer assistant | 403 (the permission is `portal:assistant:use`, for customers only) |
| Tracing what happened | `assistant_tool_calls` (tool, shortened arguments, outcome) and `assistant_messages` are **insert-only** for the app. The handover is also in the audit log (`assistant.handoff_confirmed`) |
| Displaying answers safely | Answers are shown as plain text: no HTML, no links rendered |

**What is sent to Anthropic:** the customer's messages, the system prompt (including the
customer's display name and organisation name) and the tool results the model asks for. Those
contain only that customer's own order, invoice and ticket data. Nothing from other customers
or companies is ever sent; a test checks every request.

## Tests

- `backend/tests/db/test_assistant_api.py` (22 tests) uses a **scripted model** that also
  misbehaves on purpose. It covers:
  - permitted questions;
  - other customers' orders and invoices, and other companies;
  - injection, invented tools and bad arguments;
  - the tool-round cap, rate limit and length limit;
  - privacy of conversations, and staff denial;
  - no key, model outage;
  - "nothing of other customers is ever sent to the model";
  - insert-only audit tables.
- Mutation checks: six rules were broken on purpose. Five were caught by tests. The sixth (who
  may confirm a proposal) is also blocked by a second, independent ownership check, so no hole
  opened.
- **Live evaluation against real Claude** (opt-in, costs a little):
  `set CRM_RUN_LIVE_EVALS=1` then `pytest tests/db/test_assistant_api.py -k live`. It covers
  your own order status, another company never revealed, an injected instruction ignored, and a
  refund handed over but not decided.
- `frontend/e2e/assistant.spec.ts`: the portal entry point and the "not available" screen,
  staff kept out, and, **with a key**, a real chat plus handover confirmation.

## Settings (`backend/.env`)

| Setting | Default | Meaning |
|---|---|---|
| `CRM_ANTHROPIC_API_KEY` | (none) | Your key from console.anthropic.com. Only ever in `.env` |
| `CRM_ANTHROPIC_WORKSPACE_ID` | (none) | Only for user-level keys (`sk-ant-usr-…`), which Anthropic accepts only together with a workspace (`wrkspc_…`, Settings → Workspaces). Not secret |
| `CRM_ASSISTANT_MODEL` | `claude-opus-5-5` | Claude model. Cheaper option: `claude-sonnet-5-5` |
| `CRM_ASSISTANT_MESSAGES_PER_HOUR` | 30 | Per customer |
| `CRM_ASSISTANT_MAX_TOOL_ROUNDS` | 6 | Tool calls per answer |

Store the key with `python -m scripts.set_anthropic_key` (in `backend`, venv active): it reads the
key without showing it and writes it to `backend\.env`. Never paste keys into chats, tickets or
screenshots - a key that was shown anywhere must be revoked and replaced.

## Screens

- `/portal/assistant`: chat with the conversation history, "New conversation", the AI notice,
  and prepared tickets with **Create ticket** / **Don't send**.
- The portal home has an **Assistant** card.

## Database (migration `0009`)

- `assistant_conversations`
- `assistant_messages` (insert-only)
- `assistant_tool_calls` (insert-only audit)
- `assistant_pending_actions`

## Not done yet

Knowledge base / RAG (20b), voice (20c), streaming answers, a staff-side assistant,
conversation retention rules, and a monthly cost limit.
