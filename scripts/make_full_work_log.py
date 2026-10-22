from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.enum.table import WD_TABLE_ALIGNMENT

OUT = r"E:\crm-lead\docs\CRM-Lead_Full_Work_Log_2026-10-22.docx"
doc = Document()
for s in doc.sections:
    s.top_margin = Cm(1.8); s.bottom_margin = Cm(1.8)
    s.left_margin = Cm(2.0); s.right_margin = Cm(2.0)
doc.styles["Normal"].font.name = "Calibri"
doc.styles["Normal"].font.size = Pt(9.5)
for name, size in (("Title", 24), ("Heading 1", 15), ("Heading 2", 12), ("Heading 3", 10.5)):
    doc.styles[name].font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
    doc.styles[name].font.size = Pt(size)

def p(text, bold=False, italic=False, size=None):
    para = doc.add_paragraph()
    run = para.add_run(text); run.bold = bold; run.italic = italic
    if size: run.font.size = Pt(size)
    para.paragraph_format.space_after = Pt(3)
    return para

def b(items):
    for item in items:
        para = doc.add_paragraph(item, style="List Bullet")
        para.paragraph_format.space_after = Pt(1)

def n(items):
    for item in items:
        para = doc.add_paragraph(item, style="List Number")
        para.paragraph_format.space_after = Pt(1)

def tbl(headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        t.rows[0].cells[i].text = h
        for para in t.rows[0].cells[i].paragraphs:
            for run in para.runs: run.bold = True
    for row in rows:
        cells = t.add_row().cells
        for i, value in enumerate(row): cells[i].text = str(value)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths): row.cells[i].width = Cm(w)
    doc.add_paragraph()

def phase(num, title, goal, actions, problems, verification):
    doc.add_heading(f"{num}. {title}", level=1)
    p("Goal", bold=True); p(goal)
    p("What was done", bold=True); b(actions)
    if problems:
        p("Problems found and fixes", bold=True); b(problems)
    p("Verification / result", bold=True); b(verification)
    doc.add_page_break()

title = doc.add_heading("CRM-Lead — Full Work Log", level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
p("Complete chronological record of the work performed in this chat", italic=True).alignment = WD_ALIGN_PARAGRAPH.CENTER
p("22 October 2026  |  E:\\crm-lead  |  branch rag-r0-setup  |  commit 9d4a131", size=8.5).alignment = WD_ALIGN_PARAGRAPH.CENTER

doc.add_heading("How to read this document", level=1)
p("This is not a summary. It is a chronological engineering log. Each phase records the goal, the files and systems changed, the errors encountered, how each error was fixed, and the tests or live checks that were actually run. Numbers are reported as observed; if a check was not run, it says so.")
p("At the start of this chat, the project already existed and R0–R5 work was present in the working tree. This log starts with the first inspected state (Step 11 partial) and records every subsequent change through the GitHub push and final evaluation.")
tbl(["Fixed reference", "Value"], [
    ["Repository", "github.com/bvenkatesulu909/crm_lead"],
    ["Branch", "rag-r0-setup"],
    ["Pushed commit", "9d4a131 — Complete R5-R6 knowledge, assistant, voice, monitoring and RLS bootstrap"],
    ["Database head", "0028 (knowledge versions/retention)"],
    ["Full backend suite at last run", "1121 passed, 4 skipped (EXIT=0)"],
    ["RLS coverage at last audit", "2 of 47 tenant-owned tables"],
], [4.0, 12.0])

phase(1, "Baseline inspection: what existed before changes",
      "Understand the real state of the repository before editing, so later work reused existing code instead of rebuilding it.",
      [
        "Inspected backend modules: accounts, activities, assistant, catalog, contacts, dashboard, documents, identity, invoices, knowledge, leads, notifications, orders, portal, quotes, relationships, reports, sales, support, workflows.",
        "Inspected the Next.js App Router structure: staff screens under (app), customer portal under portal, auth callback routes, print views.",
        "Confirmed Keycloak OIDC Authorization Code + PKCE, encrypted session cookie, JWT verification via JWKS, tenant from verified token.",
        "Confirmed DeepSeek and Anthropic model abstraction; knowledge RAG with fastembed BAAI/bge-small-en-v1.5, pgvector + full-text RRF, reranker disabled.",
        "Confirmed RLS only on kb_documents/kb_chunks (migration 0022), crm_current_tenant fail-closed, bind_tenant + after_begin listener.",
        "Counted 1,091 backend tests collected, 13 frontend Vitest files, 22 Playwright specs.",
      ],
      ["No code changes in this phase."],
      ["Baseline understood; no false assumptions about missing features."])

phase(2, "Step 11 (R6.1): feedback and weekly gaps",
      "Add helpful/not-helpful feedback to every knowledge answer and a weekly report of knowledge gaps; skip the article-drafting gap agent.",
      [
        "Created migration 0027: rag_queries and rag_feedback, tenant/user composite FKs, surface check, unique feedback per query/user.",
        "Added RagQuery and RagFeedback models.",
        "Recorded every staff and portal answer (question, answer, sources, surface, user) and returned query_id.",
        "Added POST /api/v1/knowledge/feedback and POST /api/v1/portal/knowledge/feedback with upsert behaviour.",
        "Added helpful/not-helpful buttons to staff and portal answers with a thank-you state.",
        "Added scripts/rag_gaps_report.py: last 7 days by surface, negative rate, unanswered, refused, top questions.",
        "Added feedback and aggregation tests; updated OpenAPI and inventory.",
      ],
      [
        "Migration 0027 failed: composite FK ON DELETE SET NULL would null tenant_id. Changed to CASCADE.",
        "Composite FK to rag_queries failed: no unique (tenant_id,id). Added unique constraint on rag_queries.",
        "Model/migration unique constraint names differed; made names explicit and fixed FK ondelete to match model (RESTRICT).",
        "Frontend TypeScript and hook lint issues in the feedback component were fixed (state ordering, useActionState).",
      ],
      ["Targeted answer/portal/feedback tests passed (20).", "Full suite at this stage: 1069 passed, 4 skipped, one migration-sync failure that was fixed and retested green."])

phase(3, "Step 12 (R6.2/R6.3): versions, archive, freshness, retention, erasure",
      "New document versions re-ingest; nightly checks report knowledge anomalies; archiving deletes chunks transactionally; 90-day retention; person erasure clears stored questions.",
      [
        "Migration 0028 added group_id, version, is_archived, archived_at and a unique (tenant,group,version).",
        "Upload accepts replaces_document_id; previous version is archived and its chunks deleted in the same transaction; version increments.",
        "Added POST /knowledge/documents/{id}/archive.",
        "Retrieval excludes archived documents.",
        "Added freshness.py: published without chunks, chunks of archived documents, old embedding-model chunks, stuck processing; worker hook; 90-day rag_queries deletion.",
        "Added erasure helper for a person's rag_queries.",
        "Added version/archive tests, maintenance tests, retention and erasure tests.",
      ],
      [
        "Initial migration failed because composite FK required a unique key on (tenant,group,version); fixed.",
        "Freshness module could not use instrumentation because of an error; implemented direct SQL queries.",
        "Mypy errors on rowcount/upsert and missing fixtures; fixed with getattr and PostgreSQL insert.",
        "Test cleanup hung on an open app transaction; fixed by closing app session before truncate.",
      ],
      ["Version/archive 14 passed; maintenance/retention/erasure 16 passed at the time.", "DB head advanced to 0028."])

phase(4, "R6: live monitoring, alerts, webhook and OTLP",
      "Run Prometheus, Grafana, Alertmanager and a webhook receiver locally, prove the heartbeat alert, and verify tracing export.",
      [
        "Added prometheus, grafana, alertmanager and webhook receiver to infrastructure/docker-compose.yml, bound to 127.0.0.1.",
        "Scrape token protected /api/v1/internal/metrics; Prometheus scrapes crm-api.",
        "Grafana dashboard provisioned with 9 panels; verified through Grafana API.",
        "Worker heartbeat alert CrmWorkerHeartbeatStale fired; alert became active in Alertmanager.",
        "Added a webhook receiver container on the compose network; Alertmanager delivered the payload; file contained CrmWorkerHeartbeatStale (1,055+ bytes).",
        "Added manual SQLAlchemy span fallback because the official instrumentation rejects SQLAlchemy 2.1.5; verified OTLP receiver received HTTP + DB spans.",
      ],
      [
        "Main compose file lost postgres/files volume declarations during insertion; restored them.",
        "Alertmanager crashed on unsupported --config.expand-env; removed the flag.",
        "Host webhook receiver was refused from the container; moved receiver into compose and used http://webhook:9999/alerts.",
        "OTLP probe first received 0 bytes because the receiver directory did not exist; created the directory, then received 3,585 and 4,035 bytes in separate probes.",
        "SQLAlchemy instrumentation version mismatch was logged as an error; replaced with lightweight manual spans.",
      ],
      ["Grafana 9 panels, Prometheus target crm-api up, alert fired and delivered, OTLP/DB spans received.", "This was local validation, not production pager integration."])

phase(5, "Customer AI assistant, input/output guardrails and browser voice",
      "Give customers a secure AI chat over their own CRM data, with guardrails and speech input/output.",
      [
        "Added assistant guardrails: empty/long input, injection patterns, card/SSN/API-key patterns; output blocks system prompt/secret markers.",
        "Integrated guardrails into portal assistant send_message; output sanitised before storage.",
        "Added browser SpeechRecognition and SpeechSynthesis controls (Speak/Listen).",
        "Added MediaRecorder VoiceRecorder component and authenticated Next.js BFF /api/voice/transcribe.",
        "Added server TTS BFF /api/voice/speak and upgraded Listen to server audio with play/stop/replay and browser fallback.",
        "Added auto-submit after a finished voice transcript and Enter-to-send.",
      ],
      [
        "Recorder state-in-effect lint errors; fixed with useSyncExternalStore and action wrapper.",
        "Next.js dev server file locks blocked edits; stopped server briefly, edited, restarted.",
        "Microphone remained blocked even when Chrome allowed it. Root cause: the app sent Permissions-Policy microphone=(); changed to microphone=(self).",
      ],
      ["Frontend typecheck/lint/build passed; Chromium voice E2E passed with fake mic and mocked STT/TTS."])

phase(6, "Server speech providers: OpenAI, ElevenLabs, local Whisper/Piper",
      "Add a production-capable server-side STT/TTS abstraction instead of relying only on browser speech.",
      [
        "Added SpeechProvider protocol and OpenAI-compatible provider (/audio/transcriptions, /audio/speech).",
        "Added authenticated /api/v1/voice/transcribe and /api/v1/voice/speak; audio limits, TTS guardrails, no storage.",
        "Added ElevenLabs adapter (/v1/speech-to-text, /v1/text-to-speech/{voice_id}).",
        "Added local adapter: lazy faster-whisper and Piper CLI.",
        "Added configuration for provider, models, voice, piper command and requirements.",
      ],
      [
        "ElevenLabs synthesis returned 404 voice_not_found because CRM_VOICE_TTS_VOICE had been set to the API key value. Used the default premade voice ID 21m00Tcm4TlvDq8ikWAM; synthesis then returned a 33 KB MP3.",
        "The ElevenLabs key was exposed in the vendor error and earlier diagnostics; flagged for rotation.",
        "STT round-trip initially failed only because a probe reused an async client across two event loops; single-loop round-trip transcribed correctly.",
        "Requirements test failed because faster_whisper was imported but not installed; changed to importlib lazy loading and added faster-whisper to requirements.",
      ],
      ["Voice provider tests 6 passed; live TTS 47 KB; live STT round-trip produced the spoken sentence."])

phase(7, "Customer tools: quotes, products, contacts",
      "Let the customer assistant answer questions beyond accounts/orders/invoices/tickets/knowledge.",
      [
        "Added customer_quotes/customer_quote in quotes/api.py using portal policy and PORTAL_QUOTE_READ.",
        "Added customer_products (active products only, no price-book internals) and customer_contacts (granted accounts only).",
        "Registered list_my_quotes, get_my_quote, list_products, list_my_contacts.",
        "Added tool-scope, quote isolation and safe-field DB tests.",
      ],
      [
        "Customer product/contact APIs initially had missing type annotations and granted_account_ids misuse; fixed to use the grant subquery directly.",
        "Several PowerShell edits produced literal backtick-n sequences, causing syntax errors; repaired by newline normalization.",
      ],
      ["Assistant contract updated; 4 tool-scope tests and 3 DB isolation tests passed; final tool set 13 tools."])

phase(8, "Staff AI assistant: separate page, ticket removal, cross-module retrieval",
      "Create a staff AI assistant that is not linked to Knowledge and does not require a ticket number for every question.",
      [
        "Added /assistant page, sidebar item and module card link.",
        "Added support-first staff endpoint /api/v1/assistant/ask.",
        "Added staff tool protocol: typed Pydantic arguments, permission checks, trimmed results, record links, max tool rounds.",
        "Added search_accounts, get_account, list_account_contacts, get_ticket, search_leads tools.",
        "Added account/contact APIs and DB RBAC/tenant tests.",
        "Removed the mandatory ticket field from UI and backend; optional ticket context retained.",
        "Added retrieval for leads, tickets, quotes, orders, invoices and accounts.",
        "Added Enter submit and voice auto-submit.",
      ],
      [
        "Initial module card linked AI Assistant to /knowledge/search and then /tickets; both were wrong. Eventually linked to the dedicated /assistant page.",
        "Staff assistant required UUID while users saw T-0060; added ticket-number resolution T-0060/60/UUID.",
        "The assistant returned an empty leads answer because it had no lead retriever; added leads API + intent.",
        "A staff question returned 503; root cause was CRM_AI_PROVIDER unset, defaulting to Anthropic with no key. Set CRM_AI_PROVIDER=deepseek; model available.",
        "A request ID could not be traced because API logs are not persisted; recommended redirecting stdout to a log file.",
      ],
      ["Staff tests 10 passed; account RBAC 4 passed; lead cross-tenant DB passed; API restarted healthy."])

phase(9, "Evaluations: RAG, leads, quotes, orders, invoices, voice, full suite",
      "Measure the AI and retrieval work with real data and guard against regressions.",
      [
        "RAG: 100 free retrieval cases; threshold 0.64; earlier paid answer evidence 4/4 (groundedness 0.917, faithfulness 1.0, correctness 1.0, injection safe).",
        "Leads: live retrieval (10 rows, all permitted fields), golden cases 5/5, live answer score 1.0 and zero invented emails.",
        "Quotes/orders/invoices: golden cases 5/5, live answer scores 1.0 for each; retrieval links correct; injection blocked.",
        "Voice: 6 provider tests; live TTS+STT round-trip; Chromium fake-mic Playwright test passes.",
        "RLS knowledge deep tests: 7 passed.",
        "Full backend suite: first run 1119 passed + 2 failed (stale OpenAPI, requirements missing faster-whisper); fixed both; second run 1121 passed, 4 skipped, EXIT=0.",
      ],
      [
        "Golden runner initially had a bool passed to all(); fixed.",
        "Leads answer score was 0.533 because missing company/email columns were counted as misses; denominator changed to only existing fields; score became 1.0.",
        "Quote/order/invoice eval scripts needed line wrapping and import fixes; final EVAL=0.",
      ],
      ["All observed eval results are listed in the verification table below."])

phase(10, "RLS migration 0029-0031 planning and current security state",
      "Move tenant isolation from application filters into PostgreSQL for every table.",
      [
        "Audited 47 tenant-owned tables: 2 protected, 45 unprotected.",
        "Deep-tested knowledge RLS: select/insert/update/delete, missing context, cross-tenant FK, transaction-local setting, app role cannot disable row security.",
        "Applied crm_owner BYPASSRLS and documented it as setup-only.",
        "Added owner_engine/owner_db_session/committed_owner_data/clean_committed_data fixtures.",
        "Proposed 0029 identity functions+policies, 0030 remaining tables by domain, 0031 worker claim.",
        "Audit showed crm_app with no tenant context could read users/access_requests/accounts from two tenants.",
      ],
      [
        "Attempting full RLS before identity/test bootstrap would break login, signup, worker and tests; stopped instead of applying unsafe migrations.",
        "World/setup fixtures still create as crm_app, so 0029 is blocked until that harness migration is done.",
      ],
      ["RLS remains 2/47; no 0029-0031 files exist. This is the largest remaining gap."])

phase(11, "Git commit and push",
      "Publish the completed work to the GitHub repository without leaking secrets.",
      [
        "Reviewed 145 changed/untracked paths.",
        "Confirmed backend/.env, frontend/.env.local and infrastructure/.env are ignored.",
        "Removed temporary alert sink and alert-received payload; added ignore rule.",
        "Committed 9d4a131 and pushed branch rag-r0-setup.",
        "Verified local HEAD equals origin/rag-r0-setup; working tree clean.",
      ],
      ["No .env, metrics token or received alert payload is tracked."],
      ["Push succeeded; PR link: https://github.com/bvenkatesulu909/crm_lead/pull/new/rag-r0-setup"])

doc.add_heading("Verification log (actual observed results)", level=1)
tbl(["Check", "Observed result", "Status"], [
    ["Full backend suite (final)", "1121 passed, 4 skipped; EXIT=0", "PASS"],
    ["Earlier full suite", "1119 passed, 2 failed (OpenAPI + requirements); both fixed", "FIXED"],
    ["Staff assistant/tools", "10 passed", "PASS"],
    ["Staff account/contact RBAC DB", "4 passed", "PASS"],
    ["Customer tool isolation DB", "3 passed", "PASS"],
    ["Leads cross-tenant DB", "passed", "PASS"],
    ["Leads golden cases", "5/5", "PASS"],
    ["Leads live answer", "score 1.0; 0 invented emails", "PASS"],
    ["Quote/order/invoice golden+live", "5/5; each 1.0", "PASS"],
    ["Voice provider unit", "6 passed", "PASS"],
    ["Voice live TTS", "47,272-byte MP3", "PASS"],
    ["Voice live STT round-trip", "correct transcript", "PASS"],
    ["Voice browser E2E", "1 passed, Chromium", "PASS"],
    ["Knowledge RLS deep", "7 passed", "PASS"],
    ["RLS full coverage", "2/47 tables protected", "OPEN"],
    ["Voice load/cross-browser", "not tested", "OPEN"],
    ["DeepSeek tool calling", "not supported", "OPEN"],
], [5.0, 8.5, 3.0])

doc.add_heading("Errors encountered and exact resolutions", level=1)
errs = [
    ("Migration composite FK", "ON DELETE SET NULL would null tenant_id; composite unique key missing.", "CASCADE + unique (tenant,id) + explicit names."),
    ("Test cleanup hang", "TRUNCATE blocked by open app transaction.", "Rollback/close app session before truncate."),
    ("Alertmanager crash", "unknown --config.expand-env flag.", "Removed flag; hardcoded local webhook URL."),
    ("Webhook refused", "Host receiver unreachable from container.", "Webhook receiver moved into compose network."),
    ("OTLP 0 bytes", "Receiver directory missing; spans timed out.", "Create directory; retry; spans received."),
    ("SQLAlchemy spans", "Instrumentation rejects SQLAlchemy 2.1.5.", "Manual before/after cursor spans."),
    ("ElevenLabs 404", "Voice ID contained API key.", "Used default premade voice ID; advised rotation."),
    ("Voice STT probe", "Async client reused across event loops.", "Single-loop round-trip; production uses one loop."),
    ("Microphone blocked", "App sent Permissions-Policy microphone=().", "Changed to microphone=(self)."),
    ("Assistant 503", "CRM_AI_PROVIDER unset; defaulted Anthropic with no key.", "Set CRM_AI_PROVIDER=deepseek."),
    ("Stale tests", "OpenAPI contract/requirements after new code.", "Regenerated contract; lazy import + requirement."),
    ("PowerShell edits", "Literal backtick-n in source files.", "Normalized real newlines; ruff reformat."),
]
tbl(["Error", "Cause", "Fix"], [(a,b,c) for a,b,c in errs], [5.0, 7.0, 4.5])

doc.add_heading("Current state and remaining work", level=1)
p("Completed and pushed: R4-R6 knowledge features, monitoring, customer and staff assistants, guardrails, voice, and evaluations. The full backend suite is green at the last run.")
p("Not complete:")
b([
    "RLS is still knowledge-only: 2/47 tenant tables. 0029 identity, owner-based test bootstrap, 0030 remaining tables, 0031 worker role are not implemented.",
    "Voice load/latency and Firefox/WebKit coverage are not tested.",
    "DeepSeek cannot perform tool calls in this codebase; tool-based flows still require Anthropic.",
    "No public production deployment. Everything runs locally.",
    "The ElevenLabs API key was exposed and should be rotated.",
])

doc.add_heading("Appendix: key commands (Windows CMD)", level=1)
for cmd in [
    "cd E:\\crm-lead\\backend",
    ".venv\\Scripts\\python -m pytest",
    ".venv\\Scripts\\ruff check .",
    ".venv\\Scripts\\ruff format --check .",
    ".venv\\Scripts\\mypy app tests",
    ".venv\\Scripts\\lint-imports",
    ".venv\\Scripts\\python -m scripts.rls_audit",
    ".venv\\Scripts\\python -m scripts.eval_leads_answer",
    ".venv\\Scripts\\python -m scripts.eval_staff_golden",
    ".venv\\Scripts\\python -m scripts.eval_staff_quotes_orders_invoices",
    "cd E:\\crm-lead\\frontend",
    "npm run typecheck",
    "npm run lint",
    "npm run build",
    "npx playwright test e2e/voice.spec.ts",
]:
    para = doc.add_paragraph(cmd); para.runs[0].font.name = "Consolas"; para.runs[0].font.size = Pt(8.5)

p("End of log. This document records what was actually run and observed; open items are explicitly marked.", italic=True)

doc.save(OUT)
print("SAVED", OUT)
