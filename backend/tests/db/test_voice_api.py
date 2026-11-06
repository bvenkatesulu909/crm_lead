# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""Voice is governed by the agent registry (ADR 0023, steps VM2-VM3).

The speech service is a fake (no key, no network). People come from test_quotes_api.py.
"""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import bind_tenant
from app.modules.agents.models import AgentSetting, AgentUsage
from app.modules.voice.provider import SpeechProviderError, SynthesizedSpeech
from tests.db.test_assistant_proposals import alpha, make_api  # noqa: F401
from tests.db.test_quotes_api import World, auth, ok, world  # noqa: F401

VOICE = "/api/v1/voice"
AUDIO = b"\x1a\x45\xdf\xa3" + b"0" * 8000  # 8 kB of "webm": about 2 seconds


class FakeSpeech:
    available = True

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    async def transcribe(self, data: bytes, filename: str, content_type: str) -> str:
        self.calls.append("transcribe")
        if self.fail:
            raise SpeechProviderError("Speech transcription is unavailable.")
        return "Which tickets are open?"

    async def synthesize(self, text: str) -> SynthesizedSpeech:
        self.calls.append(f"speak:{text}")
        return SynthesizedSpeech(b"ID3-fake-audio")


def api_with(make_api: Any, speech: FakeSpeech | None, **settings: Any) -> TestClient:
    client: TestClient = make_api(None, **settings)
    client.app.state.speech_provider = speech  # type: ignore[attr-defined]
    return client


def switch(db_session: Session, world: World, enabled: bool, tenant: Any = None) -> None:
    tenant = tenant or alpha(world)
    bind_tenant(db_session, tenant)
    db_session.add(AgentSetting(tenant_id=tenant, agent_key="voice", enabled=enabled))
    db_session.flush()


def usage(db_session: Session, world: World) -> tuple[int, int]:
    bind_tenant(db_session, alpha(world))
    row = db_session.scalar(select(AgentUsage).where(AgentUsage.agent_key == "voice"))
    return (row.input_tokens, row.output_tokens) if row else (0, 0)


def transcribe(api: TestClient, auth: Any, user: str = "alpha.agent1") -> Any:
    return api.post(
        f"{VOICE}/transcribe",
        files={"file": ("speech.webm", AUDIO, "audio/webm")},
        headers=auth(user),
    )


def speak(api: TestClient, auth: Any, text: str = "Two tickets are open.") -> Any:
    return api.post(f"{VOICE}/speak", json={"text": text}, headers=auth("alpha.agent1"))


def test_voice_is_off_until_an_administrator_switches_it_on(make_api, auth, world) -> None:
    api = api_with(make_api, None)
    status = ok(api.get(f"{VOICE}/status", headers=auth("alpha.agent1")))
    assert status == {
        "enabled": False,
        "browser_engine": True,
        "server_engine": False,
        "minutes_used": 0,
        "minutes_budget": 300,
    }


def test_the_status_follows_the_switch_and_the_settings(make_api, auth, world, db_session) -> None:
    switch(db_session, world, True)
    api = api_with(make_api, FakeSpeech(), voice_browser_engine=False, voice_monthly_minutes=60)
    status = ok(api.get(f"{VOICE}/status", headers=auth("alpha.agent1")))
    assert status["enabled"] is True
    assert status["browser_engine"] is False
    assert status["server_engine"] is True
    assert status["minutes_budget"] == 60


def test_one_organisations_switch_does_not_switch_on_another(
    make_api, auth, world, db_session
) -> None:
    switch(db_session, world, True)
    api = api_with(make_api, FakeSpeech())
    assert ok(api.get(f"{VOICE}/status", headers=auth("beta.agent")))["enabled"] is False
    assert transcribe(api, auth, "beta.agent").json()["code"] == "voice_off"


def test_server_speech_is_refused_while_voice_is_off(make_api, auth, world) -> None:
    speech = FakeSpeech()
    api = api_with(make_api, speech)
    for response in (transcribe(api, auth), speak(api, auth)):
        assert response.status_code == 503
        assert response.json()["code"] == "voice_off"
    assert speech.calls == []  # the paid service was never called


def test_server_speech_counts_estimated_seconds(make_api, auth, world, db_session) -> None:
    switch(db_session, world, True)
    speech = FakeSpeech()
    api = api_with(make_api, speech)
    assert ok(transcribe(api, auth)) == {"text": "Which tickets are open?"}
    response = speak(api, auth, "Two tickets are open: one about billing.")  # 40 characters
    assert response.status_code == 200
    assert response.content == b"ID3-fake-audio"
    assert usage(db_session, world) == (3, 3)  # 8004 bytes -> 3 s heard; 40 chars -> 3 s spoken


def test_the_monthly_minutes_are_a_hard_limit(make_api, auth, world, db_session) -> None:
    switch(db_session, world, True)
    speech = FakeSpeech()
    api = api_with(make_api, speech, voice_monthly_minutes=1)
    for _ in range(20):  # 3 s each: the 21st would be past 60 s
        ok(transcribe(api, auth))
    response = transcribe(api, auth)
    assert response.status_code == 503
    assert response.json()["code"] == "voice_budget_reached"
    assert speech.calls.count("transcribe") == 20


def test_a_failing_speech_service_is_not_counted(make_api, auth, world, db_session) -> None:
    switch(db_session, world, True)
    api = api_with(make_api, FakeSpeech(fail=True))
    response = transcribe(api, auth)
    assert response.status_code == 503
    assert response.json()["code"] == "voice_unavailable"
    assert usage(db_session, world) == (0, 0)


def test_without_a_speech_service_the_answer_is_voice_unavailable(
    make_api, auth, world, db_session
) -> None:
    switch(db_session, world, True)
    api = api_with(make_api, None)
    assert transcribe(api, auth).json()["code"] == "voice_unavailable"


def test_the_spoken_text_is_cleaned_before_it_becomes_audio(
    make_api, auth, world, db_session
) -> None:
    switch(db_session, world, True)
    speech = FakeSpeech()
    api = api_with(make_api, speech)
    ok_response = speak(api, auth, "Open [this](https://evil.example/x?d=1) now.")
    assert ok_response.status_code == 200
    assert "evil.example" not in speech.calls[-1]


def test_the_registry_lists_voice_without_a_token_budget(make_api, auth, world) -> None:
    api = api_with(make_api, None)
    agents = ok(api.get("/api/v1/agents", headers=auth("alpha.admin")))
    items = agents["items"] if isinstance(agents, dict) else agents
    voice = next(a for a in items if a["key"] == "voice")
    assert voice["uses_model"] is False
    assert voice["enabled"] is False
