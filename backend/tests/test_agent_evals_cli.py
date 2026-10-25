"""The evaluation command line that needs no database (BP-10, step EV5)."""

import json
from pathlib import Path

import pytest

from agent_evals import cli
from agent_evals.scoring import CaseResult, Check, build_scorecard
from agent_evals.suite import Estimate


def card_file(tmp_path: Path, *, failing: bool = False) -> Path:
    results = [
        CaseResult("a-case", "staff_assistant", [Check("tools", True)]),
        CaseResult(
            "b-case", "public_chat", [Check("tools", not failing, "boom" if failing else "")]
        ),
    ]
    path = tmp_path / "card.json"
    path.write_text(
        build_scorecard(results, provider="fake", dataset_sha256="ab" * 32).to_json(),
        encoding="utf-8",
    )
    return path


def run(argv: list[str], **kwargs: object) -> tuple[int, str]:
    lines: list[str] = []
    code = cli.main(argv, out=lines.append, **kwargs)  # type: ignore[arg-type]
    return code, "\n".join(lines)


def test_defaults_are_the_free_scripted_run() -> None:
    args = cli.parse_args([])
    assert args.provider == "fake" and not args.estimate and args.suite is None


def test_an_unknown_provider_is_refused() -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["--provider", "gpt"])


def test_a_saved_scorecard_is_rendered_without_a_database(tmp_path: Path) -> None:
    code, text = run(["--render", str(card_file(tmp_path))])
    assert code == 0
    assert "| staff_assistant | 1 | 1 | 0 |" in text and "All cases passed" in text


def test_a_failing_scorecard_names_the_failed_case(tmp_path: Path) -> None:
    _, text = run(["--render", str(card_file(tmp_path, failing=True))])
    assert "b-case" in text and "boom" in text


def test_a_file_that_is_not_a_scorecard_is_refused_clearly(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"hello": 1}), encoding="utf-8")
    code, text = run(["--render", str(bad)])
    assert code == 2 and "not a scorecard" in text


def test_a_missing_file_is_refused_clearly(tmp_path: Path) -> None:
    code, text = run(["--render", str(tmp_path / "nope.json")])
    assert code == 2 and "Cannot read" in text


@pytest.mark.parametrize("provider", ["deepseek", "anthropic"])
def test_a_paid_provider_needs_the_money_guard(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(cli.LIVE_GUARD, raising=False)
    code, text = run(["--provider", provider])
    assert code == 2 and cli.LIVE_GUARD in text and "--estimate" in text


def test_the_guard_must_be_exactly_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cli.LIVE_GUARD, "yes")
    code, _ = run(["--provider", "deepseek"])
    assert code == 2


def test_the_estimate_math() -> None:
    guess = Estimate(
        cases=10,
        model_calls=40,
        input_tokens=2_000_000,
        output_tokens=500_000,
        input_usd=2_000_000 / 1e6 * 0.28,
        output_usd=500_000 / 1e6 * 0.42,
    )
    assert round(guess.total_usd, 4) == round(0.56 + 0.21, 4)


def test_a_record_id_that_looks_like_a_card_number_is_not_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid

    from agent_evals import world

    looks_like_a_card = uuid.UUID("12345678-1234-4123-8123-123456789012")
    fine = uuid.UUID("deadbeef-dead-4bee-8fed-deadbeefdead")
    ids = iter([looks_like_a_card, looks_like_a_card, fine])
    monkeypatch.setattr(uuid, "uuid4", lambda: next(ids))
    assert world.clean_id() == fine
