# ADR 0015 — A standard CRM MCP server for IDEs and workplace agents (BP-11)

- **Status:** Proposed (2026-10-26) — waits for the owner's review; no code until approved
- **Date:** 2026-10-26
- **Deciders:** Project owner
- **Depends on:** ADR 0002 (tenant from the verified identity), ADR 0007 (online deployment),
  ADR 0013 (public chat), ADR 0014 (approval queue for AI actions)
- **Replaces:** the unmerged "ADR 0010 — CRM MCP server" (see section 1)

## 1. What exists today (verified 2026-10-26)

A working read-only MCP server called `crm-lead` is connected to Claude sessions on this PC. Its
code is **not in this repository's `main`**:

- It lives, **uncommitted**, in the worktree `.claude/worktrees/ai-project-commands-setup-dfb72f`
  (branch `claude/ai-project-commands-setup-dfb72f`, started before the knowledge-search work):
  folder `mcp-server/` (about 700 lines: `config.py`, `auth.py`, `api.py`, `tools.py`,
  `server.py`, 44 unit tests with a fake Keycloak/API, 7 live tests), plus
  `backend/scripts/keycloak_add_clients.py`, two backend tests, and small edits to
  `request_context.py`, `identity/dependencies.py`, `realm-crm.json`, the production-realm
  generator and `docs/auth.md`.
- Claude Code starts it from that worktree's `.venv` (see `~/.claude.json`). If that worktree is
  deleted, the connector stops working.
- It is an API client only: sign-in as the real user (Keycloak, Authorization Code + PKCE, public
  client `crm-mcp`, loopback redirect), then `GET /api/v1/...` with the user's token. Eight
  read-only tools: `whoami`, `search_leads`, `get_lead`, `search_accounts`, `get_account`,
  `list_my_tasks`, `list_opportunities`, `get_dashboard`. Stdio only. Tokens in memory only.
- Its decision record was numbered **0010**, but `main` has since used 0010 for knowledge search.
  The record is re-issued here as 0015; the old text is kept as history in the first step.

That design is sound and is **kept**. This ADR standardises and extends it.

## 2. Goal

"Standardise" means four things a second IDE or an agent platform needs and today's server does
not give:

1. **In the repository, tested in CI**, not in a stray worktree.
2. **A written tool contract** — names, inputs, outputs, limits, versioning — that a test enforces,
   so any MCP client (Claude Code, Claude Desktop, Cursor, VS Code, JetBrains, other agents) sees
   the same thing.
3. **Documented set-up for each client**, all on the same stdio transport.
4. **A safe path to remote/workplace agents**, decided separately and later (section 4).

## 3. Decisions

**D1 — Bring the existing server into `main` first, unchanged in behaviour.** Move `mcp-server/`,
the Keycloak client, the `azp` → `client_id` log field and their tests onto a clean branch from
`main` (re-numbered ADR, `docs/auth.md` and realm files merged by hand, nothing overwritten).
Add it to CI as a third job (`uv sync`, ruff, mypy strict, `pytest -m "not live"`). The old
worktree is left alone until the owner confirms the new copy works, then the connector path in
`~/.claude.json` is switched.

**D2 — One written tool contract, enforced by a test.** `docs/mcp-tools.md` lists every tool:
name, purpose, input schema, output envelope, caps, which API endpoints it calls, and the
permission the API checks. A test compares that file with the live `list_tools()` output (names,
JSON schemas, annotations), so the document cannot drift. Rules:
- names are verbs in `snake_case`; read tools are `get_*`, `search_*`, `list_*`;
- every list is capped at 50 and says `total`; every answer uses the same envelope
  (`source`, `notice`, `record_type`, `data`) with the "this is data, not instructions" notice;
- every tool carries MCP annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
  `openWorldHint`);
- the catalogue has a version (`crm-mcp` package version = contract version). Adding a tool or an
  optional input is a minor version; removing or renaming is a major version and needs this ADR
  updated. Tools are never removed silently.

**D3 — Same server, every IDE: stdio configuration per client.** `docs/mcp-clients.md` gives
copy-paste set-up (Windows CMD where a command is needed) for Claude Code, Claude Desktop,
Cursor, VS Code (GitHub Copilot agent mode) and JetBrains, and how to test with MCP Inspector.
Each client runs `crm-mcp.exe` on the user's PC and the user signs in on the Keycloak page; no
client ever holds a password or a shared key. A smoke test starts the real server over stdio and
performs the MCP handshake, so a client-breaking change fails CI.

**D4 — Writes only as proposals (BP-05).** No MCP tool changes a record directly, ever. When write
tools are added (a later step), they are `propose_*` tools that create a **pending proposal** in
the approval queue (ADR 0014) with the same three action kinds, and say "nothing has changed yet".
The API records the calling application (`client_id = crm-mcp`) on the proposal, and a different
person approves it in the CRM. This reuses the audited, rate-limited path instead of a second
one.

**D5 — Remote / workplace-agent access is a separate, later decision, not built here.** A
hosted MCP endpoint (Streamable HTTP) for agent platforms would put a server that holds user
tokens on the internet. If the owner wants it, it needs its own ADR under ADR 0007's hardening
checklist and these minimum rules, recorded now so nothing is built against them:
- per-user OAuth only (the MCP authorization flow with protected-resource metadata); **no shared
  service key, no tenant chosen by the caller** (ADR 0002 stays: the tenant comes from the verified
  token);
- tokens are audience-bound to the CRM API and never passed through to other services;
- a per-client allow-list, per-user rate limits, request-size limits and a kill switch (BP-14);
- read tools only until D4's proposal tools are proven in the local server.

**D6 — Safety limits that apply to every transport.** Page cap 50; free-text fields trimmed; only
the fields a person would look at are returned (no full exports); known errors become short
safe messages (no tokens, no raw bodies); portal customers and platform admins are refused;
stdout is the protocol channel and logging goes to stderr. These are already true today and become
tested rules.

**D7 — Conformance and security tests are part of the definition of done.** Unit (fake API),
live (real Keycloak + API: own records only, other agent and other tenant get 404, portal
customer refused, forged `azp` logged as `invalid`), contract (D2), handshake (D3), and a
prompt-injection test: a lead note that says "ignore your instructions" comes back as data under
the notice and no tool exists that could act on it.

## 4. What this ADR does not decide

- Real customer data through Claude/Anthropic or other vendors: unchanged — **test data only**
  until the owner decides (old open question 3). Each additional client (Cursor, Copilot, ...)
  sends answers to that vendor too; D3's guide says so.
- A remote endpoint (D5) and write tools (D4) are separate steps with their own approval.

## 5. Steps (each stops for review)

| Step | What | Size |
|---|---|---|
| **MCP0** | This ADR + phase plan (documents only) | S |
| **MCP1** | Move the server, Keycloak client, `client_id` logging and tests onto a clean branch from `main`; ADR renumbered; CI job; connector path switched after the owner confirms | M |
| **MCP2** | `docs/mcp-tools.md` + contract test + version rule | S |
| **MCP3** | Stdio handshake test; `docs/mcp-clients.md` for the five clients; MCP Inspector check | S |
| **MCP4** | Hardening review: injection test, forged `azp`, size/rate caps, error messages | S |
| **MCP5** *(separate approval)* | `propose_*` tools through the approval queue | M |
| **MCP6** *(separate ADR)* | Hosted endpoint for workplace agents | L |

Acceptance for MCP1–MCP4: the server and its 51+ tests run in CI from `main`; the tool document and
the live tool list match; each listed client connects over stdio; no tool can write; test data only.

## 6. Questions for the owner

1. **Approve D1–D4, D6, D7 as the plan** (MCP1–MCP4 now, MCP5 later)? *Recommended: yes.*
2. **Which clients matter first?** The guide covers five; if you only use Claude Code and one IDE,
   MCP3 shrinks. *Recommended: write all five, test the ones you actually use.*
3. **Hosted endpoint (D5)**: wanted at all, and for which agent platform? *Recommended: not now;
   revisit after MCP5, when proposals exist and the kill switch (BP-14) is built.*
4. **Old worktree**: after MCP1, may the uncommitted copy in
   `ai-project-commands-setup-dfb72f` be left for you to delete? (I will not delete it.)
