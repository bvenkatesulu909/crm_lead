"""Golden + live scored eval for staff quote/order/invoice answers."""

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
from app.modules.assistant.llm import build_chat_model
from app.modules.assistant.staff_service import answer, retrieve_context
from app.modules.identity.models import Tenant, User

CASES = Path(__file__).resolve().parents[1] / "evals" / "staff" / "quote_order_invoice_cases.json"
PREFIX = {"quotes": "/quotes", "orders": "/orders", "invoices": "/invoices"}


def main() -> int:
    settings = get_settings()
    engine = create_db_engine(settings)
    factory = create_session_factory(engine)
    model = build_chat_model(settings)
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
            subject="module-eval",
            issuer="eval",
            user_type="staff",
            roles=frozenset(),
            permissions=frozenset(
                {Permission.QUOTE_READ_ALL, Permission.ORDER_READ_ALL, Permission.INVOICE_READ_ALL}
            ),
            user_id=user.id,
            tenant_id=tenant.id,
        )
        for case in cases:
            decision = guardrails.inspect_input(case["question"])
            if case.get("expect_guardrail"):
                results.append(
                    {"id": case["id"], "pass": not decision.allowed, "kind": "guardrail"}
                )
                continue
            if not decision.allowed:
                results.append({"id": case["id"], "pass": False, "kind": "blocked"})
                continue
            rows, _ = retrieve_context(session, principal, case["question"])
            prefix = PREFIX[case["expected_module"]]
            retrieval_ok = bool(rows) and all(
                str(r.get("link", "")).startswith(prefix) for r in rows
            )
            tenant_ok = not case.get("expect_no_other_tenant") or "beta-demo" not in json.dumps(
                rows
            )
            if case.get("expect_no_other_tenant"):
                results.append(
                    {"id": case["id"], "pass": retrieval_ok and tenant_ok, "rows": len(rows)}
                )
                continue
            text, _, _ = answer(session, principal, model, question=case["question"])
            sample = rows[:5]
            fields = [
                field
                for row in sample
                for field in case["expected_fields"]
                if row.get(field) is not None
            ]
            hits = sum(
                1
                for row in sample
                for field in case["expected_fields"]
                if row.get(field) is not None and str(row[field]) in text
            )
            score = round(hits / len(fields), 3) if fields else 0.0
            results.append(
                {
                    "id": case["id"],
                    "pass": retrieval_ok and score >= 0.6,
                    "rows": len(rows),
                    "score": score,
                    "chars": len(text),
                }
            )
    engine.dispose()
    passed = sum(1 for r in results if r["pass"])
    print(json.dumps({"cases": len(results), "passed": passed, "results": results}, indent=2))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
