# crm-mcp — read-only CRM access for Claude (ADR 0015 (originally 0010))

`crm-mcp` is a small program that lets **Claude Desktop** or **Claude Code** answer questions
from your CRM data ("which of my deals close this month?", "summarise the Acme account").
It speaks **MCP** (Model Context Protocol), the standard way AI apps call tools.

**What it can and cannot do**

- It only **reads**. No tool can create, change or delete anything.
- It signs in **as you**, on the normal Keycloak login page in your browser. Claude never sees
  your password, and every answer contains only records you are allowed to see. The CRM API does
  all the checks (tenant, role, record-level), exactly as for the web app.
- It works for **staff users** only (not portal customers).
- It runs **on this PC only** (Claude starts it). Nothing is put online.
- After restarting Claude you sign in again (tokens are kept in memory only).
- Every call shows up in the API log with `"client_id": "crm-mcp"`, so MCP use is traceable.
- Answers are sent to Anthropic as part of the conversation. Use it only with **test data**
  until the owner decides otherwise (ADR 0015 (originally 0010), open question 3).

## Tools

| Tool | What it returns | API used |
|---|---|---|
| `whoami` | your name, organisation, roles | `GET /me` |
| `search_leads` | leads by name/company/e-mail, optional status filter | `GET /leads` |
| `get_lead` | one lead + its 10 most recent activities | `GET /leads/{id}`, `/activities` |
| `search_accounts` | accounts by name | `GET /accounts` |
| `get_account` | one account + contacts + open deals | `GET /accounts/{id}`, `/contacts`, `/opportunities` |
| `list_my_tasks` | your open tasks: all / overdue / today / next 7 days | `GET /activities?mine=true` |
| `list_opportunities` | your open deals (or all you may see) | `GET /opportunities` |
| `get_dashboard` | dashboard figures for your role | `GET /dashboard` |

Lists return at most 50 records. Every answer starts with a notice telling Claude that record
text is data, not instructions (protection against "prompt injection" hidden in a note).

## Setup (once)

Needs: the local stack running (`cd infrastructure && docker compose up -d`) and the API
(`uvicorn app.main:create_app --factory --reload` in `backend`).

1. Install the program (creates `mcp-server\.venv`):

   ```bat
   cd mcp-server
   uv sync
   ```

2. Add the `crm-mcp` login client to your running Keycloak (only needed once; it never changes
   or deletes existing clients - Keycloak reads `realm-crm.json` only on its very first start):

   ```bat
   cd backend
   .venv\Scripts\activate
   python -m scripts.keycloak_add_clients
   ```

3. Connect Claude.

   **Claude Code** (run in the project folder):

   ```bat
   claude mcp add crm-lead -- E:\crm-lead\mcp-server\.venv\Scripts\crm-mcp.exe
   ```

   **Claude Desktop**: Settings → Developer → Edit Config, and add to
   `claude_desktop_config.json`:

   ```json
   {
     "mcpServers": {
       "crm-lead": {
         "command": "E:\\crm-lead\\mcp-server\\.venv\\Scripts\\crm-mcp.exe"
       }
     }
   }
   ```

   Restart Claude Desktop afterwards.

4. Ask Claude "who am I in the CRM?". The first question opens the sign-in page in your browser;
   sign in (for example as `alpha.agent1`), close the tab, and Claude gets the answer.

## Settings (optional environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `CRM_MCP_API_URL` | `http://localhost:8000/api/v1` | CRM API address |
| `CRM_MCP_ISSUER` | `http://localhost:9080/realms/crm` | Keycloak realm |
| `CRM_MCP_CLIENT_ID` | `crm-mcp` | Keycloak client |
| `CRM_MCP_REDIRECT_PORT` | `8765` | Local port for the sign-in answer (must match the Keycloak client) |

Plain `http://` is accepted only for `localhost`; anything else must be `https://`.

## Try it by hand (MCP Inspector)

```bat
cd mcp-server
npx @modelcontextprotocol/inspector .venv\Scripts\crm-mcp.exe
```

## Tests

```bat
cd mcp-server
uv run pytest -m "not live"
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests
```

- `-m "not live"`: unit tests with a fake Keycloak and API (no services needed).
- Plain `pytest` also runs `tests/test_live.py` against the real local Keycloak + API (skipped
  when they are not running). It signs in with the fictional test users; the password is read
  from `CRM_TEST_KEYCLOAK_USER_PASSWORD` (environment or `backend\.env`).

## How it fits together

```
Claude Desktop / Claude Code
        │  MCP over stdio (this PC)
        ▼
crm-mcp  ──(1) browser sign-in, PKCE──►  Keycloak (client crm-mcp, public, loopback redirect)
        │
        └─(2) GET /api/v1/... with YOUR access token ──►  CRM API (all permission checks)
```

Files: `config.py` (settings), `auth.py` (sign-in, tokens), `api.py` (HTTP calls, safe error
messages), `tools.py` (the tools), `server.py` (MCP registration, `crm-mcp` entry point).
