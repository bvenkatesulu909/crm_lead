"""Pure rules of the no-code agent builder (ADR 0034, AB1): no database, no model, no network.

A custom agent is a recipe made of data. This file holds the two fixed menus an administrator can
choose from, the limits, and the cleaning of the typed text. Nothing here can add a power: a read
set or a suggestion kind that is not on a menu is refused, and the menus are written out in the
database checks of migration 0068 as well (a test keeps the two in step).
"""

import re
import secrets
import string
from dataclasses import dataclass

from app.core.screening import screen

NAME_MAX = 60
PURPOSE_MAX = 200
INSTRUCTION_MAX = 4000
MIN_MEANINGFUL = 3
MAX_AGENTS = 10  # per organisation (ADR 0034, decision AB8; counted by the service in AB2)
MAX_READ_SETS = 3
MAX_SUGGESTION_KINDS = 2
KEY_LETTERS = 12

# What a custom agent may LOOK AT. Each runs as the person who starts the agent, so that person's
# own record-level rules decide what is visible (AB2). The text is what the builder screen shows.
READ_SETS: dict[str, str] = {
    "lead": "The lead's own fields (status, source, wishes, score reasons).",
    "lead_activity": "The lead's recent timeline and open tasks.",
    "account": "The account's own fields.",
    "account_health": "The account's health figures and last interaction.",
    "deal": "The deal's own fields (stage, amount, expected close).",
    "deal_quotes": "The deal's quotes and their status.",
}

# What kind of record each read set is about. A run is about ONE record, so the read sets of one
# agent must all belong to the same kind (a lead agent cannot also read "the deal's quotes").
RECORD_TYPE_OF: dict[str, str] = {
    "lead": "lead",
    "lead_activity": "lead",
    "account": "account",
    "account_health": "account",
    "deal": "deal",
    "deal_quotes": "deal",
}

# What a custom agent may SUGGEST: kinds that already exist in the approval queue, and nothing that
# moves money or a deal's stage. A new kind is a developer's change and an amendment of ADR 0034.
# ``lead.assign`` is left out of v1: the model is never shown who could be assigned, so it could
# only guess a person (ADR 0034, amendment of 2026-11-16).
SUGGESTION_KINDS: tuple[str, ...] = ("lead.set_status", "activity.create_task")
# The kinds that change the lead itself work only for an agent that reads a lead.
LEAD_ONLY_KINDS = frozenset({"lead.set_status"})


class DefinitionError(ValueError):
    """The typed definition cannot be used. The message is safe to show to the administrator."""


@dataclass(frozen=True)
class CleanDefinition:
    name: str
    purpose: str
    instruction: str
    read_sets: list[str]
    suggestion_kinds: list[str]
    # What kind of record this agent is run on: "lead", "account" or "deal".
    record_type: str
    # Codes of what was taken out while cleaning (links, hidden characters...), never the text.
    cleaned: list[str]


def new_agent_key() -> str:
    """The agent's key in the registry: unguessable and never a built-in agent's name."""
    # Letters only: the registry's key rule (agents.catalogue.KEY_PATTERN) allows no digits.
    return "custom_" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(KEY_LETTERS))


_KEY = re.compile(r"^custom_[a-z]{12}$")


def is_custom_key(key: str) -> bool:
    return _KEY.fullmatch(key) is not None


def _meaningful(text: str) -> str:
    return "".join(ch for ch in text if ch.isalnum())


def _squeeze(rows: list[str]) -> list[str]:
    kept: list[str] = []
    for row in rows:
        if row == "" and (not kept or kept[-1] == ""):
            continue
        kept.append(row)
    return kept


def _clean_text(label: str, raw: str, *, longest: int, lines: bool) -> tuple[str, set[str]]:
    result = screen(raw)
    codes = {finding.code for finding in result.findings}
    if "instruction_phrase" in codes:
        raise DefinitionError(
            f"The {label} contains words that try to change the safety rules of the AI. "
            "Describe the task instead."
        )
    if lines:
        # Keep the administrator's line breaks (an instruction is written in short paragraphs), but
        # drop the spaces around them and any run of blank lines.
        rows = [" ".join(row.split()) for row in result.clean.splitlines()]
        text = "\n".join(_squeeze(rows)).strip()
    else:
        text = " ".join(result.clean.split())
    if len(_meaningful(text)) < MIN_MEANINGFUL:
        raise DefinitionError(f"The {label} is empty after unusable text is removed.")
    if len(text) > longest:
        raise DefinitionError(f"The {label} may have at most {longest} characters.")
    return text, codes


def _menu(label: str, values: list[str], allowed: tuple[str, ...], most: int) -> list[str]:
    chosen = list(dict.fromkeys(values))  # without repeats, in the order given
    if not 1 <= len(chosen) <= most:
        raise DefinitionError(f"Choose 1-{most} {label}.")
    if any(value not in allowed for value in chosen):
        raise DefinitionError(f"Something chosen is not on the menu of {label}.")
    return chosen


def clean_definition(
    *,
    name: str,
    purpose: str,
    instruction: str,
    read_sets: list[str],
    suggestion_kinds: list[str],
) -> CleanDefinition:
    """The cleaned definition, or ``DefinitionError``. Text from a person is data like any other:
    links, markup and hidden characters are taken out and reported by code; words that try to
    switch off the safety rules are refused outright (the instruction is read by a model)."""
    found: set[str] = set()
    sets = _menu("read sets", read_sets, tuple(READ_SETS), MAX_READ_SETS)
    kinds = _menu("suggestion kinds", suggestion_kinds, SUGGESTION_KINDS, MAX_SUGGESTION_KINDS)
    record_types = {RECORD_TYPE_OF[item] for item in sets}
    if len(record_types) != 1:
        raise DefinitionError("Read sets about different kinds of record cannot be mixed.")
    record_type = record_types.pop()
    if record_type != "lead" and LEAD_ONLY_KINDS & set(kinds):
        raise DefinitionError("Changing a lead's status needs an agent that reads a lead.")
    clean_name, codes = _clean_text("name", name, longest=NAME_MAX, lines=False)
    found |= codes
    clean_purpose, codes = _clean_text("purpose", purpose, longest=PURPOSE_MAX, lines=False)
    found |= codes
    clean_instruction, codes = _clean_text(
        "instruction", instruction, longest=INSTRUCTION_MAX, lines=True
    )
    found |= codes
    return CleanDefinition(
        name=clean_name,
        purpose=clean_purpose,
        instruction=clean_instruction,
        read_sets=sets,
        suggestion_kinds=kinds,
        record_type=record_type,
        cleaned=sorted(found),
    )
