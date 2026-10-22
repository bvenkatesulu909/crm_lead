"""Scored end-to-end Leads answer eval (uses the live DB + configured LLM).

python -m scripts.eval_leads_answer
"""

import json
import re
import sys

from sqlalchemy import select

from app import model_registry as _model_registry  # noqa: F401
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import get_settings
from app.core.db import create_db_engine, create_session_factory
from app.modules.assistant.llm import build_chat_model
from app.modules.assistant.staff_service import answer
from app.modules.identity.models import Tenant, User
from app.modules.leads import api as leads_api

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def main() -> int:
    settings = get_settings()
    engine = create_db_engine(settings)
    factory = create_session_factory(engine)
    with factory() as session:
        tenant = session.scalars(select(Tenant).where(Tenant.slug == "alpha-demo")).one()
        user = session.scalars(
            select(User).where(
                User.tenant_id == tenant.id, User.email == "admin@alpha.example.test"
            )
        ).one()
        principal = Principal(
            subject="leads-eval",
            issuer="eval",
            user_type="staff",
            roles=frozenset(),
            permissions=frozenset({Permission.LEAD_READ_ALL, Permission.ACCOUNT_READ_ALL}),
            user_id=user.id,
            tenant_id=tenant.id,
        )
        leads = leads_api.search_leads(session, principal, limit=10)
        if not leads:
            print(json.dumps({"score": 0, "error": "no leads"}))
            return 1
        model = build_chat_model(settings)
        text, _, links = answer(
            session,
            principal,
            model,
            question=(
                "List these first 10 leads with their exact name, company, email and status. "
                "Use only the retrieved records."
            ),
        )
    lowered = text.lower()
    name_hits = sum(1 for lead in leads if lead["name"].lower() in lowered)
    company_hits = sum(
        1
        for lead in leads
        if (lead["company"] or "").lower() and (lead["company"] or "").lower() in lowered
    )
    email_hits = sum(1 for lead in leads if lead["email"] and lead["email"].lower() in lowered)
    expected_emails = {lead["email"].lower() for lead in leads if lead["email"]}
    invented = sorted(set(EMAIL.findall(text)) - expected_emails)
    possible = (
        len(leads)
        + sum(1 for lead in leads if lead["company"])
        + sum(1 for lead in leads if lead["email"])
    )
    score = round((name_hits + company_hits + email_hits) / possible, 3) if possible else 0.0
    report = {
        "leads": len(leads),
        "name_hits": name_hits,
        "company_hits": company_hits,
        "email_hits": email_hits,
        "invented_emails": invented,
        "links": links,
        "score": score,
        "answer_chars": len(text),
    }
    print(json.dumps(report, indent=2))
    engine.dispose()
    return 0 if score >= 0.6 and not invented else 1


if __name__ == "__main__":
    sys.exit(main())
