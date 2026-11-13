"""The trial script's arithmetic (ADR 0030, CA3): error rates and the way samples are found."""

from pathlib import Path

import pytest

from scripts.measure_call_transcription import (
    Row,
    char_error_rate,
    find_samples,
    normalize,
    render,
    word_error_rate,
)


def test_normalizing_ignores_case_punctuation_and_spacing() -> None:
    assert normalize("  Hello,   WORLD! ") == "hello world"
    assert normalize("नमस्ते, दुनिया।") == "नमस्ते दुनिया"  # the Hindi danda is punctuation
    assert normalize("నమస్కారం. నాకు  ఫ్లాట్ కావాలి") == "నమస్కారం నాకు ఫ్లాట్ కావాలి"


def test_a_perfect_transcript_has_no_errors() -> None:
    assert word_error_rate("the flat is ready", "The flat is ready.") == 0.0
    assert char_error_rate("the flat is ready", "The flat is ready.") == 0.0


def test_word_errors_are_counted_against_the_words_said() -> None:
    assert word_error_rate("one two three four", "one two three five") == 0.25  # one wrong
    assert word_error_rate("one two three four", "one three four") == 0.25  # one missing
    assert word_error_rate("one two", "one two three") == 0.5  # one extra
    assert word_error_rate("one two", "completely different") == 1.0
    assert word_error_rate("one", "a b c d") == 4.0  # can exceed 100 %


def test_the_character_rate_is_finer_than_the_word_rate() -> None:
    assert char_error_rate("hyderabad", "hydrabad") == pytest.approx(1 / 9)
    assert word_error_rate("hyderabad", "hydrabad") == 1.0


def test_nothing_said_and_nothing_heard_is_perfect_but_a_guess_is_not() -> None:
    assert word_error_rate("", "") == 0.0 and word_error_rate("", "something") == 1.0
    assert char_error_rate("", "") == 0.0 and char_error_rate("", "x") == 1.0
    assert word_error_rate("something", "") == 1.0


def test_samples_need_a_language_a_known_audio_type_and_a_reference(tmp_path: Path) -> None:
    for name in (
        "a.hi.mp3",
        "a.hi.txt",  # a good pair
        "b.te.m4a",  # no reference
        "c.fr.mp3",
        "c.fr.txt",  # unknown language
        "d.en.pdf",
        "d.en.txt",  # not audio
        "e.mp3",
        "e.txt",  # no language
    ):
        (tmp_path / name).write_bytes(b"x")
    found = find_samples(tmp_path)
    assert [(s.name, s.language, s.audio.name) for s in found] == [("a", "hi", "a.hi.mp3")]


def test_the_table_shows_each_sample_and_the_averages_per_language() -> None:
    rows = [
        Row("one", "hi", "cleaned", 0.25, 0.1, 2.0),
        Row("two", "hi", "cleaned", 0.75, 0.3, 4.0),
        Row("one", "hi", "original", 0.5, 0.2, 2.0),
    ]
    table = render(rows)
    assert "25.0 %" in table and "75.0 %" in table
    assert "average" in table and "50.0 %" in table  # the mean of 25 and 75 for cleaned
    assert table.count("average") == 2  # one per audio variant
