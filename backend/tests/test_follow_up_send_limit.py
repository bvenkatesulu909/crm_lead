"""The hourly e-mail limit of an approved follow-up still works without a full server configuration.

CI (and any script) has no complete settings, so reading them used to raise; it must fall back to
the built-in default instead (found by the CI run of the approval step)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.communications import api


def test_without_settings_the_default_limit_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> Settings:
        return Settings()  # no database address, no issuer: raises ValidationError

    monkeypatch.setattr(api, "get_settings", broken)
    monkeypatch.delenv("CRM_DATABASE_URL", raising=False)
    try:
        Settings(_env_file=None)
    except ValidationError:
        pass
    assert api._emails_per_hour() == Settings.model_fields["communication_emails_per_hour"].default


def test_with_settings_their_value_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    class Fake:
        communication_emails_per_hour = 7

    monkeypatch.setattr(api, "get_settings", lambda: Fake())
    assert api._emails_per_hour() == 7
