"""The real Razorpay client (ADR 0031): two calls, both to one fixed host.

``POST /v1/payment_links`` creates a standard payment link, ``POST /v1/payment_links/{id}/cancel``
cancels one. Nothing else is called. The host is fixed in this file, never taken from a setting or a
record; redirects are not followed; the key goes only in the Basic-auth header; errors say the
HTTP status and nothing from the body, so no key, link or customer detail reaches a log.
"""

from datetime import datetime

import httpx

from app.modules.payment_links.provider import CreatedLink, ProviderError
from app.modules.payment_links.rules import REFERENCE_MAX_LENGTH

BASE_URL = "https://api.razorpay.com/v1"
_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


class RazorpayProvider:
    def __init__(
        self,
        key_id: str,
        key_secret: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._auth = (key_id, key_secret)
        self._client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=False)

    def _post(self, path: str, body: dict[str, object] | None) -> dict[str, object]:
        try:
            response = self._client.post(f"{BASE_URL}{path}", json=body, auth=self._auth)
        except httpx.HTTPError as exc:
            raise ProviderError("Razorpay could not be reached.") from exc
        if response.status_code != 200:
            raise ProviderError(f"Razorpay answered with status {response.status_code}.")
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError("Razorpay sent an answer that could not be read.") from exc
        if not isinstance(data, dict):
            raise ProviderError("Razorpay sent an answer that could not be read.")
        return data

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
        if len(reference_id) > REFERENCE_MAX_LENGTH:
            raise ProviderError("The reference is too long.")
        data = self._post(
            "/payment_links",
            {
                "amount": amount_paise,
                "currency": currency,
                "accept_partial": False,
                "reference_id": reference_id,
                "description": description[:2000],
                "expire_by": int(expires_at.timestamp()),
                "reminder_enable": False,
                "notes": notes,
            },
        )
        link_id, short_url = data.get("id"), data.get("short_url")
        if (
            not isinstance(link_id, str)
            or not 1 <= len(link_id) <= 60
            or not set(link_id) <= _ID_CHARS
            or not isinstance(short_url, str)
            or not short_url.startswith("https://")
        ):
            raise ProviderError("Razorpay sent an answer that could not be read.")
        return CreatedLink(link_id, short_url)

    def cancel_link(self, provider_link_id: str) -> None:
        if not provider_link_id or not set(provider_link_id) <= _ID_CHARS:
            raise ProviderError("No such link.")
        self._post(f"/payment_links/{provider_link_id}/cancel", None)
