"""The payment provider seam (ADR 0031): what the CRM asks of Razorpay, and a scripted fake.

The real client arrives with step UP2. Until then everything runs against ``FakeProvider``, which
behaves like Razorpay where it matters: a reference id can be used once, an amount must be a
positive whole number of paise, a cancelled link stays cancelled. No network, no key.
"""

import itertools
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.payment_links import rules


class ProviderError(Exception):
    """The provider could not be reached, was busy or broken, or refused (see the subclasses).

    The message never holds a key, a secret or anything the provider sent back.
    """


class ProviderRefusedError(ProviderError):
    """The provider answered and refused this request (a 4xx answer other than 429).

    Trying again will not help, so the person is told it was refused, not that the service is down.
    """


class AmountTooLargeError(ProviderRefusedError):
    """The amount is above the provider account's maximum for one payment."""


@dataclass(frozen=True)
class CreatedLink:
    provider_link_id: str
    short_url: str


class PaymentProvider(Protocol):
    def create_link(
        self,
        *,
        reference_id: str,
        amount_paise: int,
        currency: str,
        description: str,
        expires_at: datetime,
        notes: dict[str, str],
    ) -> CreatedLink: ...

    def cancel_link(self, provider_link_id: str) -> None: ...


class UnavailableProvider:
    """No provider is configured (the default): every call says so, nothing leaves the server."""

    def create_link(
        self,
        *,
        reference_id: str,
        amount_paise: int,
        currency: str,
        description: str,
        expires_at: datetime,
        notes: dict[str, str],
    ) -> CreatedLink:
        raise ProviderError("No payment provider is configured.")

    def cancel_link(self, provider_link_id: str) -> None:
        raise ProviderError("No payment provider is configured.")


class FakeProvider:
    def __init__(self) -> None:
        self._counter = itertools.count(1)
        self.links: dict[str, dict[str, object]] = {}
        self.cancelled: set[str] = set()

    def create_link(
        self,
        *,
        reference_id: str,
        amount_paise: int,
        currency: str,
        description: str,
        expires_at: datetime,
        notes: dict[str, str],
    ) -> CreatedLink:
        if len(reference_id) > rules.REFERENCE_MAX_LENGTH:
            raise ProviderError("The reference is too long.")
        if any(link["reference_id"] == reference_id for link in self.links.values()):
            raise ProviderError("That reference was already used.")
        if currency != rules.CURRENCY:
            raise ProviderError("Only INR is supported.")
        if amount_paise > rules.MAX_PAISE:
            raise AmountTooLargeError("The amount is above the maximum.")
        if amount_paise < rules.MIN_PAISE:
            raise ProviderRefusedError("The amount is out of range.")
        link_id = f"plink_fake{next(self._counter):06d}"
        self.links[link_id] = {
            "reference_id": reference_id,
            "amount_paise": amount_paise,
            "currency": currency,
            "description": description,
            "expires_at": expires_at,
            "notes": dict(notes),
        }
        return CreatedLink(link_id, f"https://pay.fake.invalid/{link_id}")

    def cancel_link(self, provider_link_id: str) -> None:
        if provider_link_id not in self.links:
            raise ProviderError("No such link.")
        self.cancelled.add(provider_link_id)
