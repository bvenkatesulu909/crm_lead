"""File store and mailer adapters (ADR 0005), without real servers."""

import smtplib
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.mail import (
    Attachment,
    Mail,
    MailRejectedError,
    MailUnavailableError,
    MemoryMailer,
    SmtpMailer,
    build_message,
)
from app.core.storage import (
    FileStoreUnavailableError,
    MemoryFileStore,
    S3FileStore,
    StoredFileMissingError,
    UnconfiguredFileStore,
    build_file_store,
    object_key,
)
from tests.auth_helpers import TEST_ISSUER

DB_URL = "postgresql+psycopg://u:p@127.0.0.1:1/none"
FAKE_SECRET = "test-only-not-a-real-secret"  # noqa: S105 - placeholder for tests


def make_settings(**values: Any) -> Settings:
    return Settings(
        **({"_env_file": None, "database_url": DB_URL, "oidc_issuer": TEST_ISSUER} | values)
    )


# --- file store ---------------------------------------------------------------------------


def test_object_keys_always_start_with_the_tenant() -> None:
    t, r, f = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert object_key(t, "quotes", r, f) == f"tenant/{t}/quotes/{r}/{f}"
    for bad in ("../x", "quotes/../..", "", "a b"):
        with pytest.raises(ValueError):
            object_key(t, bad, r, f)


def test_memory_store_round_trip_and_missing_file() -> None:
    store = MemoryFileStore()
    store.put("tenant/a/x", b"%PDF-1.7", "application/pdf")
    assert store.get("tenant/a/x") == b"%PDF-1.7"
    store.delete("tenant/a/x")
    store.delete("tenant/a/x")  # twice is fine: handlers may run twice
    with pytest.raises(StoredFileMissingError) as missing:
        store.get("tenant/a/x")
    assert missing.value.status_code == 404


def test_without_keys_storing_files_answers_503_and_nothing_else_breaks() -> None:
    store = build_file_store(make_settings())
    assert isinstance(store, UnconfiguredFileStore)
    with pytest.raises(FileStoreUnavailableError) as error:
        store.put("k", b"x", "text/plain")
    assert (error.value.status_code, error.value.code) == (503, "files_unavailable")


def test_keys_select_the_s3_store_and_empty_values_mean_not_configured() -> None:
    configured = make_settings(files_s3_access_key="crm", files_s3_secret_key=FAKE_SECRET)
    assert isinstance(build_file_store(configured), S3FileStore)
    empty = make_settings(files_s3_access_key="", files_s3_secret_key=" ")  # noqa: S106 - blank
    assert not empty.files_configured


def test_s3_store_maps_connection_failures_to_503() -> None:
    # Nothing listens on port 9 (discard): the store must answer 503, not crash.
    settings = make_settings(
        files_s3_endpoint="127.0.0.1:9",
        files_s3_access_key="crm",
        files_s3_secret_key=FAKE_SECRET,
    )
    store = S3FileStore(settings, retries=0)
    with pytest.raises(FileStoreUnavailableError):
        store.put("tenant/a/x", b"x", "text/plain")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("files_s3_endpoint", "http://127.0.0.1:9333"),  # host:port only
        ("files_s3_bucket", "Bad_Bucket"),
        ("files_max_bytes", 10),
    ],
)
def test_invalid_file_settings_stop_startup(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})


def test_production_requires_https_for_the_file_store() -> None:
    with pytest.raises(ValidationError, match="file store must use HTTPS"):
        make_settings(environment="production", oidc_issuer="https://id.example.test/realms/crm")


# --- mail ---------------------------------------------------------------------------------


def a_mail(**changes: Any) -> Mail:
    values: dict[str, Any] = {
        "to": ("customer@example.test",),
        "subject": "Your quote QT-0007",
        "text": "Hello, please find the quote attached.",
        "attachments": (Attachment("QT-0007.pdf", "application/pdf", b"%PDF-1.7 test"),),
    }
    return Mail(**(values | changes))


def test_message_has_text_and_pdf_attachment() -> None:
    message = build_message(a_mail(), "CRM <no-reply@crm.localhost>")
    assert message["To"] == "customer@example.test"
    assert message["Subject"] == "Your quote QT-0007"
    parts = list(message.iter_attachments())
    assert [(p.get_filename(), p.get_content_type()) for p in parts] == [
        ("QT-0007.pdf", "application/pdf")
    ]
    assert parts[0].get_content() == b"%PDF-1.7 test"


@pytest.mark.parametrize(
    "changes",
    [
        {"subject": "Quote\r\nBcc: victim@example.test"},
        {"to": ("a@example.test\nBcc: victim@example.test",)},
    ],
)
def test_header_injection_is_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        build_message(a_mail(**changes), "CRM <no-reply@crm.localhost>")
    with pytest.raises(ValueError):
        MemoryMailer().send(a_mail(**changes))


def test_a_mail_needs_a_recipient() -> None:
    with pytest.raises(MailRejectedError):
        build_message(a_mail(to=()), "CRM <no-reply@crm.localhost>")


class FakeSmtp:
    """Stands in for smtplib.SMTP; behaviour set per test."""

    error: BaseException | None = None
    sent: list[Any] = []
    calls: list[str] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        FakeSmtp.calls.append(f"connect {host}:{port} timeout={timeout}")

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def starttls(self, context: Any) -> None:
        FakeSmtp.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        FakeSmtp.calls.append(f"login {user}")

    def send_message(self, message: Any) -> None:
        if FakeSmtp.error is not None:
            raise FakeSmtp.error
        FakeSmtp.sent.append(message)


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSmtp]:
    FakeSmtp.error, FakeSmtp.sent, FakeSmtp.calls = None, [], []
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    return FakeSmtp


def test_smtp_mailer_uses_the_configured_server(fake_smtp: type[FakeSmtp]) -> None:
    SmtpMailer(make_settings(smtp_port=2525)).send(a_mail())
    assert fake_smtp.calls == ["connect 127.0.0.1:2525 timeout=15.0"]  # no TLS/login locally
    assert fake_smtp.sent[0]["From"] == "CRM <no-reply@crm.localhost>"

    fake_smtp.calls = []
    SmtpMailer(
        make_settings(smtp_starttls=True, smtp_username="crm", smtp_password=FAKE_SECRET)
    ).send(a_mail())
    assert fake_smtp.calls[1:] == ["starttls", "login crm"]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (smtplib.SMTPRecipientsRefused({}), MailRejectedError),
        (smtplib.SMTPDataError(554, b"rejected"), MailRejectedError),
        (smtplib.SMTPDataError(451, b"try later"), MailUnavailableError),
        (ConnectionRefusedError(), MailUnavailableError),
        (smtplib.SMTPServerDisconnected(), MailUnavailableError),
    ],
)
def test_smtp_failures_are_temporary_or_permanent(
    fake_smtp: type[FakeSmtp], error: BaseException, expected: type[Exception]
) -> None:
    fake_smtp.error = error
    with pytest.raises(expected):
        SmtpMailer(make_settings()).send(a_mail())
