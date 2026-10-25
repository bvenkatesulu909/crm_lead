# Connecting IDEs and agents to the CRM (MCP server, ADR 0015)

The `crm-lead` MCP server lets an AI tool in your IDE read CRM data ("which of my deals close this
month?") **as you**. It is a small program that your IDE starts on **this PC** (transport "stdio").
It only reads; the tools are listed in [mcp-tools.md](mcp-tools.md).

## Read this first

- **Test data only.** Every answer is sent to the vendor of the tool you use (Anthropic, Cursor,
  Microsoft/GitHub, JetBrains and their model providers). Until the owner decides about real
  customer data (ADR 0015, section 4), use only the fictional demo organisations.
- **You sign in as yourself.** The first CRM question opens the Keycloak sign-in page in your
  browser. The password never goes to the IDE. Staff users only (not portal customers).
- **After restarting the IDE you sign in again** (tokens are kept in memory only).
- **One sign-in at a time.** The sign-in answer comes back on `http://127.0.0.1:8765/callback`.
  If two IDEs ask you to sign in at the very same moment, the second says the port is in use:
  finish the first sign-in, then ask again.
- Nothing is put online. The program talks to the local CRM API and Keycloak only.

## One-time set-up (every client)

Run these from Windows CMD in the project folder `E:\crm-lead` (the local stack and the API must
be running: `cd infrastructure && docker compose up -d`, and `uvicorn` in `backend`).

```bat
cd mcp-server
uv sync
```

Then, only if the login client `crm-mcp` is not yet in your Keycloak (new installs only):

```bat
cd ..\backend
.venv\Scripts\activate
python -m scripts.keycloak_add_clients
```

The program to start is: `E:\crm-lead\mcp-server\.venv\Scripts\crm-mcp.exe` (no arguments).
In JSON files below, backslashes are doubled (`E:\\crm-lead\\...`).

Optional settings (environment variables, same for every client): `CRM_MCP_API_URL`
(default `http://localhost:8000/api/v1`), `CRM_MCP_ISSUER` (default
`http://localhost:9080/realms/crm`), `CRM_MCP_REDIRECT_PORT` (default `8765`).

## The five clients

| Client | Where the setting lives | Tested here? |
|---|---|---|
| Claude Code | `claude mcp add` | **Yes** - the server has been used from Claude Code |
| Claude Desktop | `claude_desktop_config.json` | Same JSON shape as the others; not opened by me |
| Cursor | `mcp.json` | Not tested |
| VS Code (GitHub Copilot agent mode) | `.vscode\mcp.json` | Not tested |
| JetBrains IDEs (AI Assistant) | Settings dialog, JSON | Not tested |

"Not tested" means the steps follow each product's documented format and the server itself is
proven to start and answer over stdio (see "Check the server by itself" below), but I have not
clicked through that product. Menu names can change between versions: if one differs, the JSON is
what matters.

### Claude Code

```bat
claude mcp add crm-lead -- E:\crm-lead\mcp-server\.venv\Scripts\crm-mcp.exe
```

Add `--scope user` to have it in every project instead of only this one. Check with
`claude mcp list`, or type `/mcp` inside Claude Code.

### Claude Desktop

Settings -> Developer -> Edit Config opens `claude_desktop_config.json`. Add:

```json
{
  "mcpServers": {
    "crm-lead": {
      "command": "E:\\crm-lead\\mcp-server\\.venv\\Scripts\\crm-mcp.exe"
    }
  }
}
```

Quit Claude Desktop completely (also from the tray) and start it again.

### Cursor

Create `.cursor\mcp.json` in the project (or `%USERPROFILE%\.cursor\mcp.json` for all projects):

```json
{
  "mcpServers": {
    "crm-lead": {
      "command": "E:\\crm-lead\\mcp-server\\.venv\\Scripts\\crm-mcp.exe",
      "args": []
    }
  }
}
```

Open Settings -> MCP (or Tools & MCP) and make sure `crm-lead` is switched on.

### VS Code (GitHub Copilot, agent mode)

Create `.vscode\mcp.json` in the project. Note the top-level key is `servers`, not `mcpServers`:

```json
{
  "servers": {
    "crm-lead": {
      "type": "stdio",
      "command": "E:\\crm-lead\\mcp-server\\.venv\\Scripts\\crm-mcp.exe",
      "args": []
    }
  }
}
```

Open the Copilot chat in **Agent** mode, click the tools icon and tick `crm-lead`. (The command
"MCP: List Servers" shows whether it started.)

### JetBrains IDEs (IntelliJ IDEA, PyCharm, WebStorm ...)

Settings -> Tools -> AI Assistant -> Model Context Protocol (MCP) -> Add -> **As JSON**:

```json
{
  "mcpServers": {
    "crm-lead": {
      "command": "E:\\crm-lead\\mcp-server\\.venv\\Scripts\\crm-mcp.exe",
      "args": []
    }
  }
}
```

Apply, then check the server shows a green status in the same list.

## First question to ask

"Who am I in the CRM?" (calls `whoami`). A browser tab opens; sign in as a demo staff user (for
example `alpha.agent1`), close the tab, and the tool answers. Then try "Which of my leads are
new?" or "List my deals".

## Check the server by itself (no IDE)

These two checks need no sign-in:

```bat
cd mcp-server
uv run pytest tests\test_stdio_handshake.py
npx @modelcontextprotocol/inspector@2.12.0 --cli .venv\Scripts\crm-mcp.exe --method tools/list
```

The first starts the real program over stdio, performs the MCP handshake and compares the tools
with [mcp-tools.md](mcp-tools.md); it also runs in CI. The second is the official MCP Inspector in
command-line mode and prints the same 8 tools. For the interactive screen, leave out `--cli`
(this downloads the Inspector from npm the first time).

## When it does not work

| Symptom | Likely cause and fix |
|---|---|
| The IDE says the server failed to start | Wrong path, or `uv sync` was not run. Run `E:\crm-lead\mcp-server\.venv\Scripts\crm-mcp.exe` in CMD: it should wait silently (stop with Ctrl+C); an error line names the problem (for example an address that is not `localhost`/`https`). |
| Sign-in page does not open | Copy the address from the IDE's MCP log (the server writes it to its error output) into a browser. |
| "port 8765 ... is in use" | Another sign-in is in progress, or another program uses that port. Finish it, or set `CRM_MCP_REDIRECT_PORT` and add the same redirect to the `crm-mcp` client in Keycloak. |
| "the CRM API is not reachable" | The API is not running on `CRM_MCP_API_URL`. |
| "your role is not allowed" / "waiting for approval" | The signed-in user has no staff role yet; sign in as another user. |
| "not found, or you are not allowed to see it" | Normal answer for a record that does not exist or is someone else's. |
