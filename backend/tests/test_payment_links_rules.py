"""Payment links, pure part (ADR 0031, UP1): the webhook signature, money in paise, references,
the fake provider and the settings that keep real money out of test setups. No database, no
network."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.core.config import Settings
from app.modules.payment_links import rules
from app.modules.payment_links.provider import FakeProvider, ProviderError
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL

SECRET = "whsec-test-value"  # noqa: S105 - a made-up test value
BODY = b'{"event":"payment_link.paid","payload":{"payment_link":{"entity":{"id":"plink_1"}}}}'


def settings(**values: Any) -> Settings:
    values.setdefault("environment", "test")
    values.setdefault("oidc_issuer", TEST_ISSUER)
    return Settings(_env_file=None, database_url=UNREACHABLE_DATABASE_URL, **values)


# --- the webhook signature -------------------------------------------------------------------


def test_the_signature_of_the_exact_body_is_accepted() -> None:
    assert rules.verify_signature(BODY, rules.sign(BODY, SECRET), SECRET)


def test_one_changed_byte_is_refused() -> None:
    signature = rules.sign(BODY, SECRET)
    assert not rules.verify_signature(BODY + b" ", signature, SECRET)
    assert not rules.verify_signature(BODY.replace(b"plink_1", b"plink_2"), signature, SECRET)


def test_a_rewritten_body_is_refused() -> None:
    """Parsing and re-writing the JSON (spaces, key order) changes the bytes: that must fail."""
    import json

    signature = rules.sign(BODY, SECRET)
    rewritten = json.dumps(json.loads(BODY), indent=2).encode()
    assert not rules.verify_signature(rewritten, signature, SECRET)


def test_another_secret_is_refused() -> None:
    assert not rules.verify_signature(BODY, rules.sign(BODY, "someone-elses"), SECRET)


@pytest.mark.parametrize("signature", [None, "", "   ", "not-hex", "0" * 64])
def test_a_missing_or_wrong_signature_is_refused(signature: str | None) -> None:
    assert not rules.verify_signature(BODY, signature, SECRET)


@pytest.mark.parametrize("secret", [None, ""])
def test_without_a_secret_nothing_can_be_verified(secret: str | None) -> None:
    """A missing secret must refuse, never accept: otherwise anyone could post a payment."""
    assert not rules.verify_signature(BODY, rules.sign(BODY, ""), secret)
    assert not rules.verify_signature(BODY, rules.sign(BODY, SECRET), secret)


def test_capital_letters_and_spaces_around_the_signature_are_tolerated() -> None:
    signature = rules.sign(BODY, SECRET)
    assert rules.verify_signature(BODY, f" {signature.upper()} ", SECRET)


def test_the_body_hash_is_a_sha256_of_the_bytes() -> None:
    assert len(rules.body_sha256(BODY)) == 64
    assert rules.body_sha256(BODY) != rules.body_sha256(BODY + b"x")


# --- money -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rupees", "paise"),
    [("1", 100), ("1.00", 100), ("214.16", 21416), ("0.29", None), ("5000000", 500_000_000)],
)
def test_rupees_become_whole_paise_without_a_float(rupees: str, paise: int | None) -> None:
    if paise is None:
        with pytest.raises(ValueError):
            rules.to_paise(Decimal(rupees))  # below one rupee
    else:
        assert rules.to_paise(Decimal(rupees)) == paise


@pytest.mark.parametrize("bad", ["0", "-5", "0.99", "10.005", "NaN", "Infinity", "100000001"])
def test_amounts_that_must_not_reach_razorpay_are_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        rules.to_paise(Decimal(bad))


def test_a_float_is_refused() -> None:
    with pytest.raises(ValueError):
        rules.to_paise(10.5)  # type: ignore[arg-type]


def test_the_largest_amount_is_still_accepted() -> None:
    assert rules.to_paise(Decimal("100000000")) == rules.MAX_PAISE


def test_paise_back_to_rupees_is_exact() -> None:
    assert rules.from_paise(21416) == Decimal("214.16")
    assert rules.from_paise(rules.to_paise(Decimal("19.99"))) == Decimal("19.99")


# --- references and expiry -------------------------------------------------------------------


def test_a_reference_fits_razorpays_limit_and_differs_per_try() -> None:
    invoice = uuid.uuid4()
    first, second = rules.reference_id(invoice, 1), rules.reference_id(invoice, 2)
    assert first != second
    assert len(first) <= rules.REFERENCE_MAX_LENGTH
    assert len(rules.reference_id(invoice, 99)) <= rules.REFERENCE_MAX_LENGTH
    assert rules.reference_id(invoice, 1) == first  # stable


@pytest.mark.parametrize("attempt", [0, 100, -1])
def test_a_reference_try_out_of_range_is_refused(attempt: int) -> None:
    with pytest.raises(ValueError):
        rules.reference_id(uuid.uuid4(), attempt)


def test_the_expiry_is_days_ahead_and_needs_a_timezone() -> None:
    now = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
    assert rules.expires_at(now) == datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
    assert rules.expires_at(now, 1) == datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        rules.expires_at(datetime(2026, 11, 13, 9, 0))


# --- the fake provider -----------------------------------------------------------------------


def create(provider: FakeProvider, reference: str = "ref1", paise: int = 21416, **over: Any):
    values: dict[str, Any] = {
        "reference_id": reference,
        "amount_paise": paise,
        "currency": "INR",
        "description": "Invoice 7",
        "expires_at": datetime(2026, 11, 20, tzinfo=UTC),
        "notes": {"invoice": "x"},
    }
    values.update(over)
    return provider.create_link(**values)


def test_the_fake_gives_each_link_its_own_id_and_address() -> None:
    provider = FakeProvider()
    first, second = create(provider, "a"), create(provider, "b")
    assert first.provider_link_id != second.provider_link_id
    assert first.short_url.startswith("https://") and first.provider_link_id in first.short_url


def test_the_fake_refuses_a_reference_used_before() -> None:
    provider = FakeProvider()
    create(provider, "same")
    with pytest.raises(ProviderError):
        create(provider, "same")


@pytest.mark.parametrize(
    "over",
    [{"amount_paise": 99}, {"amount_paise": 0}, {"currency": "USD"}, {"reference_id": "x" * 41}],
)
def test_the_fake_refuses_what_razorpay_refuses(over: dict[str, Any]) -> None:
    with pytest.raises(ProviderError):
        create(FakeProvider(), "ok", **over)


def test_the_fake_can_cancel_only_a_link_that_exists() -> None:
    provider = FakeProvider()
    link = create(provider)
    provider.cancel_link(link.provider_link_id)
    assert link.provider_link_id in provider.cancelled
    with pytest.raises(ProviderError):
        provider.cancel_link("plink_nope")


# --- settings: real money stays out of test setups -------------------------------------------

KEYS = {
    "razorpay_key_id": "rzp_test_abc123",
    "razorpay_key_secret": "s1",
    "razorpay_webhook_secret": "s2",
}


def test_the_default_is_off_with_no_keys_needed() -> None:
    assert settings().razorpay_mode == "off"


def test_off_is_allowed_in_production_so_a_server_without_razorpay_starts() -> None:
    config = settings(
        environment="production",
        oidc_issuer="https://auth.example.test/realms/crm",
        files_s3_secure=True,
    )
    assert config.razorpay_mode == "off"


def test_the_unavailable_provider_refuses_everything() -> None:
    from app.modules.payment_links.provider import UnavailableProvider

    with pytest.raises(ProviderError):
        create(UnavailableProvider())  # type: ignore[arg-type]
    with pytest.raises(ProviderError):
        UnavailableProvider().cancel_link("plink_1")


def test_the_fake_is_refused_in_production() -> None:
    with pytest.raises(ValueError, match="fake payment provider"):
        settings(
            environment="production",
            razorpay_mode="fake",
            oidc_issuer="https://auth.example.test/realms/crm",
            files_s3_secure=True,
        )


def test_test_mode_needs_all_three_secrets() -> None:
    assert settings(razorpay_mode="test", **KEYS).razorpay_mode == "test"
    for missing in KEYS:
        values = {k: v for k, v in KEYS.items() if k != missing}
        with pytest.raises(ValueError, match="needs"):
            settings(razorpay_mode="test", **values)


def test_test_mode_refuses_a_live_key() -> None:
    with pytest.raises(ValueError, match="live key"):
        settings(razorpay_mode="test", **{**KEYS, "razorpay_key_id": "rzp_live_abc"})


def test_live_mode_needs_the_owners_go_live_and_a_live_key() -> None:
    live = {**KEYS, "razorpay_key_id": "rzp_live_abc"}
    with pytest.raises(ValueError, match="go-live"):
        settings(razorpay_mode="live", **live)
    with pytest.raises(ValueError, match="live key"):
        settings(razorpay_mode="live", razorpay_go_live=True, **KEYS)
    assert settings(razorpay_mode="live", razorpay_go_live=True, **live).razorpay_mode == "live"


def test_the_secrets_do_not_show_in_the_settings_text() -> None:
    text = repr(settings(razorpay_mode="test", **KEYS))
    assert "s1" not in text.replace("rzp_test", "")  # SecretStr hides them
    assert "razorpay_key_secret=SecretStr('**********')" in text
