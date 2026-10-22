"""Weekly knowledge-gaps report (R6.1). Read-only; prints markdown, optionally JSON.

python -m scripts.rag_gaps_report
python -m scripts.rag_gaps_report --days 7 --json gaps.json
"""

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app import model_registry as _model_registry  # noqa: F401
from app.core.config import get_settings
from app.core.db import bind_tenant, create_db_engine, create_session_factory
from app.modules.identity.models import Tenant
from app.modules.knowledge.gaps import build_gaps_report
from app.modules.knowledge.models import RagFeedback, RagQuery


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    since = datetime.now(UTC) - timedelta(days=args.days)
    settings = get_settings()
    engine = create_db_engine(settings)
    factory = create_session_factory(engine)
    queries: list[dict[str, object]] = []
    feedback: list[dict[str, object]] = []
    try:
        with factory() as session:
            for tenant in session.scalars(select(Tenant)).all():
                bind_tenant(session, tenant.id)
                for row in session.scalars(
                    select(RagQuery).where(
                        RagQuery.tenant_id == tenant.id, RagQuery.created_at >= since
                    )
                ).all():
                    queries.append(
                        {
                            "id": row.id,
                            "question": row.question,
                            "answer": row.answer,
                            "sources": row.sources,
                            "surface": row.surface,
                        }
                    )
                for vote in session.scalars(
                    select(RagFeedback).where(
                        RagFeedback.tenant_id == tenant.id, RagFeedback.created_at >= since
                    )
                ).all():
                    feedback.append({"query_id": vote.query_id, "helpful": vote.helpful})
    finally:
        engine.dispose()
    report = build_gaps_report(queries, feedback)
    print(f"# Knowledge gaps (last {args.days} days)")
    print(json.dumps(report, indent=2))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
