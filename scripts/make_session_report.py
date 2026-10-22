from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

OUT = r"E:\crm-lead\docs\CRM-Lead_Session_Report_2026-10-22.docx"
doc = Document()
for section in doc.sections:
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)

styles = doc.styles
styles["Normal"].font.name = "Calibri"
styles["Normal"].font.size = Pt(10.5)
for name, size in (("Title", 26), ("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 11.5)):
    styles[name].font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
    styles[name].font.size = Pt(size)

def body(text, bold=False, italic=False):
    p = doc.add_paragraph()
    r = p.add_run(text); r.bold = bold; r.italic = italic
    p.paragraph_format.space_after = Pt(5)
    return p

def bullets(items):
    for item in items:
        p = doc.add_paragraph(item, style="List Bullet")
        p.paragraph_format.space_after = Pt(2)

def numbered(items):
    for item in items:
        p = doc.add_paragraph(item, style="List Number")
        p.paragraph_format.space_after = Pt(2)

def table(headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = h
        for p in cell.paragraphs:
            for r in p.runs: r.bold = True
    for row in rows:
        cells = t.add_row().cells
        for i, value in enumerate(row):
            cells[i].text = str(value)
    if widths:
        for row in t.rows:
            for i, width in enumerate(widths):
                row.cells[i].width = Cm(width)
    doc.add_paragraph()

title = doc.add_heading("CRM-Lead: Session Work Report", level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
p = doc.add_paragraph("What was built, tested, fixed, and what remains")
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.runs[0].italic = True
p = doc.add_paragraph("Report date: 22 October 2026  |  Repository: E:\\crm-lead  |  Branch: rag-r0-setup  |  Commit: 9d4a131")
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.runs[0].font.size = Pt(8.5)

doc.add_heading("1. Executive summary", level=1)
body("This report describes the work completed in the CRM-Lead project during the session. The work covered the R4-R6 scope: knowledge-base answers with citations, evaluation, feedback, document versioning and retention, local monitoring, customer and staff AI assistants, guardrails, and voice input/output.")
body("The project is substantially complete for the implemented scope and the work is pushed to GitHub. The most important remaining gap is database-level tenant isolation: only the two knowledge tables have PostgreSQL Row-Level Security (RLS). The other 45 tenant-owned tables still depend on application-level tenant filters.")
table(["Item", "Value"], [
    ["Branch", "rag-r0-setup"],
    ["Commit", "9d4a131 — Complete R5-R6 knowledge, assistant, voice, monitoring and RLS bootstrap"],
    ["Remote", "github.com/bvenkatesulu909/crm_lead"],
    ["Working tree", "clean at time of report"],
    ["Full backend suite", "1121 passed, 4 skipped"],
    ["RLS coverage", "2 of 47 tenant-owned tables"],
], widths=[3.5, 12.5])

doc.add_heading("2. What was delivered, step by step", level=1)

doc.add_heading("Step 1 — Repository audit and baseline", level=2)
body("The existing application was inspected before changing it: frontend routes, FastAPI modules, Keycloak authentication, the DeepSeek/Anthropic model abstraction, RAG implementation, RLS policies, migrations, and tests.")
bullets([
    "Frontend: Next.js App Router with server actions; browser never receives access tokens.",
    "Backend: FastAPI modular monolith with one package per domain and thin routers.",
    "Database: PostgreSQL with Alembic migrations and composite tenant foreign keys.",
    "AI: provider abstraction for Anthropic and DeepSeek; local embeddings with fastembed.",
    "RLS: only kb_documents and kb_chunks were protected at the start.",
])

doc.add_heading("Step 2 — Feedback and knowledge gaps (R6.1)", level=2)
bullets([
    "Added migration 0027 with rag_queries and rag_feedback.",
    "Staff and portal knowledge answers now record the question, answer, sources and surface, and return query_id.",
    "Added helpful / not-helpful feedback API and UI for staff and portal answers.",
    "Added scripts/rag_gaps_report.py: 7-day report with surface counts, negative rate, unanswered and refused questions.",
    "Added tests for feedback upsert, gaps aggregation and answer/portal flows.",
])

doc.add_heading("Step 3 — Document versions, freshness and retention (R6.2/R6.3)", level=2)
bullets([
    "Migration 0028 added group_id, version, is_archived and archived_at to knowledge documents.",
    "Replacing a document archives the previous version and deletes its chunks in the same transaction.",
    "Added archive endpoint; retrieval excludes archived documents.",
    "Added nightly freshness/retention module: missing chunks, chunks of archived documents, old embedding model, stuck processing, and 90-day rag_queries cleanup.",
    "Added person-erasure helper for stored questions.",
    "Tests cover versions, archive, freshness, retention and erasure.",
])

doc.add_heading("Step 4 — Live monitoring (R6)", level=2)
bullets([
    "Added Prometheus, Grafana, Alertmanager and a local webhook receiver to the local compose stack, bound to 127.0.0.1.",
    "Grafana dashboard has 9 panels and was verified through the API.",
    "Prometheus scrapes the API; target crm-api is up.",
    "The worker-heartbeat alert fired and was delivered to Alertmanager and a webhook receiver (payload contained CrmWorkerHeartbeatStale).",
    "OTLP tracing was verified with a local receiver: HTTP spans exported; manual SQLAlchemy spans added because the official instrumentation does not support SQLAlchemy 2.1.5.",
])

doc.add_heading("Step 5 — Customer AI assistant, guardrails and voice", level=2)
bullets([
    "The customer portal assistant answers from the customer's own data with permission-checked tools.",
    "Input guardrails: length, prompt injection, card/SSN/API-key patterns.",
    "Output guardrails: blocks system-prompt/secret markers and replaces unsafe answers.",
    "Customer tools include accounts, orders, invoices, tickets, knowledge, quotes, products and contacts.",
    "Added browser speech-to-text (MediaRecorder/server gateway with Web Speech fallback) and text-to-speech.",
    "Added ElevenLabs and local faster-whisper/Piper provider adapters behind the SpeechProvider interface.",
    "TTS playback now has Listen, Stop and Replay controls.",
])

doc.add_heading("Step 6 — Staff AI assistant", level=2)
bullets([
    "Added a separate /assistant page and sidebar item, not linked to the knowledge module.",
    "Removed the mandatory ticket number; the assistant now accepts a question only.",
    "Added intent retrieval for accounts, contacts, leads, tickets, quotes, orders and invoices.",
    "Added a typed staff tool registry: search_leads, search_accounts, get_account, list_account_contacts, get_ticket.",
    "Every tool result is trimmed, permission-checked and includes a record link.",
    "No write tool and no automatic sending.",
    "Enter submits; a finished voice transcript auto-submits.",
])

doc.add_heading("Step 7 — Test harness and RLS groundwork", level=2)
bullets([
    "Added owner_engine and owner_db_session fixtures for privileged test setup.",
    "Added committed_owner_data and clean_committed_data for owner-created rows plus truncation cleanup.",
    "Verified crm_owner has BYPASSRLS and crm_app does not.",
    "Added deep RLS tests for knowledge tables: select/insert/update/delete, missing context, cross-tenant foreign keys, transaction-local setting.",
    "Added scripts/rls_audit.py and docs/rls-audit.md.",
    "Important: world/setup fixtures still create through crm_app; this is the remaining prerequisite before RLS on identity tables.",
])

doc.add_heading("Step 8 — Evaluations", level=2)
bullets([
    "RAG retrieval: 100 free cases, threshold 0.64, hit@5 1.000 and 100% negative rejection (earlier evidence).",
    "Paid answer evidence: 4/4, groundedness 0.917, faithfulness 1.0, correctness 1.0, injection safe.",
    "Leads: live DB retrieval, golden cases 5/5, live answer score 1.0 with zero invented emails.",
    "Quotes/orders/invoices: golden cases 5/5, live answer scores 1.0 for each module.",
    "Voice: provider tests, live TTS/STT round-trip, Chromium browser E2E with fake microphone.",
    "Full backend suite: 1121 passed, 4 skipped.",
])

doc.add_heading("3. Verification and test evidence", level=1)
table(["Check", "Result"], [
    ["Full backend suite", "1121 passed, 4 skipped"],
    ["Staff assistant/tools", "10 passed"],
    ["Staff account/contact RBAC DB", "4 passed"],
    ["Customer tool isolation DB", "3 passed"],
    ["Leads cross-tenant DB", "passed"],
    ["Leads golden cases", "5/5"],
    ["Leads live answer score", "1.0, 0 invented emails"],
    ["Quote/order/invoice golden + live eval", "5/5, score 1.0 each"],
    ["Voice provider tests", "6 passed"],
    ["Voice STT/TTS round-trip", "correct transcript"],
    ["Voice browser E2E", "1 passed (Chromium)"],
    ["Knowledge RLS deep tests", "7 passed"],
    ["Frontend typecheck/lint/build", "passed at last check"],
], widths=[7.5, 8.5])

doc.add_heading("4. What is not complete", level=1)
table(["Gap", "Why it matters"], [
    ["Full RLS rollout", "Only 2 of 47 tenant tables are protected; a direct SQL path can still read another tenant's rows for accounts, leads, quotes, orders, invoices, users, etc."],
    ["0029 identity RLS", "Login reads users before the tenant is known; sign-up writes access_requests. Needs SECURITY DEFINER functions and policies."],
    ["Test bootstrap migration", "World fixtures still insert as crm_app, so enabling RLS on identity/all tables would break the suite."],
    ["0030 remaining tables", "Policies for the 45 tenant tables, one domain at a time."],
    ["0031 worker", "Worker claims outbox jobs across tenants; ADR accepts a dedicated crm_worker BYPASSRLS role."],
    ["Voice load/cross-browser", "Only Chromium fake-mic E2E; no Firefox/WebKit or latency/load measurements."],
    ["DeepSeek tool calling", "DeepSeek provider fails closed when tools are supplied; tool-based assistant flows still need Anthropic."],
    ["Production deployment", "Everything still runs locally; no public deployment or production secrets."],
], widths=[4.2, 11.8])

doc.add_heading("5. Security notes", level=1)
bullets([
    "crm_app is a non-owner role without BYPASSRLS; crm_owner has BYPASSRLS only for migrations/test setup.",
    "Tenant is taken from the verified token, never from client input.",
    "Timestamps, IDs and server-controlled fields are not accepted from clients.",
    "The ElevenLabs API key was exposed in a vendor error during configuration. Rotate it and update backend/.env.",
    "No .env, metrics token, raw audio or test alert payloads are committed.",
    "Audio is processed for transcription and not stored by CRM-Lead.",
])

doc.add_heading("6. Key files and commands", level=1)
doc.add_heading("Key files", level=2)
bullets([
    "backend/alembic/versions/20261021_0027_rag_feedback.py — feedback tables.",
    "backend/alembic/versions/20261021_0028_knowledge_versions.py — versions/archive/retention.",
    "backend/alembic/versions/20261021_0022_rls_knowledge.py — knowledge RLS.",
    "backend/app/modules/knowledge/ — RAG, freshness, gaps, feedback.",
    "backend/app/modules/assistant/ — customer assistant, staff assistant, guardrails, tools.",
    "backend/app/modules/voice/ — speech provider abstraction and endpoints.",
    "backend/scripts/rls_audit.py — RLS inventory and probes.",
    "backend/scripts/eval_leads_answer.py — scored leads answer eval.",
    "backend/scripts/eval_staff_golden.py — golden case runner.",
    "backend/scripts/eval_staff_quotes_orders_invoices.py — quote/order/invoice scored eval.",
    "frontend/src/app/portal/assistant/ — customer chat UI.",
    "frontend/src/app/(app)/assistant/ — staff AI assistant.",
    "frontend/src/components/voice-recorder.tsx — MediaRecorder UI.",
    "frontend/e2e/voice.spec.ts — Chromium voice E2E.",
    "docs/rls-audit.md, docs/adr/0009-row-level-security.md, docs/voice.md.",
])

doc.add_heading("Commands (Windows CMD)", level=2)
cmds = [
    "cd E:\\crm-lead\\backend",
    ".venv\\Scripts\\python -m pytest",
    ".venv\\Scripts\\ruff check .",
    ".venv\\Scripts\\ruff format --check .",
    ".venv\\Scripts\\mypy app tests",
    ".venv\\Scripts\\lint-imports",
    ".venv\\Scripts\\python -m scripts.rls_audit",
    ".venv\\Scripts\\python -m scripts.eval_staff_golden",
    ".venv\\Scripts\\python -m scripts.eval_staff_quotes_orders_invoices",
]
for cmd in cmds:
    p = doc.add_paragraph(cmd)
    p.runs[0].font.name = "Consolas"
    p.runs[0].font.size = Pt(9)
    p.paragraph_format.space_after = Pt(2)

doc.add_heading("7. Honest conclusion", level=1)
body("The implemented R4-R6 product scope is running and tested: knowledge answers, feedback, versions, retention, monitoring, customer and staff assistants, guardrails, voice and evaluations. The repository is pushed and the full backend suite passed with 1121 tests.")
body("The application is not yet fully tenant-isolated at the database layer. Until migrations 0029-0031 and the owner-based test bootstrap are completed, RLS protects only the knowledge tables. This report does not claim otherwise.")

doc.save(OUT)
print("SAVED", OUT)
