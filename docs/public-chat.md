# Public website chat (BP-01, ADR 0013)

A chat for home buyers on the company's website. The visitor needs no account. A model asks for
their name, phone number and property wishes, and when the visitor has confirmed them it saves a
**lead** in the CRM. Sales managers are notified, assign the lead as usual, and read the whole
conversation on the lead page.

Decisions and alternatives: [ADR 0013](adr/0013-public-chat-save-lead.md). Steps PC0-PC6 in
[implementation-plan.md](../implementation-plan.md).

## How a message travels

```
visitor's browser ──POST /api/public-chat──► Next.js server (route handler)
   (page /chat,         { message, website }     adds X-Public-Chat-Key (secret) and
    no sign-in)                                   X-Visitor-Ip; keeps the token in the
                                                  httpOnly cookie crm_chat
                          ──POST /api/v1/public/chat──► FastAPI (public_chat module)
                                                     key wrong/missing or feature off → 404
                                                     honeypot, guardrails, limits
                                                     model (≤ 2 tool rounds, one tool: save_lead)
                                                     save_lead → leads/api.py (Automation identity)
                                                     event public_chat.lead_captured
            ◄── { reply, lead_saved } ──  (the token never reaches the browser's JavaScript)
worker: event → notification to every sales manager; daily-ish clean-up of old conversations
```

- **The visitor can never read CRM data.** The model's only tool saves a lead; the answer holds
  just the reply text and "details saved: yes/no".
- **One lead per conversation.** A second `save_lead` changes nothing ("already passed on").
- **Plain text only.** Answers are shown as text (never HTML or Markdown), so a reply can't load
  images or links.

## Switching it on locally (fake model, no API key needed)

1. In `backend\.env` (git-ignored) - generate the key once and use the same value in step 2:

   ```
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   ```
   CRM_PUBLIC_CHAT_TENANT_SLUG=alpha-demo
   CRM_PUBLIC_CHAT_SERVER_KEY=<the generated key>
   CRM_PUBLIC_CHAT_PROVIDER=fake
   ```

2. In `frontend\.env.local` (git-ignored):

   ```
   PUBLIC_CHAT_SERVER_KEY=<the same key>
   ```

3. Restart the API, the worker and `npm run dev`, then open http://localhost:3000/chat.

The **fake** model asks for a phone number until it gets one, then saves the lead with fixed
example wishes (apartment, ₹1.2 Cr – ₹1.5 Cr, Kokapet). It is for tests and demos only and is
**refused at start-up in production**. For real answers set `CRM_PUBLIC_CHAT_PROVIDER=deepseek`
and `CRM_DEEPSEEK_API_KEY` (or `anthropic` with the Anthropic key). Without a key the chat
answers "not available right now" (503), never a crash.

## Settings

| Where | Setting | Default | Meaning |
|---|---|---|---|
| API | `CRM_PUBLIC_CHAT_TENANT_SLUG` | empty (off) | the organisation whose website this is |
| API | `CRM_PUBLIC_CHAT_SERVER_KEY` | empty (off) | shared secret, at least 32 characters |
| API | `CRM_PUBLIC_CHAT_PROVIDER` | `deepseek` | `deepseek`, `anthropic` or `fake` |
| API | `CRM_PUBLIC_CHAT_MESSAGES_PER_IP_HOUR` | 20 | visitor messages per address per hour |
| API | `CRM_PUBLIC_CHAT_SESSIONS_PER_IP_HOUR` | 3 | new conversations per address per hour |
| API | `CRM_PUBLIC_CHAT_MESSAGES_PER_SESSION` | 30 | visitor messages per conversation |
| API | `CRM_PUBLIC_CHAT_MESSAGES_PER_DAY` | 500 | visitor messages per organisation per day (cost ceiling) |
| API | `CRM_PUBLIC_CHAT_RETENTION_DAYS` | 30 | conversations without a lead are deleted after this many quiet days |
| Web | `PUBLIC_CHAT_SERVER_KEY` | empty (off: `/chat` is 404) | the same secret as the API's |
| Web | `PUBLIC_CHAT_PRIVACY_URL` | empty | link to the company's privacy notice, shown above the chat |

## API

| Method and path | Who | What it does |
|---|---|---|
| `POST /api/v1/public/chat` | only the Next.js server (`X-Public-Chat-Key`) | one visitor message → `{ token, reply, lead_saved }`; errors 404, 422 `message_refused`, 429 `public_chat_rate_limited` / `public_chat_busy`, 503 |
| `GET /api/v1/public-chat/leads/{id}/transcript` | staff with `lead:read:all` or `lead:read:own` who may see that lead (else 404) | `{ started_at, messages: [{ role, content, created_at }] }`; empty for leads that didn't come from the chat |

Web: `POST /api/public-chat` (route handler, public) forwards to the first one; it retries once
without the token when the old conversation was cleaned up (`conversation_not_found`).

**The visitor's address** (for the per-address limits) comes from `x-nf-client-connection-ip`
(set by Netlify itself) when present, otherwise from the first `X-Forwarded-For` entry. Locally
there is no proxy, so every visitor counts as one "unknown" address: after 3 conversations in an
hour, new ones are refused for a while ("You have sent many messages…"). That is the limit
working, not a bug. When going live behind another host, check which header it sets and keep
the platform's own header first - a visitor can add their own `X-Forwarded-For`.

## Data and privacy

- Tables `public_chat_sessions` and `public_chat_messages` (migration 0041, forced RLS like
  every tenant table).
- The token is stored only as a SHA-256 hash; the visitor's address only as a keyed hash (for
  the limits), never shown or logged. Transcripts are never logged.
- The page shows "Your messages and the details you share are stored to answer your enquiry"
  before the first message (plus the privacy link when configured).
- The worker deletes conversations without a lead after the retention; conversations with a
  lead stay as the lead's history.

## Notifications

`public_chat.lead_captured` (`lead_id`, `session_id`) → "New lead from the website chat: <name>"
for every active sales manager, linking to the lead (e-mail per their notification settings).

## Tests

- Backend: `tests/test_public_chat_rules.py`, `tests/db/test_public_chat_api.py`,
  `tests/db/test_public_chat_followup.py` (server key, switched off, limits, guardrails,
  honeypot, one lead per conversation, tenant isolation, notification, transcript access,
  clean-up).
- Web: `src/lib/public-chat-page.test.tsx` (page, route forwarding, cookie options, visitor
  address), `src/lib/public-chat.test.tsx` (transcript card).
- End to end: `e2e/public-chat.spec.ts` (skipped unless `PUBLIC_CHAT_SERVER_KEY` is set).

## Not built yet

- Embedding the chat in the company's own website (iframe or link) - the page sends
  `X-Frame-Options: DENY` today.
- CAPTCHA (a later ADR if bots appear); property search or prices in the chat (BP-08).
