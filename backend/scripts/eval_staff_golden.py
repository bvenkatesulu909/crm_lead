"""Execute the stored staff golden questions against retrieval + guardrails."""

import json
import sys
from pathlib import Path

from sqlalchemy import select

from app import model_registry as _model_registry  # noqa: F401
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import get_settings
from app.core.db import create_db_engine, create_session_factory
from app.modules.assistant import guardrails
from app.modules.assistant.staff_service import retrieve_context
from app.modules.identity.models import Tenant, User

CASES = Path(__file__).resolve().parents[1] / "evals" / "staff" / "leads_cases.json"
PREFIX = {
    "leads": "/leads",
    "accounts": "/accounts",
    "quotes": "/quotes",
    "orders": "/orders",
    "invoices": "/invoices",
    "tickets": "/tickets",
}


def main() -> int:
    settings = get_settings()
    engine = create_db_engine(settings)
    factory = create_session_factory(engine)
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    results = []
    with factory() as session:
        tenant = session.scalars(select(Tenant).where(Tenant.slug == "alpha-demo")).one()
        user = session.scalars(
            select(User).where(
                User.tenant_id == tenant.id, User.email == "admin@alpha.example.test"
            )
        ).one()
        principal = Principal(
            subject="golden",
            issuer="eval",
            user_type="staff",
            roles=frozenset(),
            permissions=frozenset(
                {
                    Permission.LEAD_READ_ALL,
                    Permission.ACCOUNT_READ_ALL,
                    Permission.QUOTE_READ_ALL,
                    Permission.ORDER_READ_ALL,
                    Permission.INVOICE_READ_ALL,
                    Permission.TICKET_READ_ALL,
                }
            ),
            user_id=user.id,
            tenant_id=tenant.id,
        )
        for case in cases:
            decision = guardrails.inspect_input(case["question"])
            if case.get("expect_guardrail"):
                ok = not decision.allowed
                results.append({"id": case["id"], "pass": ok, "reason": "guardrail"})
                continue
            if not decision.allowed:
                results.append({"id": case["id"], "pass": False, "reason": "blocked"})
                continue
            rows, _ = retrieve_context(session, principal, case["question"])
            prefix = PREFIX.get(case["expected_module"], "")
            module_ok = bool(rows) and all(str(r.get("link", "")).startswith(prefix) for r in rows)
            fields_ok = (not rows) or all(
                field in rows[0] for field in case.get("expected_fields", [])
            )
            tenant_ok = not case.get("expect_no_other_tenant") or "beta-demo" not in json.dumps(
                rows
            )
            results.append(
                {
                    "id": case["id"],
                    "pass": module_ok and fields_ok and tenant_ok,
                    "rows": len(rows),
                    "module": case["expected_module"],
                }
            )
    engine.dispose()
    passed = sum(1 for r in results if r["pass"])
    print(json.dumps({"cases": len(results), "passed": passed, "results": results}, indent=2))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
