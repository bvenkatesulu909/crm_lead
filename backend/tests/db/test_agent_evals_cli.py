# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""The evaluation command line against the real test database (BP-10, step EV5).

The command-line path (``agent_evals.cli.main``) plays the cases in the test world exactly as it
would play them on the development data, and writes a scorecard. Real-model runs are exercised
with a stand-in "real" model: no money is ever spent in a test.
"""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from agent_evals import cli
from agent_evals.cases import load_cases
from agent_evals.suite import CASES_DIR, estimate_cost, run_suite
from agent_evals.world import World as EvalWorld
from app.modules.assistant.llm import ModelReply
from tests.db.agent_eval_support import eval_test_settings, eval_world
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name


class SharedSession:
    """A 'factory' that hands the test's own session (rolled back by the test) to the CLI."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def __call__(self) -> "SharedSession":
        return self

    def __enter__(self) -> Session:
        return self.session

    def __exit__(self, *exc: object) -> None:
        return None


class Silent:
    """A model that never calls a tool and answers with a fixed sentence."""

    available = True

    def __init__(self, text: str = "I could not find that.") -> None:
        self.text = text
        self.calls = 0

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        self.calls += 1
        return ModelReply(self.text)


def run_cli(session: Session, argv: list[str], **kwargs: Any) -> tuple[int, str]:
    lines: list[str] = []
    code = cli.main(
        [*argv, "--tenant", "alpha-quotes", "--other-tenant", "beta-quotes"],
        settings=eval_test_settings(),
        factory=SharedSession(session),  # type: ignore[arg-type]
        out=lines.append,
        **kwargs,
    )
    return code, "\n".join(lines)


def test_the_scripted_run_passes_every_case_and_writes_a_scorecard(
    db_session: Session, world: World, tmp_path: Path
) -> None:
    # In CI the scorecard and the table go where the job summary step looks for them.
    target = (
        Path(os.environ["AGENT_EVAL_OUT_DIR"]) if os.environ.get("AGENT_EVAL_OUT_DIR") else tmp_path
    )
    target.mkdir(parents=True, exist_ok=True)
    out = target / "scorecard.json"
    code, text = run_cli(
        db_session,
        ["--provider", "fake", "--out", str(out), "--summary", str(target / "summary.md")],
    )
    assert code == 0, text
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["provider"] == "fake"
    assert data["totals"]["failed"] == 0
    assert data["totals"]["total"] >= 45  # 34 agent cases + the cited-answer cases
    assert "All cases passed" in text


def test_the_same_run_twice_gives_the_same_scorecard(
    db_session: Session, world: World, tmp_path: Path
) -> None:
    one, two = tmp_path / "one.json", tmp_path / "two.json"
    run_cli(db_session, ["--provider", "fake", "--suite", "public_chat", "--out", str(one)])
    run_cli(db_session, ["--provider", "fake", "--suite", "public_chat", "--out", str(two)])
    assert one.read_text(encoding="utf-8") == two.read_text(encoding="utf-8")


def test_one_suite_and_one_case_can_be_chosen(db_session: Session, world: World) -> None:
    code, text = run_cli(
        db_session, ["--provider", "fake", "--suite", "staff_assistant", "--only", "staff-fourth"]
    )
    assert code == 0 and "staff-fourth-proposal-refused" in text
    assert "public-" not in text


def test_nothing_selected_is_not_a_pass(db_session: Session, world: World) -> None:
    code, text = run_cli(db_session, ["--provider", "fake", "--only", "no-such-case-anywhere"])
    assert code == 2 and "not a pass" in text


def test_the_run_leaves_no_trace_in_the_database(db_session: Session, world: World) -> None:
    env = eval_world(db_session, world)
    before = env.snapshot()
    run_cli(db_session, ["--provider", "fake", "--suite", "staff_assistant"])
    after = eval_world(db_session, world).snapshot()
    assert after == before


def test_a_world_without_the_needed_people_is_explained(db_session: Session, world: World) -> None:
    lines: list[str] = []
    code = cli.main(
        ["--provider", "fake", "--tenant", "no-such-organisation"],
        settings=eval_test_settings(),
        factory=SharedSession(db_session),  # type: ignore[arg-type]
        out=lines.append,
    )
    assert code == 2 and "no-such-organisation" in "\n".join(lines)


# --- a real model (stood in for by a fake one: no money is spent) ---------------------------------


def test_a_real_model_run_plays_only_live_cases_and_is_a_report(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(cli.LIVE_GUARD, "1")
    silent = Silent()
    out = tmp_path / "deepseek.json"
    code, text = run_cli(
        db_session,
        ["--provider", "deepseek", "--suite", "staff_assistant", "--out", str(out)],
        model_builder=lambda settings, provider: silent,
    )
    live = [c for c in load_cases(CASES_DIR) if c.agent == "staff_assistant" and c.live]
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["totals"]["total"] == len(live) and silent.calls >= len(live)
    assert data["provider"] == "deepseek"
    # A model that does nothing fails the cases that expect tools - but a report is not a gate.
    assert data["totals"]["failed"] > 0
    assert code == 0, text


def test_a_regression_against_the_baseline_exits_one(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(cli.LIVE_GUARD, "1")
    good = tmp_path / "good.json"
    run_cli(db_session, ["--provider", "fake", "--suite", "staff_assistant", "--out", str(good)])
    code, text = run_cli(
        db_session,
        ["--provider", "deepseek", "--suite", "staff_assistant", "--baseline", str(good)],
        model_builder=lambda settings, provider: Silent(),
    )
    assert code == 1 and "REGRESSION" in text


def test_a_model_without_a_key_runs_nothing(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    class NoKey:
        available = False

    monkeypatch.setenv(cli.LIVE_GUARD, "1")
    code, text = run_cli(
        db_session,
        ["--provider", "deepseek"],
        model_builder=lambda settings, provider: NoKey(),
    )
    assert code == 2 and "not configured" in text


def test_a_model_that_crashes_fails_the_case_and_the_run_goes_on(
    db_session: Session, world: World
) -> None:
    class Crash:
        available = True

        def reply(self, **_: Any) -> ModelReply:
            raise RuntimeError("provider is down")

    cards = run_suite(
        db_session,
        eval_world(db_session, world),
        provider="deepseek",
        model=Crash(),
        suites=("public_chat",),
    )
    results = cards["public_chat"].results
    assert results and all(not r.passed for r in results)


def test_the_estimate_is_positive_and_scales_with_the_prices(
    db_session: Session, world: World
) -> None:
    env: EvalWorld = eval_world(db_session, world)
    cheap = estimate_cost(db_session, env, price_in_per_million=0.1, price_out_per_million=0.1)
    dear = estimate_cost(db_session, env, price_in_per_million=1.0, price_out_per_million=1.0)
    assert cheap.cases > 0 and cheap.input_tokens > 0 and cheap.output_tokens > 0
    assert cheap.input_tokens == dear.input_tokens
    assert dear.total_usd == pytest.approx(cheap.total_usd * 10)


def test_the_estimate_command_prints_a_dollar_figure_and_calls_no_model(
    db_session: Session, world: World
) -> None:
    def must_not_be_built(settings: Any, provider: str) -> Any:
        raise AssertionError("an estimate must not build a model")

    code, text = run_cli(
        db_session, ["--provider", "deepseek", "--estimate"], model_builder=must_not_be_built
    )
    assert code == 0 and "$" in text and "cases" in text


def test_a_colleague_whose_id_the_guardrail_refuses_gets_a_stand_in(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.auth.rbac import Role
    from app.modules.assistant import guardrails
    from app.modules.assistant.guardrails import InputDecision

    env = eval_world(db_session, world)
    colleague = env.other_agent()
    real = guardrails.inspect_input

    def picky(text: str) -> InputDecision:
        return InputDecision(False, "no") if text == str(colleague.id) else real(text)

    monkeypatch.setattr(guardrails, "inspect_input", picky)
    chosen = env._mentionable(colleague, Role.SALES_AGENT)
    assert chosen != colleague.id
    stand_in = env._person(env.tenant_id, "staff", Role.SALES_AGENT.value, 2)
    assert stand_in.id == chosen and stand_in.roles == ["sales_agent"]
    # An id the guardrail accepts is simply used.
    monkeypatch.undo()
    assert env._mentionable(colleague, Role.SALES_AGENT) == colleague.id
