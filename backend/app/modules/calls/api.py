"""Public interface of the call recordings module. Other modules import only from here."""

from collections.abc import Callable
from typing import cast

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.outbox import DeadJobHandler, Job, JobHandler
from app.core.storage import FileStore
from app.modules.calls import audio, clips, fakes, processing, service
from app.modules.calls.service import Transcript, transcript_of
from app.modules.voice import api as voice_api

expire_stale_uploads = service.expire_stale
delete_old_audio = service.delete_old_audio
AGENT_KEY = service.AGENT_KEY
JOB_KIND = processing.JOB_KIND
CLIP_JOB_KIND = clips.JOB_KIND

__all__ = [
    "AGENT_KEY",
    "CLIP_JOB_KIND",
    "JOB_KIND",
    "Transcript",
    "clip_dead_job_handler",
    "clip_job_handler",
    "dead_job_handler",
    "delete_old_audio",
    "expire_stale_uploads",
    "job_handler",
    "transcript_of",
]


def job_handler(
    store: FileStore,
    settings: Settings,
    *,
    cleaner: audio.Cleaner | None = None,
    speech: Callable[[], voice_api.SpeechProvider | None] | None = None,
) -> JobHandler:
    """Worker handler for "call.process". ``cleaner`` and ``speech`` replace ffmpeg and the speech
    service in tests and evaluations; the worker passes neither."""
    scripted = settings.calls_engine == "fake"
    the_cleaner = (
        cleaner
        or (fakes.ScriptedCleaner() if scripted else None)
        or audio.FfmpegCleaner(
            ffmpeg=settings.calls_ffmpeg_command,
            ffprobe=settings.calls_ffprobe_command,
            timeout_seconds=settings.calls_clean_timeout_seconds,
        )
    )

    def make_speech() -> voice_api.SpeechProvider | None:
        return voice_api.build_speech_provider(settings, stt_model=settings.calls_stt_model)

    the_speech = speech or (
        (lambda: cast(voice_api.SpeechProvider, fakes.ScriptedSpeech()))
        if scripted
        else make_speech
    )

    def handle(session: Session, job: Job) -> None:
        processing.process(
            session,
            job,
            store=store,
            cleaner=the_cleaner,
            speech=the_speech,
            settings=settings,
        )

    return handle


def clip_job_handler(
    store: FileStore, settings: Settings, *, cleaner: audio.Cleaner | None = None
) -> JobHandler:
    """Worker handler for "call.clip": cuts one highlight clip (ADR 0033). ``cleaner`` replaces
    ffmpeg in tests; the worker passes none."""
    the_cleaner = (
        cleaner
        or (fakes.ScriptedCleaner() if settings.calls_engine == "fake" else None)
        or audio.FfmpegCleaner(
            ffmpeg=settings.calls_ffmpeg_command,
            ffprobe=settings.calls_ffprobe_command,
            timeout_seconds=settings.calls_clean_timeout_seconds,
        )
    )

    def handle(session: Session, job: Job) -> None:
        clips.process(session, job, store=store, cleaner=the_cleaner)

    return handle


def clip_dead_job_handler() -> DeadJobHandler:
    return clips.on_dead


def dead_job_handler() -> DeadJobHandler:
    return processing.on_dead
