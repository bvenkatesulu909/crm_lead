"""The command line behind ``python -m scripts.eval_agents`` (BP-10, step EV5).

    python -m scripts.eval_agents --provider fake            # every case, scripted: the CI gate
    python -m scripts.eval_agents --provider deepseek --estimate
    set CRM_RUN_LIVE_EVALS=1
    python -m scripts.eval_agents --provider deepseek --out evals\\baseline\\deepseek.json
    python -m scripts.eval_agents --render evals\\baseline\\deepseek.json

Exit codes: 0 fine, 1 a failure the run was asked to judge, 2 could not run / bad request.

* ``fake``: the scripted model plays every case. Any failed case, forbidden tool or false
  "done" claim makes the exit code 1 - the same rule the pytest gate uses.
* ``deepseek`` / ``anthropic``: a real model plays the ``live`` cases. This costs money, so it
  needs ``CRM_RUN_LIVE_EVALS=1``. The result is a report: the exit code is 1 only if
  ``--baseline`` is given and something got worse than that file.

Everything runs inside one database transaction that is rolled back at the end: the development
data is read, never changed.
"""

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from agent_evals.report import (
    compare,
    load_baseline,
    merge_scorecards,
    render_markdown,
    render_summary,
)
from agent_evals.scoring import Scorecard
from agent_evals.suite import ALL_SUITES, estimate_cost, run_suite
from agent_evals.world import World, WorldError
from app.core.config import Settings
from app.modules.assistant.llm import ChatModel

PROVIDERS = ("fake", "deepseek", "anthropic")
LIVE_GUARD = "CRM_RUN_LIVE_EVALS"

# Published list prices in US dollars per million tokens. Prices change: check the provider's page
# and override with --price-in / --price-out before relying on a number.
DEFAULT_PRICES = {"deepseek": (0.28, 0.42), "anthropic": (3.0, 15.0)}

Out = Callable[[str], None]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.eval_agents",
        description="Play the agent evaluation cases and write a scorecard.",
    )
    parser.add_argument("--provider", choices=PROVIDERS, default="fake")
    parser.add_argument("--tenant", default="alpha-demo", help="organisation to play in")
    parser.add_argument(
        "--other-tenant", default="beta-demo", help="second organisation (isolation cases)"
    )
    parser.add_argument(
        "--suite", action="append", choices=ALL_SUITES, help="only this suite (repeatable)"
    )
    parser.add_argument("--only", help="only cases whose id contains this text")
    parser.add_argument("--out", type=Path, help="write the scorecard (JSON) here")
    parser.add_argument("--baseline", type=Path, help="compare with this earlier scorecard")
    parser.add_argument("--summary", type=Path, help="write the Markdown table here")
    parser.add_argument("--render", type=Path, help="print a scorecard file as a table and stop")
    parser.add_argument("--estimate", action="store_true", help="print the cost estimate and stop")
    parser.add_argument("--price-in", type=float, help="USD per million input tokens")
    parser.add_argument("--price-out", type=float, help="USD per million output tokens")
    return parser.parse_args(argv)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _render_file(path: Path, out: Out) -> int:
    try:
        card = _scorecard_from_file(path)
    except (OSError, ValueError) as error:
        out(f"Cannot read {path}: {error}")
        return 2
    out(card)
    return 0


def _scorecard_from_file(path: Path) -> str:
    """A saved scorecard as the Markdown table (reads the file, runs nothing)."""
    import json

    from agent_evals.scoring import CaseResult, Check, build_scorecard

    data = json.loads(_read(path))
    try:
        results = [
            CaseResult(
                r["case_id"],
                r["agent"],
                [Check(c["name"], bool(c["passed"]), c.get("detail", "")) for c in r["checks"]],
            )
            for r in data["results"]
        ]
        card = build_scorecard(
            results, provider=str(data["provider"]), dataset_sha256=str(data["dataset_sha256"])
        )
    except (KeyError, TypeError) as error:
        raise ValueError(
            f"this is not a scorecard file ({type(error).__name__}: {error})"
        ) from error
    return render_markdown(card)


def main(
    argv: list[str] | None = None,
    *,
    settings: Settings | None = None,
    factory: "sessionmaker[Session] | None" = None,
    model_builder: Callable[[Settings, str], ChatModel] | None = None,
    out: Out = print,
) -> int:
    args = parse_args(argv)
    if args.render:
        return _render_file(args.render, out)

    live = args.provider != "fake"
    if live and not args.estimate and os.environ.get(LIVE_GUARD) != "1":
        out(
            f"Refusing to spend money: set {LIVE_GUARD}=1 to run a real model "
            "(use --estimate first to see the cost)."
        )
        return 2

    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()
    if factory is None:
        from app.core.db import create_db_engine, create_session_factory

        factory = create_session_factory(create_db_engine(settings))

    model: ChatModel | None = None
    if live and not args.estimate:
        build = model_builder or _build_model
        model = build(settings, args.provider)
        if not getattr(model, "available", True):
            out(f"The {args.provider} model is not configured (no API key); nothing was run.")
            return 2

    suites = tuple(args.suite) if args.suite else ALL_SUITES
    baseline = None
    if args.baseline:
        try:
            baseline = load_baseline(_read(args.baseline))
        except (OSError, ValueError) as error:
            out(f"Cannot read the baseline {args.baseline}: {error}")
            return 2

    with factory() as session:
        try:
            world = World(session, settings, args.tenant, args.other_tenant)
            if args.estimate:
                return _estimate(session, world, args, out)
            cards = run_suite(
                session,
                world,
                provider=args.provider,
                model=model,
                suites=suites,
                only=args.only,
                progress=out,
            )
        except WorldError as error:
            out(f"Cannot play the cases: {error}")
            return 2
        finally:
            session.rollback()  # the development data stays exactly as it was

    if not cards:
        out("No cases were selected - nothing ran. That is not a pass.")
        return 2
    return _report(cards, args, baseline, out)


def _build_model(settings: Settings, provider: str) -> ChatModel:
    from app.modules.assistant.llm import build_chat_model

    return build_chat_model(settings.model_copy(update={"ai_provider": provider}))


def _estimate(session: Session, world: World, args: argparse.Namespace, out: Out) -> int:
    if args.provider == "fake":
        out("The fake provider is free: there is nothing to estimate.")
        return 0
    default_in, default_out = DEFAULT_PRICES[args.provider]
    price_in = args.price_in if args.price_in is not None else default_in
    price_out = args.price_out if args.price_out is not None else default_out
    guess = estimate_cost(
        session,
        world,
        price_in_per_million=price_in,
        price_out_per_million=price_out,
        only=args.only,
    )
    out(
        f"Cost estimate for {args.provider}: {guess.cases} cases, about {guess.model_calls} model "
        f"calls, {guess.input_tokens:,} input + {guess.output_tokens:,} output tokens.\n"
        f"At ${price_in}/M in and ${price_out}/M out that is about ${guess.total_usd:.2f}. "
        "An estimate, not a quote: check the prices and your balance."
    )
    return 0


def _report(
    cards: dict[str, Scorecard], args: argparse.Namespace, baseline: object, out: Out
) -> int:
    merged = merge_scorecards(list(cards.values()))
    comparison = compare(merged, baseline) if baseline is not None else None  # type: ignore[arg-type]
    table = render_summary(cards) if len(cards) > 1 else render_markdown(merged)
    if comparison is not None:
        table += "\n" + render_markdown(merged, comparison, title="Overall")
    out(table)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(merged.to_json() + "\n", encoding="utf-8", newline="\n")
        out(f"Scorecard written to {args.out}")
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(table, encoding="utf-8", newline="\n")
    if args.provider == "fake":
        return 0 if merged.all_passed else 1
    return 1 if comparison is not None and not comparison.ok else 0


if __name__ == "__main__":
    sys.exit(main())
