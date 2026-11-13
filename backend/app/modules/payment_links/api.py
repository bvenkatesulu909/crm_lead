"""Public interface of the payment links module (ADR 0031). Other modules import only from here."""

from app.core.config import Settings
from app.core.outbox import JobHandler
from app.modules.payment_links import rules, service
from app.modules.payment_links.provider import FakeProvider, PaymentProvider, UnavailableProvider
from app.modules.payment_links.razorpay import RazorpayProvider

APPLY_JOB = service.APPLY_JOB
AGENT_KEY = service.AGENT_KEY
link_creator = service.link_creator
verify_signature = rules.verify_signature
to_paise = rules.to_paise
from_paise = rules.from_paise

__all__ = [
    "AGENT_KEY",
    "APPLY_JOB",
    "apply_job_handler",
    "build_provider",
    "link_creator",
    "from_paise",
    "to_paise",
    "verify_signature",
]


def build_provider(settings: Settings) -> PaymentProvider:
    """The scripted fake (default, no network), or the real client with the configured keys. The
    settings validator has already refused a half-set or unsafe combination."""
    if settings.razorpay_mode == "off":
        return UnavailableProvider()
    if settings.razorpay_mode == "fake":
        return FakeProvider()
    if not (settings.razorpay_key_id and settings.razorpay_key_secret):
        raise ValueError("Razorpay keys are not configured.")
    return RazorpayProvider(
        settings.razorpay_key_id, settings.razorpay_key_secret.get_secret_value()
    )


def apply_job_handler() -> JobHandler:
    return service.apply_event
