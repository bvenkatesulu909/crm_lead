"""The real Razorpay client (ADR 0031): two calls, both to one fixed host.

``POST /v1/payment_links`` creates a standard payment link, ``POST /v1/payment_links/{id}/cancel``
cancels one. Nothing else is called. The host is fixed in this file, never taken from a setting or a
record; redirects are not followed; the key goes only in the Basic-auth header; errors say the
HTTP status and nothing from the body, so no key, link or customer detail reaches a log. A refusal
(400/422, 401/403) is told apart from an outage, and the body is only read to pick a fixed reason
code (an amount above the account's limit); its text is never kept.
"""

from datetime import datetime

import httpx

from app.modules.payment_links.provider import CreatedLink, ProviderError, ProviderRefusedError
from app.modules.payment_links.rules import REFERENCE_MAX_LENGTH

BASE_URL = "https://api.razorpay.com/v1"
_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def _refusal_reason(response: httpx.Response) -> str:
    """A fixed code for a bad request: only the amount limit is told apart; the text is dropped."""
    try:
        data = response.json()
    except ValueError:
        return "refused"
    error = data.get("error") if isinstance(data, dict) else None
    description = error.get("description") if isinstance(error, dict) else None
    if isinstance(description, str) and "maximum amount" in description.lower():
        return "amount_too_large"
    return "refused"


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
            message = f"Razorpay answered with status {response.status_code}."
            if response.status_code in (401, 403):
                raise ProviderRefusedError("key_refused", message)
            if response.status_code in (400, 422):
                raise ProviderRefusedError(_refusal_reason(response), message)
            raise ProviderError(message)
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
