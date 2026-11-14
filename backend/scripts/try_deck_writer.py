"""Try the deck writer ONCE with a real model (ADR 0032 Amendment A, PD7).

    set CRM_RUN_LIVE_EVALS=1
    python -m scripts.try_deck_writer [--provider deepseek|anthropic] [--tenant alpha-demo]

It plays in the development database as a sales manager, on the first approved quote it finds, with
the deck writer switched on inside ONE transaction that is rolled back at the end: nothing is kept,
no proposal, no usage row, no audit entry. It prints what the model wrote and what the safety check
and the slide rules made of it. One call costs a fraction of a cent; it still needs the same guard
as the paid evaluation runs (``CRM_RUN_LIVE_EVALS=1``) and the provider's key in the environment.
"""

import argparse
import os
import sys
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from agent_evals.world import World, WorldError
from app.core.config import Settings
from app.core.db import create_db_engine
from app.modules.agents import api as agents_api
from app.modules.assistant.llm import build_chat_model
from app.modules.proposal_decks import rules, writer
from app.modules.quotes.models import Quote

GUARD = "CRM_RUN_LIVE_EVALS"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.try_deck_writer")
    parser.add_argument("--provider", choices=("deepseek", "anthropic"), default="deepseek")
    parser.add_argument("--tenant", default="alpha-demo")
    args = parser.parse_args(argv)
    if os.environ.get(GUARD) != "1":
        print(f"This calls a paid model. Set {GUARD}=1 to allow it.")
        return 2
    settings = Settings()
    model = build_chat_model(settings.model_copy(update={"ai_provider": args.provider}))
    if not model.available:
        print(f"The {args.provider} model is not configured (no API key); nothing was run.")
        return 2
    factory = sessionmaker(bind=create_db_engine(settings), expire_on_commit=False)
    with factory() as session:
        try:
            world = World(session, settings, args.tenant, "beta-demo")
            admin, manager = world.principal("tenant_admin"), world.principal("sales_manager")
            tenant = manager.tenant_id
            if tenant is None:
                raise WorldError("the sales manager has no organisation")
            world.bind(manager)
            quote_id = session.scalar(
                select(Quote.id)
                .where(Quote.tenant_id == manager.tenant_id, Quote.status.in_(("approved", "sent")))
                .limit(1)
            )
            if quote_id is None:
                print("No approved quote found in the development data.")
                return 2
            ai_limits = agents_api.Limits.from_settings(settings)
            world.bind(admin)
            current = agents_api.effective(
                session, tenant, writer.AGENT, ai_limits, datetime.now(UTC)
            )
            agents_api.update_settings(
                session,
                admin,
                writer.AGENT,
                limits=ai_limits,
                now=datetime.now(UTC),
                version=current.version,
                enabled=True,
            )
            world.bind(manager)
            result = writer.draft_summary(
                session,
                manager,
                model,
                quote_id,
                limits=writer.Limits.from_settings(settings),
                ai_limits=ai_limits,
            )
            print(f"outcome: {result.outcome}")
            if result.blocked_message:
                print(f"blocked by the safety check: {result.blocked_message}")
            if result.proposal is not None:
                text = str(result.proposal.payload.get("text", ""))
                print(f"reason:  {result.proposal.reason}")
                print(f"words:   {len(text.split())} (the slide allows {rules.SUMMARY_MAX_WORDS})")
                print(f"text:\n{text}")
            used = agents_api.effective(session, tenant, writer.AGENT, ai_limits, datetime.now(UTC))
            print(f"tokens used this month (rolled back afterwards): {used.used_tokens}")
        except WorldError as error:
            print(f"Cannot play: {error}")
            return 2
        finally:
            session.rollback()  # the development data stays exactly as it was
    return 0


if __name__ == "__main__":
    sys.exit(main())
