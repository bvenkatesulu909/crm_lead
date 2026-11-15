"""Call recordings (ADR 0030, step CA1): the pure rules - no database, no network, no ffmpeg."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.calls import rules

MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64
MP3_FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 64
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32
OGG = b"OggS\x00\x02" + b"\x00" * 32
M4A = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00" + b"\x00" * 32
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 32
AMR = b"#!AMR\n" + b"\x00" * 32
PDF = b"%PDF-1.7 not audio"
SAMPLES = {"mp3": MP3, "wav": WAV, "ogg": OGG, "m4a": M4A, "webm": WEBM, "amr": AMR}


# --- the vocabulary -----------------------------------------------------------------------------


def test_three_languages_and_the_status_flow() -> None:
    assert rules.LANGUAGES == ("hi", "te", "en")
    assert rules.STATUSES == ("uploading", "queued", "processing", "ready", "failed", "expired")


def test_the_allowed_types() -> None:
    assert set(rules.AUDIO_TYPES) == {"mp3", "m4a", "wav", "ogg", "webm", "amr"}
    assert rules.AUDIO_TYPES["mp3"] == "audio/mpeg"
    assert rules.AUDIO_TYPES["m4a"] == "audio/mp4"


# --- file names ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("call.mp3", "call.mp3"),
        ("  Call 12 Nov.MP3 ", "Call 12 Nov.MP3"),
        ("C:\\Users\\rep\\calls\\buyer.wav", "buyer.wav"),
        ("/tmp/../etc/passwd.ogg", "passwd.ogg"),  # noqa: S108 - a name to clean, never opened
        ("కాల్ రికార్డింగ్.m4a", "కాల్ రికార్డింగ్.m4a"),
        ("call\x00\x1f.mp3", "call.mp3"),
    ],
)
def test_a_file_name_is_cleaned_to_a_plain_name(raw: str, clean: str) -> None:
    assert rules.clean_file_name(raw) == clean


@pytest.mark.parametrize(
    "bad", ["", "   ", ".mp3", "noextension", "x" * 200 + ".mp3", "a/", None, 5]
)
def test_a_name_with_nothing_usable_is_refused(bad: object) -> None:
    with pytest.raises(rules.CallRuleError):
        rules.clean_file_name(bad)


@pytest.mark.parametrize(
    ("name", "kind"),
    [("a.mp3", "mp3"), ("a.MP3", "mp3"), ("a.m4a", "m4a"), ("a.wav", "wav"), ("a.amr", "amr")],
)
def test_the_type_comes_from_the_extension(name: str, kind: str) -> None:
    assert rules.kind_of(name) == kind


@pytest.mark.parametrize("bad", ["a.exe", "a.pdf", "a.mp3.exe", "a.zip", "a.flac"])
def test_other_extensions_are_refused(bad: str) -> None:
    with pytest.raises(rules.CallRuleError, match="type"):
        rules.kind_of(bad)


# --- what is really inside ----------------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_each_type_is_recognised_by_its_first_bytes(kind: str) -> None:
    assert rules.looks_like(kind, SAMPLES[kind])


def test_an_mp3_may_start_with_a_frame_instead_of_a_tag() -> None:
    assert rules.looks_like("mp3", MP3_FRAME)


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_a_pdf_is_not_audio_whatever_it_is_called(kind: str) -> None:
    assert not rules.looks_like(kind, PDF)


@pytest.mark.parametrize(
    ("kind", "other"), [("mp3", "wav"), ("wav", "ogg"), ("ogg", "m4a"), ("m4a", "mp3")]
)
def test_audio_of_another_type_is_not_accepted_under_this_name(kind: str, other: str) -> None:
    assert not rules.looks_like(kind, SAMPLES[other])


def test_empty_or_tiny_files_are_not_audio() -> None:
    assert not rules.looks_like("mp3", b"")
    assert not rules.looks_like("wav", b"RIFF")
    assert rules.HEAD_BYTES >= 64


# --- consent, size and the key of the stored copy -----------------------------------------------


def test_consent_must_be_given() -> None:
    rules.check_consent(True)
    for bad in (False, None, "yes", 1):
        with pytest.raises(rules.CallRuleError, match="agreed"):
            rules.check_consent(bad)


def test_size_must_be_within_the_limit() -> None:
    rules.check_size(1, 100)
    rules.check_size(100, 100)
    for bad in (0, -5, 101):
        with pytest.raises(rules.CallRuleError):
            rules.check_size(bad, 100)
    with pytest.raises(rules.CallTooLargeError):
        rules.check_size(101, 100)


def test_the_retention_cutoff_is_a_number_of_days_back() -> None:
    now = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
    assert rules.retention_cutoff(now, 90) == now - timedelta(days=90)
    assert rules.retention_cutoff(now, 1) == now - timedelta(days=1)


def test_an_unknown_kind_never_looks_like_audio() -> None:
    assert not rules.looks_like("exe", b"MZ\x90\x00" + b"\x00" * 20)
    assert not rules.looks_like("", SAMPLES["mp3"])
