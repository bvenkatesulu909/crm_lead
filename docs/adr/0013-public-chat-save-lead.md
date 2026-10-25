# ADR 0013 — Public website chat that saves real-estate leads (BP-01)

- **Status:** Accepted (2026-10-25)
- **Date:** 2026-10-25
- **Deciders:** Project owner
- **Covers:** blueprint BP-01, tickets CRM-104 (DeepSeek tool calling), CRM-105 (real-estate lead
  fields), CRM-106a/b (public chat API and page). See `docs/master-plan.md`.

## Context

The approved product idea is a chat on the company's public website: a visitor (a home buyer)
chats, the assistant asks for name, phone, property type, budget and location, and a **lead** is
saved in the CRM for the sales team. Today:

- **Every API endpoint needs a signed-in user**, except health checks. Even sign-up needs a
  Keycloak login first. This would be the **first endpoint where someone without an account
  creates data**, so it needs its own protection.
- The API **never sees the visitor's address**: in production the browser talks to the Next.js
  server, which calls the API. There is no client-IP handling anywhere yet.
- The portal assistant (`assistant` module) has the parts we need - a small `ChatModel`
  interface, a scripted fake for tests, a tool loop, input/output guardrails - but its
  conversations belong to a **signed-in user** (`user_id` foreign key), so a visitor can't use
  those tables.
- `DeepSeekChatModel` deliberately **refuses tool calls** today; the portal uses Claude.
- Leads have no real-estate fields (property type, budget, location).
- Each tenant has an **Automation** identity (ADR 0006) with `lead:write:all`; leads it creates
  are unassigned (it has no sales role).
- `frontend/src/proxy.ts` sends every page except the login flow to the sign-in screen.

Constraints: tenant isolation with forced RLS; `tenant_id` never from the client; no secrets in
the browser; nothing goes live before ADR 0007's hardening and the owner's "go live"; it must be
fully testable **without any paid API key**.

## Decisions

1. **A new module `public_chat`** (module 20). It owns the visitor conversations and the
   website-chat rules. It creates leads only through `leads/api.py`, uses the model and the
   guardrails through `assistant/api.py`, and notifies through events.

2. **One tenant per website, chosen on the server.** Setting `CRM_PUBLIC_CHAT_TENANT_SLUG` names
   the organisation whose website this is. Empty (the default) = the feature is **off** and the
   endpoint answers 404. The request never carries a tenant.

3. **Only the Next.js server may call the endpoint.** `POST /api/v1/public/chat` requires a
   server-to-server header `X-Public-Chat-Key` equal to `CRM_PUBLIC_CHAT_SERVER_KEY` (a long
   random secret in both servers' environment, never in the browser or git); without it: 404.
   The browser calls the Next.js route `/api/public-chat`, which adds the key and the
   **visitor's address** as `X-Visitor-Ip`. The API trusts that header **only** together with
   the key. Calling the API directly from the internet therefore doesn't work.

4. **The visitor's conversation is identified by an opaque random token** created by the API on
   the first message and kept by the Next.js server in an **httpOnly cookie** (`crm_chat`, never
   readable by page JavaScript, never in `localStorage`). The API stores only a **SHA-256 hash**
   of it. A visitor can continue their own conversation and nothing else; they can **never read
   any CRM data** - the only tool saves, it doesn't look anything up.

5. **The model has exactly one tool: `save_lead`.** Arguments (validated with Pydantic before
   anything is stored): `full_name` and `phone` required; `email`, `property_type`
   (`apartment` | `villa` | `plot` | `commercial`), `budget_min_inr`, `budget_max_inr` (whole
   rupees, min ≤ max), `location`, `notes` optional. The system prompt tells the model to ask for
   missing details, convert "1.2 Cr" / "80 L" into rupees, never invent prices or projects, and
   call the tool only after the visitor confirmed the details. **One lead per conversation:** a
   second `save_lead` updates nothing and tells the visitor the details were already passed on.

6. **The lead is created as the tenant's Automation identity**, with source `web`, unassigned
   (managers assign it as usual), a timeline entry "Created from the website chat", and the
   audit trail of the leads module. The chat transcript is **linked to the lead** and shown to
   staff who may read that lead. A new event `public_chat.lead_captured` notifies sales
   managers (in-app; e-mail per their notification settings).

7. **DeepSeek becomes able to call tools** (CRM-104): `DeepSeekChatModel` translates our tool
   definitions into DeepSeek's OpenAI-compatible format, reads `tool_calls` back as `ToolUse`,
   and sends tool results as `role: "tool"` messages. The Anthropic model is unchanged.
   Provider for the public chat: `CRM_PUBLIC_CHAT_PROVIDER` = `deepseek` (default) |
   `anthropic` | `fake`. **`fake`** (a scripted model that "collects" fixed details and calls
   `save_lead`) is for tests and local demos only - **refused at start-up when
   `CRM_ENVIRONMENT=production`**. Without a key for the chosen provider the chat answers "The
   chat is not available right now" (503), never a crash.

8. **Abuse and cost limits** (all settings with safe defaults):
   - per visitor address: 20 messages per hour, 3 new conversations per hour;
   - per conversation: 30 messages, 4,000 characters per message after guardrails, at most 2
     tool rounds per answer;
   - per tenant: 500 visitor messages per day (a cost ceiling for the model bill);
   - the existing input guardrails (injection phrases, card/ID/API-key patterns) and output
     sanitising; the answer is shown as **plain text** (never HTML or Markdown, so a reply can't
     load images or links that leak data);
   - a hidden "honeypot" form field on the page: bots that fill it get a polite refusal.
   No CAPTCHA in this step (a later ADR if bots appear).

9. **Real-estate fields on leads** (CRM-105): nullable `property_type`, `budget_min_inr`,
   `budget_max_inr` (`BIGINT`, whole rupees, ≥ 0, min ≤ max), `location` (text ≤ 160), with
   database checks; in the lead schemas, the lead form and the lead page; filters by property
   type later. Budgets are integers of rupees (no fractions), so no `float` anywhere.

10. **Privacy.** The page shows a short notice before the first message ("Your messages and the
    details you share are stored to answer your enquiry" + link to the company's privacy page,
    text set by the owner). Conversations **without a lead are deleted after 30 days** by the
    worker; conversations with a lead are kept as the lead's history. Visitor addresses are
    stored only as a **hash** for the limits, never shown or logged. Transcripts are never
    logged.

11. **New public web page `/chat`** outside the CRM layout (no menu, no login), excluded from
    the sign-in redirect in `proxy.ts` together with `/api/public-chat`. It works on a phone.
    Embedding it in the company's own website (an iframe or a link) is a later step.

## Consequences

- New tables `public_chat_sessions` and `public_chat_messages` (forced RLS like every tenant
  table; the API sets the configured tenant for the request, as the worker does).
- New settings in `.env.example`: `CRM_PUBLIC_CHAT_TENANT_SLUG`, `CRM_PUBLIC_CHAT_SERVER_KEY`,
  `CRM_PUBLIC_CHAT_PROVIDER` and the limits; in the web app `PUBLIC_CHAT_SERVER_KEY`.
- `assistant/api.py` exposes the model factory and guardrails to the new module.
- The first unauthenticated write path: covered by tests for the missing/wrong server key, the
  feature switched off, every limit, guardrail refusals, the one-lead-per-conversation rule, a
  visitor continuing only their own conversation, and the lead landing in the configured tenant
  only.
- Going live (Netlify + an API host) stays a separate owner decision under ADR 0007.

## Alternatives considered

- **Let the browser call the API directly** with an IP-based limit: the API can't see a
  trustworthy address behind proxies, and the endpoint would be open to anyone.
- **Reuse the portal assistant's tables** with a fake "visitor" user: mixes anonymous data with
  customer accounts and breaks the user foreign key's meaning.
- **A lead form instead of a chat:** simpler and safer, but not the approved product; the chat
  can still fall back to "leave your number" if the model is unavailable.
- **Several tools (search properties, prices):** the visitor would then reach CRM data; BP-08
  (cited property answers) is the place for that, with its own review.

## Proposed order of work (each step stops for review)

| Step | Ticket | What |
|---|---|---|
| PC0 | — | This ADR + the phase plan (documents only) |
| PC1 | CRM-104 | DeepSeek tool calling in `DeepSeekChatModel` (fake HTTP in tests) |
| PC2 | CRM-105 | Real-estate lead fields: migration 0040, schemas, lead form and page |
| PC3 | CRM-106a | `public_chat` module: tables (migration 0041), settings, server key, sessions, `save_lead`, guardrails, limits, fake provider, `POST /api/v1/public/chat` |
| PC4 | CRM-106a | Manager notification, transcript on the lead page, 30-day clean-up in the worker |
| PC5 | CRM-106b | Web: `/chat` page and `/api/public-chat` route, proxy exception, privacy notice, Vitest |
| PC6 | — | Playwright journey (fake provider), `docs/public-chat.md`, full run, PR |
