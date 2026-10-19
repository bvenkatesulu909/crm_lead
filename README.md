# crm-lead

A production-oriented Customer Relationship Management (CRM) application, built as a **modular
monolith** and run entirely on a local Windows machine.

> **Status:** Phase 0 (planning and repository setup). No application code yet.
> See [implementation-plan.md](implementation-plan.md) for what comes next.

## Documentation

| File | What it contains |
|---|---|
| [architecture.md](architecture.md) | How the system is designed: stack, modules, tenancy, security, folder layout |
| [implementation-plan.md](implementation-plan.md) | Development phases and their acceptance criteria |
| [CLAUDE.md](CLAUDE.md) | Project rules and conventions (for Claude Code and human contributors) |
| [docs/adr/](docs/adr/) | Architecture Decision Records: why big decisions were made |
| [docs/auth.md](docs/auth.md), [docs/leads.md](docs/leads.md), [docs/frontend.md](docs/frontend.md) | Login & permissions, Lead Management, web app |

## Technology

Next.js · React · TypeScript · Tailwind CSS · Python · FastAPI · PostgreSQL · SQLAlchemy · Alembic ·
Keycloak (OIDC) · Docker Desktop · pytest · Playwright

## Prerequisites (Windows)

| Tool | Version | Why it is needed | Check with (CMD) |
|---|---|---|---|
| Git | 2.40+ | Version control | `git --version` |
| Docker Desktop | recent, **running** | Runs PostgreSQL, Keycloak, MinIO, Mailpit | `docker info` |
| uv | 0.5+ | Installs Python 3.12 and the API's dependencies in an isolated environment | `uv --version` |
| Python | 3.12 (installed by uv) | Backend language | `uv python list` |
| Node.js | 22 LTS or newer LTS | Runs the Next.js frontend and Playwright | `node --version` |
| npm | comes with Node.js | Installs frontend packages | `npm --version` |

### One-time setup

1. Install uv (official installer, run in CMD):

   ```bat
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   Close and reopen CMD afterwards so `uv` is on your `PATH`.

2. Let uv download Python 3.12 (it does **not** replace your system Python):

   ```bat
   uv python install 3.12
   ```

3. Tell Git who you are (used in commit history):

   ```bat
   git config --global user.name "Your Name"
   git config --global user.email "you@example.com"
   ```

4. Start Docker Desktop and wait until it says *Engine running*.

## Running the project

### Local infrastructure (`infrastructure/`)

Needs Docker Desktop with its engine running. First time only, create the settings file and
replace every `change-me` value with a long random password:

```bat
cd infrastructure
copy .env.example .env
```

Start PostgreSQL and check it says `healthy`:

```bat
docker compose up -d
docker compose ps
```

The database listens on `127.0.0.1:5432` only. Data is kept in the Docker volume
`crm-lead_postgres_data`; `docker compose down` keeps it, `docker compose down -v` **deletes it**.

### Backend API (`backend/`)

Run these in CMD from the project folder. The first three are one-time setup.

```bat
cd backend
uv venv --python 3.12 .venv
.venv\Scripts\activate
uv pip install -r requirements-dev.txt
copy .env.example .env
```

Then add the four `CRM_*DATABASE_URL` lines to `backend\.env` (see the comments in
`.env.example`) using the passwords from `infrastructure\.env`, and create the tables:

```bat
alembic upgrade head
```

Start the API (reloads automatically when you save a file):

```bat
uvicorn app.main:create_app --factory --reload
```

Open <http://127.0.0.1:8000/api/v1/health> (should show `"status":"ok"`) or the interactive docs at
<http://127.0.0.1:8000/docs>.

Run the tests and code checks:

```bat
pytest
ruff check .
mypy app tests
```

Database tests (in `tests/db/`) run against the `crm_test` database and are skipped if
`CRM_TEST_DATABASE_URL` is not set.

### Web app (`frontend/`)

```bat
cd frontend
copy .env.example .env.local
npm install
npm run dev
```

Fill in `.env.local` as described in it, then open http://localhost:3000 and sign in with a
test identity from [docs/auth.md](docs/auth.md). Details and tests: [docs/frontend.md](docs/frontend.md).

## Security notes

- Never commit `.env` files. Copy the matching `.env.example` and fill in local values.
- Nothing in this project is deployed to the cloud.
