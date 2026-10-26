"""Sentinel: a rule-based second check on an AI proposal (ADR 0017, step SN1).

Every rule is a plain function that is given FACTS (counts, the record's current state, the
record's own text) and returns findings; reading those facts from the database is the next
step. No rule calls a model or the network, so a prompt injection that fooled the proposing
model has no effect here.

A finding is a ``block`` (the proposal is refused) or a ``warn`` (it is stored and the approver
sees "Check this: ..."). A finding never repeats the text it found. A rule that raises makes
the whole verdict a block (``sentinel_error``): the Sentinel fails closed.
"""

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.screening import find_instructions, screen

logger = logging.getLogger(__name__)

Severity = Literal["block", "warn"]
STORED_VERSION = 1

WORD_MESSAGES = {
    "link": "The text contains a link. Describe it in words instead.",
    "email_address": "The text contains an e-mail address. Describe it in words instead.",
    "html_markup": "The text contains HTML markup.",
    "external_image": "The text contains an image from outside.",
    "hidden_characters": "The text contains invisible characters.",
    "control_characters": "The text contains control characters.",
    "instruction_phrase": "The text contains words that read like instructions to an AI.",
    "repeated_text": "The text repeats itself many times.",
}


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    message: str


@dataclass(frozen=True)
class Limits:
    """The thresholds (settings, not constants)."""

    proposals_per_hour: int
    assignments_per_hour: int
    # A record that already has this many proposals today, counting the new one, is "busy".
    busy_record_per_day: int


@dataclass(frozen=True)
class Candidate:
    """The proposal as it will be stored."""

    kind: str
    reason: str
    payload: dict[str, Any]
    requester_id: uuid.UUID
    tenant_id: uuid.UUID


@dataclass(frozen=True)
class Facts:
    """What the database says about the record and the asker. Read by the caller (step SN2)."""

    record_tenant_id: uuid.UUID
    assignee_tenant_id: uuid.UUID | None
    lead_status: str | None
    lead_owner_id: uuid.UUID | None
    proposals_last_hour: int
    assignments_last_hour: int
    same_record_today: int
    identical_pending: bool
    record_texts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Verdict:
    findings: list[Finding]
    checked: list[str]

    @property
    def blocks(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "block"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warn"]

    @property
    def blocked(self) -> bool:
        return bool(self.blocks)

    def to_json(self) -> dict[str, Any]:
        """What is stored with an accepted proposal: rule groups and warnings, no record text."""
        return {
            "version": STORED_VERSION,
            "checked": list(self.checked),
            "warnings": [{"code": f.code, "message": f.message} for f in self.warnings],
        }


# --- the words ---------------------------------------------------------------------------------

_PHONE = re.compile(r"(?<!\d)\+?\d[\d\s-]{8,}\d(?!\d)")
_NOT_TEXT_KEYS = {"status"}


def _texts(candidate: Candidate) -> list[str]:
    texts = [candidate.reason]
    for key, value in candidate.payload.items():
        if isinstance(value, str) and not key.endswith("_id") and key not in _NOT_TEXT_KEYS:
            texts.append(value)
    return texts


def check_words(candidate: Candidate) -> list[Finding]:
    found: dict[str, Finding] = {}
    phone = False
    for text in _texts(candidate):
        for finding in screen(text).findings:
            found.setdefault(
                finding.code,
                Finding(finding.code, "block", WORD_MESSAGES.get(finding.code, finding.message)),
            )
        phone = phone or bool(_PHONE.search(text))
    findings = list(found.values())
    if phone:
        findings.append(
            Finding("phone_number", "warn", "The text contains what looks like a phone number.")
        )
    return findings


# --- the pattern -------------------------------------------------------------------------------


def check_pattern(candidate: Candidate, facts: Facts, limits: Limits) -> list[Finding]:
    findings: list[Finding] = []
    if facts.identical_pending:
        findings.append(
            Finding("duplicate_pending", "block", "The same proposal is already waiting.")
        )
    if facts.proposals_last_hour >= limits.proposals_per_hour:
        findings.append(
            Finding(
                "too_many_proposals",
                "block",
                "Too many proposals in the last hour. Wait for a decision on the earlier ones.",
            )
        )
    if (
        candidate.kind == "lead.assign"
        and facts.assignments_last_hour >= limits.assignments_per_hour
    ):
        findings.append(
            Finding(
                "too_many_assignments",
                "block",
                "Too many lead assignments proposed in the last hour.",
            )
        )
    if facts.same_record_today + 1 >= limits.busy_record_per_day:
        findings.append(
            Finding("busy_record", "warn", "Several proposals were made for this record today.")
        )
    return findings


# --- the state of the record -------------------------------------------------------------------


def check_state(candidate: Candidate, facts: Facts) -> list[Finding]:
    findings: list[Finding] = []
    payload = candidate.payload
    if candidate.kind in ("lead.set_status", "lead.assign"):
        if facts.lead_status == "converted":
            findings.append(
                Finding(
                    "lead_converted", "block", "This lead is already converted; leave it as it is."
                )
            )
        elif candidate.kind == "lead.set_status":
            if payload.get("status") == facts.lead_status:
                findings.append(
                    Finding("status_unchanged", "block", "The lead already has this status.")
                )
            elif facts.lead_status == "qualified" and payload.get("status") == "unqualified":
                findings.append(
                    Finding(
                        "downgrade_qualified", "warn", "This moves a qualified lead to unqualified."
                    )
                )
        elif candidate.kind == "lead.assign":
            owner = facts.lead_owner_id
            if owner is not None and owner != candidate.requester_id:
                findings.append(
                    Finding("lead_owned_by_other", "warn", "Someone else owns this lead.")
                )
    elif candidate.kind == "activity.create_task":
        assignee = payload.get("assignee_id")
        if assignee and str(assignee) != str(candidate.requester_id):
            findings.append(
                Finding("task_for_other", "warn", "The task is for someone other than the asker.")
            )
    return findings


# --- tenant ------------------------------------------------------------------------------------


def check_tenant(candidate: Candidate, facts: Facts) -> list[Finding]:
    """The database already keeps organisations apart; this is the second, explicit check."""
    findings: list[Finding] = []
    if facts.record_tenant_id != candidate.tenant_id:
        findings.append(
            Finding("tenant_mismatch", "block", "The record belongs to another organisation.")
        )
    if facts.assignee_tenant_id is not None and facts.assignee_tenant_id != candidate.tenant_id:
        findings.append(
            Finding("tenant_mismatch", "block", "The person belongs to another organisation.")
        )
    return findings


# --- the record's own text ---------------------------------------------------------------------


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def check_record_text(candidate: Candidate, facts: Facts) -> list[Finding]:
    findings: dict[str, Finding] = {}
    snippets: list[str] = []
    for text in facts.record_texts:
        result = screen(text)
        codes = {f.code for f in result.findings}
        if "instruction_phrase" in codes:
            snippets.extend(find_instructions(text))
            findings.setdefault(
                "record_contains_instruction",
                Finding(
                    "record_contains_instruction",
                    "warn",
                    "This record contains text that looks like an instruction to an AI.",
                ),
            )
        if codes & {"hidden_characters", "control_characters"}:
            findings.setdefault(
                "record_contains_hidden_text",
                Finding(
                    "record_contains_hidden_text",
                    "warn",
                    "This record contains invisible characters.",
                ),
            )
        if codes & {"link", "external_image"}:
            findings.setdefault(
                "record_contains_link",
                Finding("record_contains_link", "warn", "This record contains a link."),
            )
    reason = _squash(screen(candidate.reason).clean)
    if any(_squash(snippet) in reason for snippet in snippets):
        findings["reason_repeats_record_instruction"] = Finding(
            "reason_repeats_record_instruction",
            "block",
            "The reason repeats an instruction found inside the record.",
        )
    return list(findings.values())


# --- the verdict -------------------------------------------------------------------------------


def verify(candidate: Candidate, facts: Facts, limits: Limits, *, recheck: bool = False) -> Verdict:
    """Run the rules. ``recheck`` (at approval) runs only the ones about the record's state."""
    findings: list[Finding] = []
    checked: list[str] = []
    groups: list[tuple[str, Any]] = []
    if not recheck:
        groups.append(("words", lambda: check_words(candidate)))
        groups.append(("pattern", lambda: check_pattern(candidate, facts, limits)))
    groups.append(("state", lambda: check_state(candidate, facts)))
    groups.append(("tenant", lambda: check_tenant(candidate, facts)))
    if not recheck:
        groups.append(("record_text", lambda: check_record_text(candidate, facts)))
    for name, run in groups:
        checked.append(name)
        try:
            findings.extend(run())
        except Exception as error:  # noqa: BLE001 - fail closed, whatever went wrong
            logger.error("sentinel rule group %s failed (%s)", name, type(error).__name__)
            findings.append(
                Finding(
                    "sentinel_error",
                    "block",
                    "The safety check could not be completed, so the proposal was not accepted.",
                )
            )
    return Verdict(findings, checked)
