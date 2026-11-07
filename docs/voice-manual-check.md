# Voice conversation - checking it with a real microphone

An automated test cannot hear. This is the short list for a person to try on staging
(`https://crm.crmlead.co.in`) with a real microphone and speakers. It takes about 10 minutes.
Background: [voice-conversation.md](voice-conversation.md), [ADR 0023](adr/0023-live-voice-assistant.md).

**Use the fictional organisation `demo-fictional` only.** The browser's own speech engine sends the
audio to the browser maker (Google, Apple or Microsoft) - never test with real customer data.

## Before you start

1. Sign in as the demo organisation's administrator.
2. Open **AI agents** (Automation menu) and switch **Voice** on. It is off by default.
3. Open **AI Assistant** (`/assistant`). The card "Talk with the assistant" must show a privacy note.

## A. iPhone, Safari (the hardest browser for speech)

| # | Do this | You should see / hear | Pass? |
|---|---|---|---|
| 1 | Open the page, tap **Start voice conversation**. | Safari asks to use the microphone; you allow it. A "listening" state shows. | |
| 2 | Say: "Give me one short tip for my first call with a new lead." | Your words appear as text, then an answer starts appearing and is spoken sentence by sentence. | |
| 3 | Time it: from the end of your sentence to the first spoken word. | Under about 5 seconds usually (the free model can be slower at times). | |
| 4 | While it speaks, tap **Skip**. | Speech stops at once; it goes back to listening. | |
| 5 | Say a follow-up with only "it": "Make that tip shorter." | The answer refers to the earlier tip (memory works). | |
| 6 | Say: "Mark one of my leads as contacted." | It says a **proposal** was made and **waits for approval**; nothing changed. | |
| 7 | Tap **Stop**. | Microphone indicator in Safari disappears. | |
| 8 | Lock the phone and unlock it mid-conversation. | The page recovers or says clearly that it stopped; no stuck "listening". | |

## B. Laptop with speakers (echo)

The assistant's voice coming out of the speakers can be heard by the microphone.

| # | Do this | You should see / hear | Pass? |
|---|---|---|---|
| 1 | Start a conversation with speakers on, headphones off. Ask a question that gets a long answer. | The assistant does **not** answer itself, and its own voice does not appear as your text. | |
| 2 | Tick **Allow interrupting by speaking**, ask again, and speak over the answer. | It stops and listens. (If its own voice also stops it, untick the box and note it - then headphones are advised.) | |
| 3 | Leave the box unticked and speak over the answer. | It keeps speaking until you press **Skip** (expected). | |
| 4 | Stay silent after your question for 10 seconds. | It does not send empty turns. | |

## C. Same checks in Chrome on the laptop

Repeat A2, A4 and A6 in Chrome. Chrome's speech recognition needs an internet connection.

## Write down

- Device, browser and version.
- For every row that failed: what happened, and any message on screen.
- The time to the first spoken word (A3).

Send the notes back and the problems become fixes. Before **go live**, set
`CRM_VOICE_BROWSER_ENGINE=false` (see the deployment checklist) unless the CRM speech service is
configured.
