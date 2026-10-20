"""Write a current inventory of the project to docs/inventory.md.

Run from the backend folder with the virtual environment active:

    python -m scripts.report_inventory

The file contains counts and route lists only - it is generated, not a design document.
Live database figures are marked as such; when PostgreSQL is unreachable the script still
writes the rest and says the database was not checked, so it also works offline.
"""

from datetime import date
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
OUTPUT = REPO / "docs" / "inventory.md"
OPENAPI = REPO / "docs" / "api" / "openapi.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
NL = chr(10)
BT = chr(96)


def code(text: str) -> str:
    return BT + text + BT


def api_summary() -> tuple[int, int, int, list[tuple[str, int]]]:
    import json

    if not OPENAPI.exists():
        return 0, 0, 0, []
    spec: dict[str, Any] = json.loads(OPENAPI.read_text(encoding="utf-8"))
    paths: dict[str, Any] = spec.get("paths", {})
    operations = 0
    tags: dict[str, int] = {}
    for path_item in paths.values():
        for method, operation in path_item.items():
            if method in HTTP_METHODS:
                operations += 1
                for tag in operation.get("tags", ["(none)"]):
                    tags[tag] = tags.get(tag, 0) + 1
    schemas = len(spec.get("components", {}).get("schemas", {}))
    return operations, len(paths), schemas, sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))


def migration_summary() -> tuple[list[str], int]:
    versions = REPO / "backend" / "alembic" / "versions"
    files = sorted(versions.glob("*.py"))
    revisions: set[str] = set()
    parents: set[str] = set()
    for file in files:
        for line in file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("revision") and "=" in stripped:
                quoted = stripped.split(chr(34))
                if len(quoted) > 1:
                    revisions.add(quoted[1])
            elif stripped.startswith("down_revision") and "=" in stripped:
                quoted = stripped.split(chr(34))
                parents.update(quoted[1::2])
    return sorted(revisions - parents), len(files)


def frontend_routes() -> list[tuple[str, str]]:
    app_dir = REPO / "frontend" / "src" / "app"
    found: set[tuple[str, str]] = set()
    for file in app_dir.rglob("*"):
        if file.name not in ("page.tsx", "route.ts"):
            continue
        parts = list(file.parent.relative_to(app_dir).parts)
        kept = [p for p in parts if not (p.startswith("(") and p.endswith(")"))]
        route = "/" + "/".join(kept) if kept else "/"
        kind = "page" if file.name == "page.tsx" else "route handler"
        found.add((route, kind))
    return sorted(found)


def count_files(folder: Path, patterns: tuple[str, ...]) -> int:
    if not folder.exists():
        return 0
    total = 0
    for pattern in patterns:
        for path in folder.rglob(pattern):
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            total += 1
    return total


def database_summary() -> dict[str, Any] | None:
    try:
        import psycopg

        from app.core.config import Settings

        settings = Settings()
        url = settings.database_url.get_secret_value().replace(
            "postgresql+psycopg://", "postgresql://"
        )
        with psycopg.connect(url, connect_timeout=3) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select version_num from alembic_version")
                revision_row = cursor.fetchone()
                cursor.execute("select count(*) from pg_tables where schemaname = current_schema()")
                tables_row = cursor.fetchone()
                cursor.execute(
                    "select count(*) from pg_tables where schemaname = current_schema()"
                    " and rowsecurity"
                )
                rls_row = cursor.fetchone()
                cursor.execute(
                    "select count(*) from pg_policies where schemaname = current_schema()"
                )
                policies_row = cursor.fetchone()
        return {
            "revision": str(revision_row[0]) if revision_row else "unknown",
            "tables": int(tables_row[0]) if tables_row else 0,
            "rls_tables": int(rls_row[0]) if rls_row else 0,
            "policies": int(policies_row[0]) if policies_row else 0,
        }
    except Exception:
        return None


def render() -> str:
    today = date.today().isoformat()
    operations, path_count, schemas, tags = api_summary()
    heads, migration_count = migration_summary()
    routes = frontend_routes()
    pages = sum(1 for _, kind in routes if kind == "page")
    handlers = len(routes) - pages
    backend_tests = count_files(REPO / "backend" / "tests", ("test_*.py",))
    unit_tests = count_files(REPO / "frontend" / "src", ("*.test.ts", "*.test.tsx"))
    unit_tests += count_files(REPO / "frontend" / "test", ("*.test.ts", "*.test.tsx"))
    e2e_tests = count_files(REPO / "frontend" / "e2e", ("*.spec.ts",))
    docs = count_files(REPO / "docs", ("*.md",))
    adrs = count_files(REPO / "docs" / "adr", ("*.md",))
    database = database_summary()

    lines: list[str] = [
        "# Project inventory (generated)",
        "",
        "*Generated on "
        + today
        + " by "
        + code("python -m scripts.report_inventory")
        + " (run in "
        + code("backend/")
        + " with the venv active).*",
        "",
        "This file records counts and routes, not design decisions. Do not edit it by hand -",
        "re-run the command. The 18 October 2026 audit is in [gap-analysis.md](gap-analysis.md)",
        "and the current status is in [CLAUDE.md](../CLAUDE.md).",
        "",
        "## API (from " + code("docs/api/openapi.json") + ")",
        "",
        "- **"
        + str(operations)
        + "** operations over **"
        + str(path_count)
        + "** paths and **"
        + str(schemas)
        + "** schemas.",
        "- If this contract is stale, run " + code("python -m scripts.export_openapi") + ".",
        "",
        "| Tag | Operations |",
        "|---|---|",
    ]
    for tag, count in tags:
        lines.append("| " + tag + " | " + str(count) + " |")

    lines += ["", "## Database (live)", ""]
    if database is None:
        lines.append("- Not checked: PostgreSQL was not reachable when this file was generated.")
    else:
        lines += [
            "- Alembic revision: **" + str(database["revision"]) + "**",
            "- Tables in the current schema: **" + str(database["tables"]) + "**",
            "- Tables with Row-Level Security: **"
            + str(database["rls_tables"])
            + "** ("
            + str(database["policies"])
            + " policies)",
        ]

    lines += [
        "",
        "## Migrations (from " + code("backend/alembic/versions/") + ")",
        "",
        "- Migration files: **" + str(migration_count) + "**",
        "- Heads: " + (", ".join(code(head) for head in heads) or "(none)"),
        "",
        "## Web app (" + code("frontend/src/app") + ")",
        "",
        "- " + str(pages) + " pages and " + str(handlers) + " route handlers.",
        "",
        "| Route | Kind |",
        "|---|---|",
    ]
    for route, kind in routes:
        lines.append("| " + code(route) + " | " + kind + " |")

    lines += [
        "",
        "## Tests",
        "",
        "- Backend test files: **" + str(backend_tests) + "**",
        "- Frontend component test files: **" + str(unit_tests) + "**",
        "- Playwright end-to-end specs: **" + str(e2e_tests) + "**",
        "",
        "## Documentation",
        "",
        "- Markdown documents under "
        + code("docs/")
        + ": **"
        + str(docs)
        + "** ("
        + str(adrs)
        + " in "
        + code("docs/adr/")
        + ")",
        "",
    ]
    return NL.join(lines)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(), encoding="utf-8", newline=NL)
    print("wrote " + str(OUTPUT))


if __name__ == "__main__":
    main()
