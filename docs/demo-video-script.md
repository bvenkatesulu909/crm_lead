# CRM-116 demo video: from a website visitor to an approved change (script)

**What the video shows (about 5 minutes):** the whole story of the CRM in one run. A visitor chats on
the website, a lead appears, an AI agent only *suggests* what to do, a manager approves it, and the
AI settings stay under the administrator's control. It is the video for the README ("Live demo")
and for the one-page case study.

Everything on screen is fictional demo data (`alpha-demo`). Do not show passwords: type them with
the recording paused, or crop the sign-in page. No real customer data, ever.

## 1. Before you press record (about 15 minutes, once)

Run from Windows CMD, each block in its own window. Setup details: [README](../README.md#run-it-on-your-pc).

```bat
cd E:\crm-lead\infrastructure
docker compose up -d
```

```bat
cd E:\crm-lead\backend
.venv\Scripts\activate
alembic upgrade head
python -m scripts.seed_dev_data
set CRM_AI_PROVIDER=fake
set CRM_PUBLIC_CHAT_SERVER_KEY=<a made-up 32+ character key, see docs/public-chat.md>
uvicorn app.main:create_app --factory --reload
```

```bat
cd E:\crm-lead\backend
.venv\Scripts\activate
python -m app.worker
```

```bat
cd E:\crm-lead\frontend
set PUBLIC_CHAT_SERVER_KEY=<the same key>
npm run dev
```

`CRM_AI_PROVIDER=fake` is a scripted model: it needs no paid key and gives the same answers every
time, which is what a recording needs. Say so in the video if you mention the AI ("a scripted
model for the demo"). Do not present it as a real model.

Also prepare: **Window A** (normal browser) for staff, **Window B** (InPrivate) for the manager,
**Window C** for the public chat page `http://localhost:3000/chat`, and Mailpit
(`http://localhost:8025`) in a tab. Recording tool: **Snipping Tool, Record** (`Win + Shift + R`).

## 2. The scenes

| # | Where | Do this | Say (suggestion) |
|---|---|---|---|
| 1 | Slide or README | Show the first Mermaid diagram of the [README](../README.md#how-it-fits-together) for 15 seconds. | "One backend made of modules, a web app, a worker, and AI agents that can only suggest." |
| 2 | Window C | Open `/chat`. Write: "I want a 3 BHK in Pune, budget about 1.2 crore." Answer the follow-up questions with a made-up name and phone (the demo's own numbers). | "A visitor talks to the website chat. No sign-in." |
| 3 | Window A | Sign in as the manager (`alpha.manager`). The bell shows a notification: open it, then open the new lead. Scroll to the **Website chat** card. | "The sales manager is told at once. The lead has the wishes and the whole conversation." |
| 4 | Window A | On the lead page click **Qualify** (Qualifier card). A proposal appears; the page says nothing has changed yet. | "An AI agent can read the lead and suggest a next step. It cannot change anything." |
| 5 | Window B | Sign in as an agent (`alpha.agent1`), open **Approvals**: the agent can see their own proposals but has no **Approve** button; **Waiting** is missing. | "The person who asked cannot approve their own suggestion." |
| 6 | Window A | **Approvals → Waiting**: read the **Safety check** and "Would change" lines, then **Approve**. The lead's status changes; **What happened** shows the result matched the plan. | "A second person decides. The CRM checks afterwards that exactly the planned change happened." |
| 7 | Window A | Sign in as `alpha.admin`, open **Automation → AI agents**: show the cards, the usage bar and the estimated cost, then switch one agent **off** and save. | "The administrator sees every AI agent, its monthly budget and cost, and can switch it off at any time." |
| 8 | Window A | Back on a lead, click **Qualify** again: it says the agent is switched off. Switch it on again. | "Off means off: no call is made." |
| 9 | Window A | **Quotes**: create a quote with a discount above 10 %. Show that it waits for a manager's approval; approve it as the manager; click **Send by e-mail**. | "Money rules need a second pair of eyes too." |
| 10 | Mailpit tab | Open the e-mail: the quote PDF is attached. | "The customer gets the quote as a PDF." |
| 11 | Window A | **Reports → Website chat**: conversations started, leads saved, what people did with the AI's suggestions. | "The numbers for a pilot: how many chats became leads, and what people did with the suggestions." |

Stop the recording. Trim the start and end; export as MP4; keep it under about 6 minutes.

## 3. If something goes wrong

| What you see | What to do |
|---|---|
| `/chat` shows "Page not found" | The two server keys are missing or different: set both and restart the API and the web app. |
| No notification after the chat | The worker is not running: start `python -m app.worker`. |
| **Qualify** says there is no procedure | Write the steps first: **Automation → Qualifier**. |
| **Qualify** says the agent is off | **Automation → AI agents**: switch the Qualifier on. |
| The same proposal is already waiting | Approve or reject it first, or pick another lead. |
| No e-mail in Mailpit | The worker is not running, or Mailpit is not up (`docker compose ps`). |

## 4. After recording

- Put the video link in the README under **Live demo** (or next to it), and in the case study.
- Do **not** claim the system is online: nothing is live until the owner says "go live".
