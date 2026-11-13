"""Cleaning a recording and asking the speech service for a timed transcript (ADR 0030, step CA2).

No ffmpeg and no network are needed: the program runner and the HTTP transport are replaced. A test
that uses the real ffmpeg runs only where it is installed.
"""

import asyncio
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.modules.calls import audio
from app.modules.voice import provider as voice
from app.modules.voice.api import NoSpeechError, SpeechProviderError
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL

# --- the command lines --------------------------------------------------------------------------


def test_cleaning_makes_one_small_mono_channel_and_levels_the_sound() -> None:
    args = audio.clean_args("ffmpeg", "work/in.m4a", "work/out.mp3")
    assert args[0] == "ffmpeg" and "-nostdin" in args
    assert args[args.index("-ac") + 1] == "1"
    assert args[args.index("-ar") + 1] == "16000"
    filters = args[args.index("-af") + 1]
    assert "highpass" in filters and "afftdn" in filters and "loudnorm" in filters
    assert args[args.index("-b:a") + 1] == "48k"
    assert args[args.index("-i") + 1] == "work/in.m4a" and args[-1] == "work/out.mp3"
    assert "-y" in args  # our own temporary output may be overwritten, nothing else is named


def test_the_length_is_read_with_ffprobe_without_a_shell() -> None:
    args = audio.probe_args("ffprobe", "work/in.mp3")
    assert args[0] == "ffprobe" and args[-1] == "work/in.mp3"
    assert "format=duration" in args


@pytest.mark.parametrize(
    ("printed", "seconds"), [("12.5\n", 12.5), ("0.000000\n", 0.0), ("3600\n\n", 3600.0)]
)
def test_the_length_ffprobe_prints_is_read(printed: str, seconds: float) -> None:
    assert audio.parse_duration(printed) == seconds


@pytest.mark.parametrize("printed", ["", "\n", "N/A\n", "abc", "-4\n", "nan\n", "inf\n"])
def test_no_usable_length_means_unreadable(printed: str) -> None:
    with pytest.raises(audio.AudioUnreadableError):
        audio.parse_duration(printed)


# --- running the programs (the runner is replaced) ----------------------------------------------


class FakeRun:
    """Stands in for ``subprocess.run``: records the command, may write the output file."""

    def __init__(self, *, returncode: int = 0, stdout: str = "", write: bytes | None = None):
        self.returncode, self.stdout, self.write = returncode, stdout, write
        self.commands: list[list[str]] = []
        self.sources: list[Path] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(args)
        assert kwargs["timeout"] > 0 and kwargs["check"] is False
        assert "shell" not in kwargs  # no shell, ever
        if "-i" in args:
            source = Path(args[args.index("-i") + 1])
            assert source.read_bytes() == b"SOURCE"
            self.sources.append(source)
            if self.write is not None:
                Path(args[-1]).write_bytes(self.write)
        else:
            self.sources.append(Path(args[-1]))
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, "")


def cleaner(monkeypatch: pytest.MonkeyPatch, fake: FakeRun) -> audio.FfmpegCleaner:
    monkeypatch.setattr(subprocess, "run", fake)
    return audio.FfmpegCleaner(ffmpeg="ff", ffprobe="fp", timeout_seconds=60)


def test_a_cleaned_copy_is_returned_and_the_temporary_files_are_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRun(write=b"CLEAN")
    assert cleaner(monkeypatch, fake).clean(b"SOURCE", "my call.M4A") == b"CLEAN"
    assert fake.commands[0][0] == "ff"
    assert fake.sources[0].suffix == ".m4a"  # our own name, never the person's file name
    assert "my call" not in " ".join(fake.commands[0])
    assert not fake.sources[0].parent.exists()  # removed


def test_a_failed_or_empty_cleaning_is_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(audio.AudioUnreadableError):
        cleaner(monkeypatch, FakeRun(returncode=1, write=b"X")).clean(b"SOURCE", "a.mp3")
    with pytest.raises(audio.AudioUnreadableError):
        cleaner(monkeypatch, FakeRun(write=None)).clean(b"SOURCE", "a.mp3")  # no output file
    with pytest.raises(audio.AudioUnreadableError):
        cleaner(monkeypatch, FakeRun(write=b"")).clean(b"SOURCE", "a.mp3")  # empty output


def test_the_length_comes_from_ffprobe(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (
        cleaner(monkeypatch, FakeRun(stdout="61.2\n")).duration_seconds(b"SOURCE", "a.wav") == 61.2
    )
    with pytest.raises(audio.AudioUnreadableError):
        cleaner(monkeypatch, FakeRun(returncode=1)).duration_seconds(b"SOURCE", "a.wav")


def test_a_missing_program_is_a_set_up_problem_not_a_bad_file() -> None:
    missing = audio.FfmpegCleaner(ffmpeg="no-such-ffmpeg-xyz", ffprobe="no-such-ffprobe-xyz")
    with pytest.raises(audio.AudioToolMissingError):
        missing.duration_seconds(b"SOURCE", "a.mp3")
    with pytest.raises(audio.AudioToolMissingError):
        missing.clean(b"SOURCE", "a.mp3")


def test_a_program_that_takes_too_long_is_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(args: list[str], **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(args, 1)

    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(audio.AudioUnreadableError):
        audio.FfmpegCleaner().clean(b"SOURCE", "a.mp3")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed here")
def test_the_real_ffmpeg_cleans_a_generated_recording(tmp_path: Path) -> None:
    path = tmp_path / "tone.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(44100)
        out.writeframes(b"\x10\x20" * 2 * 44100 * 2)  # two seconds of stereo
    real = audio.FfmpegCleaner()
    data = path.read_bytes()
    assert 1.9 < real.duration_seconds(data, "tone.wav") < 2.1
    cleaned = real.clean(data, "tone.wav")
    assert cleaned[:3] == b"ID3" or cleaned[0] == 0xFF  # an mp3
    assert len(cleaned) < len(data)


# --- the speech service gives timed segments ----------------------------------------------------


def client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def openai(handler: Any) -> voice.OpenAISpeechProvider:
    return voice.OpenAISpeechProvider(
        api_key="k",
        base_url="https://speech.example/v1",
        stt_model="whisper-1",
        tts_model="t",
        tts_voice="v",
        client=client(handler),
    )


def test_the_openai_compatible_service_is_told_the_language_and_asked_for_timestamps() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={
                "text": "नमस्ते जी",
                "segments": [
                    {"start": 0.0, "end": 1.5, "text": " नमस्ते "},
                    {"start": 1.5, "end": 2.0, "text": "   "},
                    {"start": 2.0, "end": 3.25, "text": "जी"},
                ],
            },
        )

    result = asyncio.run(openai(handler).transcribe_timed(b"AUDIO", "c.mp3", "audio/mpeg", "hi"))
    assert seen["url"] == "https://speech.example/v1/audio/transcriptions"
    body = seen["body"].decode("utf-8", errors="replace")
    assert 'name="language"' in body and "\r\n\r\nhi\r\n" in body
    assert "verbose_json" in body and "segment" in body and "whisper-1" in body
    assert result.text == "नमस्ते जी" and result.engine == "openai:whisper-1"
    assert [(s.start, s.end, s.text) for s in result.segments] == [
        (0.0, 1.5, "नमस्ते"),
        (2.0, 3.25, "जी"),
    ]


def test_an_empty_answer_is_no_speech_and_a_vendor_error_is_not() -> None:
    quiet = openai(lambda request: httpx.Response(200, json={"text": "  ", "segments": []}))
    with pytest.raises(NoSpeechError):
        asyncio.run(quiet.transcribe_timed(b"A", "c.mp3", "audio/mpeg", "te"))
    broken = openai(lambda request: httpx.Response(500, json={}))
    with pytest.raises(SpeechProviderError) as caught:
        asyncio.run(broken.transcribe_timed(b"A", "c.mp3", "audio/mpeg", "te"))
    assert not isinstance(caught.value, NoSpeechError)  # a vendor error is worth retrying


def test_elevenlabs_words_become_segments_and_the_language_is_sent() -> None:
    seen: dict[str, Any] = {}
    words = [
        {"text": "hello", "start": 0.0, "end": 0.4, "type": "word"},
        {"text": " ", "start": 0.4, "end": 0.5, "type": "spacing"},
        {"text": "ji", "start": 0.5, "end": 0.8, "type": "word"},
        {"text": "namaste", "start": 5.0, "end": 5.5, "type": "word"},  # after a long pause
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, json={"text": "hello ji namaste", "words": words})

    eleven = voice.ElevenLabsSpeechProvider(
        api_key="k",
        base_url="https://eleven.example/v1",
        stt_model="scribe_v1",
        tts_model="t",
        tts_voice="v",
        client=client(handler),
    )
    result = asyncio.run(eleven.transcribe_timed(b"A", "c.mp3", "audio/mpeg", "te"))
    assert 'name="language_code"' in seen["body"].decode("utf-8", errors="replace")
    assert [(s.start, s.end, s.text) for s in result.segments] == [
        (0.0, 0.8, "hello ji"),
        (5.0, 5.5, "namaste"),
    ]
    assert result.engine == "elevenlabs:scribe_v1"


def test_words_are_grouped_by_count_and_by_pauses() -> None:
    many = [(float(i), i + 0.5, f"w{i}") for i in range(45)]
    groups = voice.segments_from_words(many, per_segment=20)
    assert [len(g.text.split()) for g in groups] == [20, 20, 5]
    assert voice.segments_from_words([]) == []


def test_calls_may_use_their_own_transcription_model() -> None:
    config = Settings(
        _env_file=None,
        environment="test",
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=TEST_ISSUER,
        voice_api_key="k",
    )
    chosen = voice.build_speech_provider(config, stt_model="whisper-1")
    assert isinstance(chosen, voice.OpenAISpeechProvider)
    assert chosen._stt_model == "whisper-1"
    default = voice.build_speech_provider(config)
    assert isinstance(default, voice.OpenAISpeechProvider)
    assert default._stt_model == config.voice_stt_model


# --- the scripted engine (tests and local demos) -----------------------------------------


def test_the_scripted_engine_can_never_run_in_production() -> None:
    from pydantic import ValidationError

    base = {
        "_env_file": None,
        "database_url": UNREACHABLE_DATABASE_URL,
        "oidc_issuer": "https://auth.example.test/realms/crm",
        "files_s3_secure": True,
    }
    with pytest.raises(ValidationError, match="call engine"):
        Settings(environment="production", calls_engine="fake", **base)  # type: ignore[arg-type]


def test_the_scripted_engine_gives_a_fixed_transcript_in_the_chosen_language() -> None:
    from app.modules.calls import fakes

    for language, script in (("hi", "फ्लैट"), ("te", "ఫ్లాట్"), ("en", "flat")):
        result = asyncio.run(
            fakes.ScriptedSpeech().transcribe_timed(b"A", "c.mp3", "audio/mpeg", language)
        )
        assert script in result.text and result.engine == "fake:scripted"
        assert [s.text for s in result.segments] and result.segments[0].start == 0.0
    unknown = asyncio.run(fakes.ScriptedSpeech().transcribe_timed(b"A", "c.mp3", "audio/mpeg", "x"))
    assert "flat" in unknown.text
    assert fakes.ScriptedCleaner().clean(b"AB", "c.mp3") == b"AB"
    assert fakes.ScriptedCleaner().duration_seconds(b"A" * 5500, "c.mp3") == 5.0
    assert fakes.ScriptedCleaner().duration_seconds(b"", "c.mp3") == 1.0
