# CI security gate (BP-20) - short design

- **Status:** Accepted (2026-11-10) with the recommended answer to all five questions in section 5
- **Track:** AI Track A2 in `docs/master-plan.md` (the last open item of A2)
- **Size:** S-M, no ADR (no new service, nothing leaves the repository except package names to the
  public advisory databases)

## 1. The problem in one paragraph

Today CI checks style, types, module boundaries, row-level security (the RLS guard test) and every
test - but nothing fails when a dependency gets a published security hole, when a secret is
committed, or when someone stores money as `float`. On 2026-11-09 the go-live check found 10 high
problems in `pypdf` and 99 high / 6 critical in the Caddy image **by hand**. BP-20 makes the first
three checks automatic and required, so they cannot be forgotten.

## 2. What the checks find today (measured 2026-11-10 on `main` 03d5fe3)

| Check | Tool | Result today |
|---|---|---|
| Python dependencies (API + worker, dev tools) | `pip-audit` 2.9.0 on `backend/requirements*.txt` | **pillow 12.3.0: 39 advisories**, all fixed in 13.0.0. Pillow is not ours directly: `reportlab` needs it, and `fastembed` (the local embedding model) **caps it below 13** |
| Python dependencies (MCP server) | `pip-audit` on `uv.lock` | none |
| Web dependencies | `npm audit` | 7 **moderate**, all in development tools (`typescript-eslint` -> `minimatch`); **0** in what is shipped (`--omit=dev`) |
| Secrets in the whole git history (292 commits) | `gitleaks` 8.24.3 | 2 findings, both **made-up test values** in `backend/tests/test_one_host_files.py` (`0123456789abcdef…`, `K003xYzAbCdEf…`) - not real keys |
| Money as `float` | a small checker (prototype) | 6 places, one cause: the AI price settings `ai_input_price_per_million` / `ai_output_price_per_million` are `float` and are passed on as `float` (the cost code converts carefully through text, so the estimates are right, but the rule says `Decimal`). Prometheus counters must stay `float` |

The RLS guard (`test_rls_tenant_tables.py`) already runs and fails the build; BP-20 keeps it as is.

## 3. The proposal

One new CI job **`security`** (no database, about 1-2 minutes), next to `backend`, `mcp-server` and
`frontend`:

1. **Python audit** - `pip-audit` on `backend/requirements.txt`, `backend/requirements-dev.txt` and
   the MCP server's lock file. Any known advisory fails the job, except entries in
   `security/audit-exceptions.toml`; every exception names the advisory, the reason and an
   **expiry date** (at most 30 days), and an expired exception fails the job by itself.
2. **Web audit** - `npm audit --omit=dev --audit-level=high` fails the job (what users run);
   the full `npm audit` (including development tools) is printed in the job summary, not failing.
3. **Secret scan** - `gitleaks` (image pinned by digest) over the **whole history** on every run
   (21 s today), secrets redacted in the log. Known made-up test values are listed by fingerprint in
   `.gitleaksignore`, never by switching a rule off.
4. **Money check** - `backend/scripts/check_money_types.py`, run as a pytest test in the existing
   backend job: fails on `float` for a name that looks like money (amount, price, cost, total, tax,
   fee, budget, `_inr`/`_eur`/`_usd`, …), on `float(<money>)` and on any `Float` database column.
   Exceptions only with a marked comment and reason (`# money-float-ok: Prometheus needs float`).
   The AI price settings become `Decimal`.
5. **A weekly run** (Monday 03:00 UTC) of the same job on `main`: new advisories appear without any
   code change; a red run shows on GitHub and in the e-mail GitHub sends you.
6. **Required check:** after the first green run you add `security` to the branch protection's
   required checks (I give the clicks), so auto-merge waits for it too.

Out of scope (later, if you want): scanning the built Docker images with Trivy in CI (done by hand
in the go-live checks), licence checks.

## 4. Steps (Phase SG), each stops for review

| Step | Content |
|---|---|
| SG1 | Money check + AI price settings as `Decimal` + tests that the checker catches a planted `float` price |
| SG2 | `security` job: pip-audit with the exceptions file, npm audit, gitleaks with `.gitleaksignore`; pillow handled (question 2) |
| SG3 | Weekly schedule, job summary, docs (`docs/ci-security-gate.md` final, CLAUDE.md commands), required-check instructions |

Each step proves its check can fail: a planted vulnerable pin, a planted fake key and a planted
`float` price must turn the job red (on a throwaway branch, never merged).

## 5. Questions for the owner (recommended answer first)

1. **What fails the build?** *Recommended:* any Python advisory (with dated exceptions); web: only
   high/critical in shipped packages; development-tool findings are shown, not failing.
   Alternative: every finding fails, including moderate development-tool ones.
2. **Pillow (39 advisories, blocked by fastembed's cap below 13).** *Recommended:* in SG2 try a
   newer `fastembed` that allows Pillow 13; if none exists, a 30-day exception with the reason, and
   the job reminds us when it expires. Alternative: pin Pillow 13 and stop using fastembed's local
   model (a bigger change to knowledge search).
3. **Secret scan scope.** *Recommended:* the whole history on every run (cheap today).
   Alternative: only the new commits of a pull request.
4. **Weekly run.** *Recommended:* yes. Alternative: only on pushes and pull requests.
5. **Required check.** *Recommended:* yes, after the first green run (you click it in GitHub
   settings). Alternative: report only.
