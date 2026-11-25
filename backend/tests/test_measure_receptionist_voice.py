"""The VR1 measurement script's arithmetic and its free run (ADR 0038)."""

from decimal import Decimal
from pathlib import Path

import pytest

from scripts import measure_receptionist_voice as m


def _turn() -> m.Turn:
    return m.Turn(
        name="q1",
        language="te",
        voice="recording",
        wer=0.1,
        cer=0.05,
        hear_s=1.0,
        think_s=2.0,
        speak_s=0.5,
        visitor_seconds=6.0,
        reply_chars=100,
    )


def test_the_wait_is_hearing_plus_thinking_plus_speaking() -> None:
    assert _turn().delay_s == pytest.approx(3.5)


def test_cost_uses_the_given_prices_and_exact_decimals() -> None:
    cost = m.turn_cost(_turn(), stt_per_minute=Decimal("0.6"), tts_per_1k_chars=Decimal("1.5"))
    assert cost == Decimal("0.06") + Decimal("0.15")  # 6 s at 0.6 a minute, 100 chars at 1.5 a 1k
    assert m.call_cost(cost) == cost * 12


def test_samples_need_a_language_in_the_name(tmp_path: Path) -> None:
    (tmp_path / "a.hi.txt").write_text("नमस्ते", encoding="utf-8")
    (tmp_path / "a.hi.m4a").write_bytes(b"x")
    (tmp_path / "b.te.txt").write_text("నమస్కారం", encoding="utf-8")
    (tmp_path / "c.fr.txt").write_text("bonjour", encoding="utf-8")
    (tmp_path / "plain.txt").write_text("x", encoding="utf-8")
    found = {(i.name, i.language, i.audio is not None) for i in m.find_items(tmp_path)}
    assert found == {("a", "hi", True), ("b", "te", False)}


def test_the_scripted_run_is_free_and_prints_the_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "q1.hi.txt").write_text("नमस्ते मुझे फ्लैट चाहिए", encoding="utf-8")
    assert m.main([str(tmp_path), "--engine", "scripted", "--synthesize"]) == 0
    out = capsys.readouterr().out
    assert "Hindi" in out
    assert "synthetic" in out
    assert "optimistic" in out


def test_a_sample_without_a_recording_needs_the_synthesize_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "q1.en.txt").write_text("hello", encoding="utf-8")
    assert m.main([str(tmp_path), "--engine", "scripted"]) == 1
    assert "no recording" in capsys.readouterr().out


def test_the_real_engine_refuses_without_the_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CRM_RUN_LIVE_EVALS", raising=False)
    (tmp_path / "q1.en.txt").write_text("hello", encoding="utf-8")
    assert m.main([str(tmp_path), "--engine", "real", "--synthesize"]) == 2
    assert "Refusing to spend money" in capsys.readouterr().out
