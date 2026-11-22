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


def test_spoken_digits_and_written_digits_score_the_same() -> None:
    assert m.numbers_as_digits("my number is nine eight seven six") == "my number is 9876"
    assert m.numbers_as_digits("मेरा number 9876543210 है") == "मेरा number 9876543210 है"
    assert m.numbers_as_digits("नौ आठ सात छह है") == "9876 है"
    assert m.numbers_as_digits("తొమ్మిది ఎనిమిది ఏడు ఆరు") == "9876"
    # A word between two runs keeps them apart (two numbers, not one).
    assert m.numbers_as_digits("one two and three") == "12 and 3"


# --- friendly handling of the three common mistakes ------------------------------------------


def test_a_text_file_saved_by_notepad_in_any_unicode_form_is_read(tmp_path: Path) -> None:
    words = "నమస్కారం నాకు ఫ్లాట్ కావాలి"
    plain = tmp_path / "a.te.txt"
    plain.write_bytes(words.encode("utf-8"))
    with_marker = tmp_path / "b.te.txt"
    with_marker.write_bytes(b"\xef\xbb\xbf" + words.encode("utf-8"))  # "UTF-8 with BOM"
    utf16 = tmp_path / "c.te.txt"
    utf16.write_bytes(b"\xff\xfe" + words.encode("utf-16-le"))  # Notepad's "Unicode"
    assert [m.read_reference(p) for p in (plain, with_marker, utf16)] == [words] * 3


def test_a_text_file_in_the_old_windows_code_page_is_refused_with_the_fix(tmp_path: Path) -> None:
    path = tmp_path / "q1.hi.txt"
    path.write_bytes("café résumé".encode("cp1252"))  # not valid UTF-8
    with pytest.raises(ValueError, match="not saved as UTF-8.*Save As"):
        m.read_reference(path)


def test_the_script_explains_a_bad_text_file_instead_of_scoring_garbage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "q1.hi.txt").write_bytes("café".encode("cp1252"))
    assert m.main([str(tmp_path), "--engine", "scripted", "--synthesize"]) == 2
    assert "q1.hi.txt is not saved as UTF-8" in capsys.readouterr().out


def test_diagnose_names_every_unusable_file_and_why(tmp_path: Path) -> None:
    (tmp_path / "ok.hi.txt").write_text("x", encoding="utf-8")
    (tmp_path / "ok.hi.m4a").write_bytes(b"x")  # a complete pair: no note
    (tmp_path / "lonely.te.m4a").write_bytes(b"x")  # recording without words
    (tmp_path / "words.en.txt").write_text("x", encoding="utf-8")  # words without recording
    (tmp_path / "q1.m4a").write_bytes(b"x")  # no language in the name
    (tmp_path / "q2.fr.txt").write_text("x", encoding="utf-8")  # a language we do not use
    (tmp_path / "notes.docx").write_bytes(b"x")  # not a sample at all: ignored
    notes = m.diagnose(tmp_path)
    assert len(notes) == 4
    joined = "\n".join(notes)
    assert "lonely.te.m4a: no text file lonely.te.txt" in joined
    assert "words.en.txt: no recording named words.en.m4a" in joined
    assert "q1.m4a: the name must look like q1.hi.m4a" in joined
    assert "q2.fr.txt: the name must look like" in joined
    assert "ok.hi" not in joined and "notes.docx" not in joined


def test_no_samples_found_says_what_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "q1.m4a").write_bytes(b"x")
    assert m.main([str(tmp_path), "--engine", "scripted"]) == 2
    out = capsys.readouterr().out
    assert "note: q1.m4a: the name must look like" in out
    assert "No samples found" in out and "q1.hi.txt" in out


def test_a_failure_line_shows_the_http_status_but_never_the_body() -> None:
    class Response:
        status_code = 401
        text = "SECRET-BODY-WITH-KEY"

    class HttpError(Exception):
        response = Response()

    try:
        try:
            raise HttpError("request failed: key=SECRET-KEY")
        except HttpError as inner:
            raise RuntimeError("Speech transcription is unavailable.") from inner
    except RuntimeError as outer:
        detail = m.describe_failure(outer)
    assert detail == "RuntimeError <- HttpError <- HTTP 401"
    assert "SECRET" not in detail
    assert m.describe_failure(ValueError("q1: no recording; add one or pass --synthesize")) == (
        "q1: no recording; add one or pass --synthesize"
    )


def test_the_http_status_is_found_deep_in_a_chain_of_causes() -> None:
    class Response:
        status_code = 429

    class HttpError(Exception):
        response = Response()

    try:
        try:
            try:
                raise HttpError("too many")
            except HttpError as deepest:
                raise OSError("connection layer") from deepest
        except OSError as middle:
            raise RuntimeError("Speech transcription is unavailable.") from middle
    except RuntimeError as outer:
        assert m.describe_failure(outer) == "RuntimeError <- OSError <- HttpError <- HTTP 429"
