# CRM-109 screen recording: an AI client can only *propose* (script)

**What the video shows (about 3 minutes):** an outside AI tool (Claude Code) connected to the CRM
through the MCP server suggests a change to a lead. Nothing changes until a **different person**
approves it in the CRM. It proves the safety rule of ADR 0020: AI clients read and propose, people
decide.

Everything on screen is fictional demo data (the `alpha-demo` organisation). Do not show
passwords: type them with the recording paused, or crop the sign-in page.

## 1. Before you press record (about 10 minutes, once)

Run from Windows CMD. Each block in its own CMD window; leave them open.

```bat
cd E:\crm-lead\infrastructure
docker compose up -d
```

```bat
cd E:\crm-lead\backend
.venv\Scripts\activate
alembic upgrade head
uvicorn app.main:create_app --factory --reload
```

```bat
cd E:\crm-lead\frontend
npm run dev
```

The MCP server, once (skip if done before):

```bat
cd E:\crm-lead\mcp-server
uv sync
claude mcp list
```

If `claude mcp list` does not show `crm-lead`, or shows a path in another folder, connect it:

```bat
claude mcp remove crm-lead
claude mcp add crm-lead -- E:\crm-lead\mcp-server\.venv\Scripts\crm-mcp.exe
```

Prepare two browser windows side by side:

- **Window A** (normal): http://localhost:3000, for the administrator and later the sales agent.
- **Window B** (a private / InPrivate window): http://localhost:3000, for the manager. A private
  window has its own sign-in, so two people can be signed in at once.

Recording tool on Windows 11: **Snipping Tool → Record** (`Win + Shift + R`), choose the area that
holds the terminal and both browser windows.

## 2. The scenes

| # | Where | Do this | Say (suggestion) |
|---|---|---|---|
| 1 | Window A | Sign in as **`alpha.admin`**. Open **Automation → AI agents**. On the card **AI clients (MCP)** tick **Switched on**, click **Save settings**. | "AI clients are switched off by default. An administrator turns them on, and can turn them off again at any time." |
| 2 | Window A | Sign out. Sign in as **`alpha.agent1`**. Open **Leads** and pick a lead with status **New**. Keep its page open; the lead's id is the last part of the page address. | "This is a sales agent. Here is one of this agent's new leads." |
| 3 | Terminal | Run `claude`. Ask: **"Who am I in the CRM?"** A browser tab opens: sign in as `alpha.agent1`, close the tab. Claude answers with the agent's name. | "The AI tool signs in as the person using it. It never sees the password." |
| 4 | Terminal | Ask: **"Which of my leads are new?"** | "It can read only what this agent may see." |
| 5 | Terminal | Ask: **"Suggest marking lead `<the lead's id>` as contacted because I spoke to them today."** (Or give its name: Claude then looks the id up first.) Claude Code asks to run `propose_lead_status`: allow it once. The answer starts **"Nothing has changed in the CRM. This is only a proposal; a different person must approve ..."** | "The AI cannot change the lead. It can only make a suggestion." |
| 6 | Window A | Reload the lead page: the status is still **New**. Open **Approvals → My proposals**: the suggestion is there, waiting. | "Nothing changed. The suggestion waits for someone else." |
| 7 | Window B | Sign in as **`alpha.manager`**. Open **Approvals → Waiting**. On the card read the line **"through an outside AI client (MCP) - application "crm-mcp""**. | "The manager sees exactly where the suggestion came from: an outside AI tool." |
| 8 | Window B | Click **Approve**, then **Approve and run**. The page says **"The proposal was approved."** Open the lead: status **Contacted**. | "Only now, after a person approved it, does the lead change." |
| 9 | Window A | (Optional) As `alpha.admin`, untick **Switched on** on **AI clients (MCP)** and save. In the terminal ask the same suggestion again: the tool answers **"AI clients are switched off for your organisation; ask a CRM administrator to turn on ..."** | "And the administrator can switch AI clients off at any moment." |

Stop the recording.

## 3. If something goes wrong

| What you see | What to do |
|---|---|
| "AI clients are switched off for your organisation ..." | Scene 1 was not saved: tick **Switched on** and click **Save settings** again. |
| "Lead not found" | The lead belongs to another agent, or the id is mistyped. Use a lead from scene 2. |
| "The same proposal is already waiting." | One is already waiting: approve or reject it first, or pick another new lead. |
| The sign-in tab says the port is in use | Another sign-in is still open: finish it, then ask again. |
| `claude` does not list the CRM tools | Run `claude mcp list` (section 1) and reconnect. |

More detail: [docs/mcp-clients.md](mcp-clients.md), [docs/mcp-tools.md](mcp-tools.md),
[docs/approvals.md](approvals.md), ADR 0020.
