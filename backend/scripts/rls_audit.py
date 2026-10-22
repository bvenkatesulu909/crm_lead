"""Read-only RLS inventory + cross-tenant probes (RLS P1 audit).

python -m scripts.rls_audit
"""

import json
import sys

from sqlalchemy import text

from app import model_registry as _model_registry  # noqa: F401
from app.core.config import get_settings
from app.core.db import clear_tenant, create_db_engine, create_session_factory


def main() -> int:
    engine = create_db_engine(get_settings())
    factory = create_session_factory(engine)
    with factory() as session:
        tables = session.execute(
            text(
                """
                select c.relname, c.relrowsecurity, c.relforcerowsecurity,
                       exists(
                         select 1 from information_schema.columns col
                         where col.table_schema = 'public' and col.table_name = c.relname
                           and col.column_name = 'tenant_id'
                       ) as has_tenant
                from pg_class c
                join pg_namespace n on n.oid = c.relnamespace
                where n.nspname = 'public' and c.relkind = 'r'
                  and c.relname <> 'alembic_version'
                order by c.relname
                """
            )
        ).all()
        policies = session.execute(
            text("select tablename, policyname from pg_policies order by tablename")
        ).all()
        roles = dict(
            session.execute(
                text(
                    "select rolname, rolbypassrls from pg_roles "
                    "where rolname in ('crm_app', 'crm_owner')"
                )
            ).all()
        )
        tenant_tables = [row for row in tables if row.has_tenant]
        protected = [row for row in tenant_tables if row.relrowsecurity]
        unprotected = [row for row in tenant_tables if not row.relrowsecurity]
        probes: dict[str, object] = {}
        for name in ("users", "access_requests", "outbox_jobs", "accounts", "tickets"):
            if any(row.relname == name for row in tables):
                probes[name] = (
                    session.execute(
                        text(
                            f"select count(*) as rows, count(distinct tenant_id) as tenants "  # noqa: S608
                            f"from {name}"
                        )
                    )
                    .one()
                    ._asdict()
                )
        clear_tenant(session)
        kb_without_context = session.scalar(text("select count(*) from kb_documents"))
        report = {
            "tenant_tables": len(tenant_tables),
            "protected_tables": [row.relname for row in protected],
            "unprotected_tenant_tables": [row.relname for row in unprotected],
            "policies": [f"{table}.{policy}" for table, policy in policies],
            "roles": roles,
            "cross_tenant_probe": probes,
            "knowledge_rows_without_tenant_context": kb_without_context,
        }
    engine.dispose()
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
