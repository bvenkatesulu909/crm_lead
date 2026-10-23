"""Read-only RLS inventory + cross-tenant probes (RLS P1 audit).

python -m scripts.rls_audit
"""

import json
import sys

from sqlalchemy import column, func, select, table, text

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
        roles: dict[str, bool] = dict(
            session.execute(
                text(
                    "select rolname, rolbypassrls from pg_roles "
                    "where rolname in ('crm_app', 'crm_owner')"
                )
            ).all()
        )
        tenant_tables = [row for row in tables if row.has_tenant]
        protected = [row for row in tenant_tables if row.relrowsecurity and row.relforcerowsecurity]
        unprotected = [row for row in tenant_tables if row not in protected]
        # Run as crm_app with no tenant context: every tenant table must show 0 rows.
        clear_tenant(session)
        visible_without_context = {
            row.relname: session.scalar(
                select(func.count()).select_from(table(row.relname, column("tenant_id")))
            )
            for row in tenant_tables
        }
        leaking = {name: rows for name, rows in visible_without_context.items() if rows}
        report = {
            "tenant_tables": len(tenant_tables),
            "protected_tables": [row.relname for row in protected],
            "unprotected_tenant_tables": [row.relname for row in unprotected],
            "policies": [f"{name}.{policy}" for name, policy in policies],
            "roles": roles,
            "tables_visible_without_tenant_context": leaking,
        }
    engine.dispose()
    print(json.dumps(report, indent=2, default=str))
    return 1 if unprotected or leaking else 0


if __name__ == "__main__":
    sys.exit(main())
