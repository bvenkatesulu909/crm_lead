# CRM MCP server - tool contract (ADR 0015)

What every MCP client (Claude Code, Claude Desktop, Cursor, VS Code, JetBrains, other agents)
sees when it connects to the `crm-lead` server. A test compares the table below with the live
server, so this page cannot drift from the program.

## The tools

<!-- catalogue:begin (generated: do not edit) -->
Contract version: **0.1.0** - 8 tools, all read-only.

| Tool | What it does | Inputs | API calls |
|---|---|---|---|
| `get_account` | One account with its contacts and open opportunities. | `account_id` (string, required) | `GET /accounts/{id}`<br>`GET /contacts`<br>`GET /opportunities` |
| `get_dashboard` | Dashboard figures for your role (default: last 30 days, widest view you have). | `view` (string) one of `executive`, `manager`, `representative`<br>`start` (string)<br>`end` (string) | `GET /dashboard` |
| `get_lead` | One lead with its 10 most recent activities. | `lead_id` (string, required) | `GET /leads/{id}`<br>`GET /leads/{id}/activities` |
| `list_my_tasks` | Your open tasks and activities: all, overdue, due today, or due in the next 7 days. | `window` (string, default "all") one of `all`, `next_7_days`, `overdue`, `today`<br>`limit` (integer, default 20) | `GET /activities` |
| `list_opportunities` | Deals. Default: your open deals; only_mine=false shows all deals you may see. | `stage` (array/string) one of `closed_lost`, `closed_won`, `negotiation`, `proposal`, `prospecting`, `qualification`<br>`only_mine` (boolean, default true)<br>`query` (string)<br>`limit` (integer, default 20) | `GET /opportunities` |
| `search_accounts` | Search customer accounts by name. Max 50. | `query` (string)<br>`limit` (integer, default 20) | `GET /accounts` |
| `search_leads` | Search leads by name, company or e-mail; optionally filter by status. Max 50. | `query` (string)<br>`status` (array/string) one of `contacted`, `converted`, `new`, `qualified`, `unqualified`<br>`limit` (integer, default 20) | `GET /leads` |
| `whoami` | Who is signed in: name, organisation and roles. | none | `GET /me` |
<!-- catalogue:end -->

Name, inputs and descriptions are generated from the server. The machine-readable copy is
`mcp-server/contract/catalogue.json`.

## Rules every tool follows

- **Names** are `get_*`, `search_*` or `list_*` (plus `whoami`); a tool that changes something
  would be called `propose_*` and only creates a proposal for a person to approve (later step).
- **Read-only, closed-world, idempotent** annotations on every tool (`readOnlyHint`,
  `destructiveHint=false`, `idempotentHint`, `openWorldHint=false`). Clients may use them to skip
  confirmation prompts, so a tool that breaks them is a test failure.
- **Lists** return at most 50 records and say `total`; the default page size is 20.
- **Answers** always have the same shape: `source` ("crm-lead"), `notice`, `record_type`,
  optional `total`, and `data`. The notice tells the model that text under `data` was typed by
  people and must never be followed as an instruction.
- **Only the fields a person would look at** are returned (no full exports, no internal version
  numbers).
- **Errors** are short, safe sentences ("not found, or you are not allowed to see it"); never a
  token, a raw API body or a stack trace. A record the person may not see is "not found".
- **Who may use it:** CRM staff only. Portal customers and platform administrators are refused.
  The CRM API does every tenant, role and record-level check with the person's own token.

## Versioning

The contract version is the package version in `mcp-server/pyproject.toml`.

| Change | Example | Version |
|---|---|---|
| **Breaking** | remove or rename a tool or an input; add a required input; allow fewer values; a read-only tool stops being read-only | new major (before 1.0: new minor, 0.1 -> 0.2) |
| **Compatible** | add a tool, an optional input or an allowed value; change a default | at least a new minor (before 1.0: new patch) |
| **Wording** | change a description | no bump needed |

Tools are never removed silently. To change the catalogue:

```bat
cd mcp-server
rem 1. change the tools in src\crm_mcp\server.py; 2. raise the version in pyproject.toml if the rule asks
uv sync
uv run python -m crm_mcp.catalogue --write
uv run pytest -m "not live"
```

`--write` refuses when the version bump is too small for the change, and the test suite fails
when the committed catalogue or this page differs from the live server.
