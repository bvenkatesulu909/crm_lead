"""Print the deal risk honesty check for one organisation (ADR 0037, DR6).

    python -m scripts.deal_risk_backtest [--tenant alpha-demo] [--days 365]

For every deal that closed in the last ``--days`` days it takes the newest risk forecast made while
the deal was still open and compares it with what happened (won on time, won late, lost). It reads
everything as the organisation's Automation identity, inside ONE transaction that is rolled back:
nothing is written. No model, no network.

The same figures are in the CRM under Reports -> "Deal risk: forecast vs. outcome".
"""

import argparse
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.db import bind_tenant, create_db_engine
from app.modules.deal_risk import api as deal_risk_api
from app.modules.deal_risk.service import LEVEL_LABELS
from app.modules.identity import api as identity_api
from app.modules.identity.models import Tenant


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.deal_risk_backtest")
    parser.add_argument("--tenant", default="alpha-demo", help="the organisation's short name")
    parser.add_argument("--days", type=int, default=365, help="deals closed in the last N days")
    args = parser.parse_args(argv)
    if not 1 <= args.days <= 3 * 366:
        print("--days must be between 1 and 1098.")
        return 2
    settings = Settings()
    factory = sessionmaker(bind=create_db_engine(settings), expire_on_commit=False)
    with factory() as session:
        try:
            tenant_id = session.scalar(select(Tenant.id).where(Tenant.slug == args.tenant))
            if tenant_id is None:
                print(f"No organisation called {args.tenant!r}.")
                return 2
            bind_tenant(session, tenant_id)
            robot = identity_api.automation_principal(session, tenant_id)
            identity_api.bind_reader(session, robot)
            end = datetime.now(UTC)
            summary = deal_risk_api.backtest_summary(
                session, robot, end - timedelta(days=args.days), end
            )
        finally:
            session.rollback()  # read-only: never keep anything
    print(f"Deal risk forecast vs. outcome - {args.tenant}, last {args.days} days")
    print(f"{'Last forecast before closing':<30}{'Deals':>7}{'On time':>9}{'Late':>6}"
          f"{'Lost':>6}{'Badly %':>9}")  # fmt: skip
    for row in summary.rows:
        rate = "-" if row.badly_percent is None else f"{row.badly_percent}"
        print(f"{LEVEL_LABELS[row.level]:<30}{row.deals:>7}{row.won_on_time:>9}{row.won_late:>6}"
              f"{row.lost:>6}{rate:>9}")  # fmt: skip
    print(summary.verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
