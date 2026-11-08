"""The case format and the loader (BP-10, step EV1).

A case is a small fixed conversation with expectations (docs/agent-evals.md). Case files live in
``backend/evals/agents/*.json``; each is ``{"version": 1, "cases": [...]}``. Everything is
checked when the files are loaded: unknown fields, wrong values, a typo in a tool name, a
broken matcher or a malformed placeholder stop the load with a message naming the file.

Placeholders like ``{{lead.own}}`` stand for records of the fictional test world; a runner
replaces them with real ids before a run (``substitute``).
"""

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from agent_evals.matchers import MatcherError, compile_matcher

Agent = Literal[
    "staff_assistant",
    "portal_assistant",
    "public_chat",
    "qualifier",
    "lead_agent",
    "deal_desk",
    "account_research",
]
# The deal desk asks four models in one run (ADR 0024): each step of its script says which one
# answers. Three reviewers run at the same time, so the order they are asked in is not fixed.
DeskRole = Literal["pricing", "account", "momentum", "lead"]
Persona = Literal[
    "sales_agent", "sales_manager", "tenant_admin", "support_agent", "customer", "visitor"
]
# How a whole conversation ended, as seen by the person.
Outcome = Literal[
    "answered",
    "proposal_pending",
    "refused",
    "not_found",
    "lead_saved",
    "nothing_changed",
    # Stopped by the agent registry (ADR 0016) before any model call. The website chat shows the
    # same "resting" sentence for both reasons, so it always reports "agent_off".
    "agent_off",
    "over_budget",
]
# How the CRM answered one tool call.
CallOutcome = Literal["ok", "refused", "not_found"]

Message = Annotated[str, StringConstraints(min_length=1, max_length=2000)]

PERSONAS: dict[str, set[str]] = {
    "staff_assistant": {"sales_agent", "sales_manager", "tenant_admin", "support_agent"},
    "portal_assistant": {"customer"},
    "public_chat": {"visitor"},
    # A support agent has no Qualifier permission, so it is not a persona here.
    "qualifier": {"sales_agent", "sales_manager", "tenant_admin"},
    # The same people as the Qualifier may ask the lead agent (ADR 0022).
    "lead_agent": {"sales_agent", "sales_manager", "tenant_admin"},
    # ADR 0024: the deal desk is for sales; account research also for support.
    "deal_desk": {"sales_agent", "sales_manager", "tenant_admin"},
    "account_research": {"sales_agent", "sales_manager", "tenant_admin", "support_agent"},
}
# After these outcomes nothing in the CRM has changed (or may only wait for approval): the
# answer must not claim otherwise.
WAITING_OUTCOMES = ("proposal_pending", "nothing_changed")

_PLACEHOLDER = re.compile(r"\{\{(.*?)\}\}")
_PLACEHOLDER_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")


class CaseFileError(ValueError):
    """A case file can't be used; the message names the file."""


class PlaceholderError(ValueError):
    """A placeholder in a case has no value in the world."""


def known_tools(agent: str) -> set[str]:
    """The tools this agent really has (imported lazily: the loader needs the app)."""
    if agent == "staff_assistant":
        from app.modules.assistant import staff_tools

        return set(staff_tools.TOOLS)
    if agent == "portal_assistant":
        from app.modules.assistant import tools

        return set(tools.TOOLS)
    if agent == "public_chat":
        from app.modules.public_chat import rules

        return {str(rules.SAVE_LEAD_TOOL["name"])}
    if agent == "qualifier":
        from app.modules.qualifier import rules as qualifier_rules

        return {qualifier_rules.TOOL_NAME}
    if agent == "lead_agent":
        from app.modules.lead_agent import rules as lead_agent_rules

        return {lead_agent_rules.TOOL_NAME}
    if agent == "deal_desk":
        from app.modules.deal_desk import review

        return {review.FINDINGS_TOOL, review.BRIEF_TOOL}
    if agent == "account_research":
        from app.modules.deal_desk import research_rules

        return {research_rules.TOOL}
    raise CaseFileError(f"unknown agent {agent!r}")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScriptedCall(_Strict):
    """A tool call the scripted model makes."""

    name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)


class Step(_Strict):
    """One reply of the scripted model: some words and/or some tool calls."""

    say: str = Field(default="", max_length=2000)
    calls: list[ScriptedCall] = Field(default_factory=list)
    # Deal desk only: which of its models gives this reply (each role's steps are used in order).
    role: DeskRole | None = None


class ExpectedCall(_Strict):
    name: str = Field(min_length=1, max_length=80)
    # Plain values (must be equal) or one-key matchers; see agent_evals.matchers.
    arguments: dict[str, Any] = Field(default_factory=dict)
    outcome: CallOutcome = "ok"

    @model_validator(mode="after")
    def _matchers_are_valid(self) -> "ExpectedCall":
        for name, spec in self.arguments.items():
            try:
                compile_matcher(spec)
            except MatcherError as exc:
                raise ValueError(f"{name}: {exc}") from exc
        return self


class Governance(_Strict):
    """How the organisation has set the agent up for this case (ADR 0016). Applied inside a
    savepoint that is rolled back after the case, so no case leaks into the next."""

    enabled: bool = True
    monthly_token_budget: int | None = Field(default=None, ge=1)
    tokens_used: int = Field(default=0, ge=0)
    # None = every tool; a list (maybe empty) = only these.
    allowed_tools: list[str] | None = None
    # The platform-wide switch (CRM_AI_DISABLED).
    platform_disabled: bool = False


class QualifierSetup(_Strict):
    """What the organisation has written for the Qualifier in this case (docs/qualifier.md).

    The standard procedure has three steps, so ``matched_steps`` 1-3 exist in a case. The lead
    agent, which judges a lead by the same written steps, plays with ``lead_agent`` steps that its
    fictional leads can be judged by. Applied inside a savepoint that is rolled back, like
    ``governance``."""

    procedure: Literal["standard", "lead_agent", "none"] = "standard"
    # The OTHER organisation has a procedure of its own; ours must never use it.
    other_organisation_procedure: bool = False


class WebcheckSetup(_Strict):
    """How the web check (ADR 0019) is set up for a staff-assistant case. Without it the
    assistant plays with no web check settings at all, as before. Applied inside the case's
    savepoint, so nothing leaks into the next case."""

    # "demo": the fictional demo registry is switched on; "none": no source is switched on.
    sources: Literal["demo", "none"] = "demo"
    # The organisation's switch in the agent registry (entry "web_check").
    enabled: bool = True
    # The platform switch CRM_WEBCHECK_DISABLED.
    platform_disabled: bool = False
    # After the conversation, run the lookups it queued against the demo registry (the real
    # fetcher and parser; only the network is replaced), so the stored evidence can be checked.
    run_jobs: bool = False


class ExpectedEvidence(_Strict):
    """What the lookups a case queued must have stored (``webcheck.run_jobs``)."""

    verdicts: list[Literal["found", "not_found", "unclear", "error"]] = Field(min_length=1)
    # Texts that must never reach the stored evidence (the page's links, pictures, hidden text).
    must_not_contain: list[str] = Field(default_factory=list)
    # Kinds of finding the cleaning must have reported (e.g. "link", "instruction_phrase").
    cleaned: list[str] = Field(default_factory=list)


class ExpectedProposal(_Strict):
    """One proposal the case must have made (kind and payload, matchers as for tool arguments)."""

    kind: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _matchers_are_valid(self) -> "ExpectedProposal":
        for name, spec in self.payload.items():
            try:
                compile_matcher(spec)
            except MatcherError as exc:
                raise ValueError(f"{name}: {exc}") from exc
        return self


class Expect(_Strict):
    tools: list[ExpectedCall] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    outcome: Outcome
    answer_must_contain: list[str] = Field(default_factory=list)
    answer_must_not_contain: list[str] = Field(default_factory=list)
    max_tool_calls: int | None = Field(default=None, ge=0, le=20)
    # True: calls may not carry arguments the case didn't list (e.g. a made-up tenant_id).
    strict_args: bool = False
    # True / False: whether the model must / must not have been called at all (a refused agent
    # never reaches it). None: not checked.
    model_called: bool | None = None
    # The warning codes (the Sentinel, ADR 0017) the proposals made in this case must carry, all
    # together. [] = none; None = not checked.
    safety_warnings: list[str] | None = None
    # Website chat only (ADR 0018): texts that must / must not be in what the chat stored in
    # the CRM (the lead's fields and its timeline), after the door cleaned it.
    stored_must_contain: list[str] = Field(default_factory=list)
    stored_must_not_contain: list[str] = Field(default_factory=list)
    # Qualifier and lead agent only: exactly the proposals the case made, in order ([] = none).
    # None: not checked.
    proposals: list[ExpectedProposal] | None = None
    # Staff assistant with ``webcheck`` only: how many web checks the conversation queued, and
    # what their stored evidence must look like. None: not checked.
    webchecks_queued: int | None = Field(default=None, ge=0, le=5)
    evidence: ExpectedEvidence | None = None
    # Deal desk only: how each reviewer's answer was judged in the stored review. None: not
    # checked.
    reviewers: dict[Literal["pricing", "account", "momentum"], Literal["answered", "refused"]] | (
        None
    ) = None
    # Account research only: how many sentences the stored brief kept, and how many were removed
    # for citing nothing gathered. None: not checked.
    brief_sentences: int | None = Field(default=None, ge=0, le=8)
    dropped_sentences: int | None = Field(default=None, ge=0, le=20)

    @model_validator(mode="after")
    def _warnings_are_warnings(self) -> "Expect":
        if self.safety_warnings:
            from app.modules.approvals.sentinel import WARNING_CODES

            unknown = sorted(set(self.safety_warnings) - WARNING_CODES)
            if unknown:
                raise ValueError(
                    f"safety_warnings: {unknown} are not warning codes of the Sentinel"
                )
        return self


def _strings(value: Any) -> list[str]:
    """Every text inside a JSON-like value."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,60}$")
    description: str = Field(min_length=1, max_length=300)
    agent: Agent
    persona: Persona = Field(alias="as")
    # For the qualifier each message is the lead to assess (a placeholder such as {{lead.rich}}):
    # the Qualifier is asked about one lead at a time, it is not a chat.
    messages: list[Message] = Field(min_length=1, max_length=5)
    # Staff assistant (ADR 0023): "voice" asks for a short answer to be read aloud. Several
    # messages, or voice, play one remembered conversation with streamed answers.
    mode: Literal["text", "voice"] = "text"
    # False: the case forces a bad call on purpose to see the CRM refuse it, so a real model
    # (which is not expected to make that call) is not run on it. Scripted runs always are.
    live: bool = True
    # How the agent is set up in the registry; absent = the defaults (on, standard budget).
    governance: Governance | None = None
    # Qualifier and lead agent: which procedure the organisation has. Absent = the standard one
    # (the Qualifier) or the lead-agent steps (the lead agent).
    qualifier: QualifierSetup | None = None
    # Staff assistant: how the web check is set up (ADR 0019). Absent = no web check settings.
    webcheck: WebcheckSetup | None = None
    script: list[Step] = Field(default_factory=list)
    expect: Expect

    @model_validator(mode="after")
    def _consistent(self) -> "Case":
        if self.persona not in PERSONAS[self.agent]:
            raise ValueError(
                f"as: a {self.persona} can't use the {self.agent} (allowed: "
                f"{', '.join(sorted(PERSONAS[self.agent]))})"
            )
        if self.agent != "public_chat" and (
            self.expect.stored_must_contain or self.expect.stored_must_not_contain
        ):
            raise ValueError("expect.stored_*: only the website chat stores text in the CRM")
        if self.mode == "voice" and self.agent != "staff_assistant":
            raise ValueError("mode: voice is only for the staff assistant")
        if self.agent not in ("qualifier", "lead_agent") and self.qualifier:
            raise ValueError("qualifier: only for the qualifier and the lead agent")
        if (
            self.agent not in ("qualifier", "lead_agent", "deal_desk")
            and self.expect.proposals is not None
        ):
            raise ValueError("expect.proposals: only for the qualifier, lead agent and deal desk")
        roles = [step.role for step in self.script]
        if self.agent == "deal_desk" and any(role is None for role in roles):
            raise ValueError("script: every deal desk step must say which role answers")
        if self.agent != "deal_desk" and any(role is not None for role in roles):
            raise ValueError("script: role is only for the deal desk")
        if self.agent != "deal_desk" and self.expect.reviewers is not None:
            raise ValueError("expect.reviewers: only for the deal desk")
        if self.agent != "account_research" and (
            self.expect.brief_sentences is not None or self.expect.dropped_sentences is not None
        ):
            raise ValueError("expect.brief_sentences / dropped_sentences: only account research")
        if self.webcheck is not None and self.agent != "staff_assistant":
            raise ValueError("webcheck: only the staff assistant can ask for a web check")
        if self.webcheck is None and (
            self.expect.webchecks_queued is not None or self.expect.evidence is not None
        ):
            raise ValueError("expect.webchecks_queued / evidence: the case needs a webcheck setup")
        if self.expect.evidence is not None and not (self.webcheck and self.webcheck.run_jobs):
            raise ValueError("expect.evidence: set webcheck.run_jobs so the lookups run")
        real = known_tools(self.agent)
        if self.governance and self.governance.allowed_tools:
            unknown = set(self.governance.allowed_tools) - real
            if unknown:
                raise ValueError(
                    f"governance.allowed_tools: {sorted(unknown)} are not tools of {self.agent}"
                )
        expected = {call.name: call.outcome for call in self.expect.tools}
        for step in self.script:
            for call in step.calls:
                # A made-up tool is how a case checks that the CRM refuses it - but the case
                # must say so, otherwise a typo would pass unnoticed.
                if call.name not in real and expected.get(call.name) != "refused":
                    raise ValueError(
                        f"script: '{call.name}' is not a tool of {self.agent}; if the CRM "
                        "should refuse it, list it in expect.tools with outcome 'refused'"
                    )
        for wanted_call in self.expect.tools:
            if wanted_call.name not in real and wanted_call.outcome != "refused":
                raise ValueError(
                    f"expect.tools: '{wanted_call.name}' is not a tool of {self.agent}; only a "
                    "call that must be refused may name a tool that doesn't exist"
                )
        for text in _strings(self.model_dump(by_alias=True)):
            for found in _PLACEHOLDER.findall(text):
                if not _PLACEHOLDER_NAME.match(found):
                    raise ValueError(
                        f"bad placeholder '{{{{{found}}}}}': use lowercase names such as "
                        "{{lead.own}}"
                    )
        return self


class _CaseFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    cases: list[Case]


# --- loading ------------------------------------------------------------------------------------


def _describe(path: Path, exc: ValidationError) -> CaseFileError:
    problems = [
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
    ]
    return CaseFileError(f"{path.name}: " + "; ".join(problems))


def load_cases(directory: Path) -> list[Case]:
    """Every case of every ``*.json`` file in the directory, sorted by id.

    Raises CaseFileError (naming the file) for anything wrong, including a duplicate id."""
    seen: dict[str, str] = {}
    cases: list[Case] = []
    for path in sorted(directory.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CaseFileError(f"{path.name}: not valid JSON ({exc})") from exc
        try:
            loaded = _CaseFile.model_validate(raw)
        except ValidationError as exc:
            raise _describe(path, exc) from exc
        for case in loaded.cases:
            if case.id in seen:
                raise CaseFileError(
                    f"duplicate case id '{case.id}' in {seen[case.id]} and {path.name}"
                )
            seen[case.id] = path.name
            cases.append(case)
    return sorted(cases, key=lambda c: c.id)


def dataset_hash(directory: Path) -> str:
    """SHA-256 of the cases themselves (not of file names or formatting), so a scorecard says
    exactly which version of the questions it answered."""
    payload = json.dumps(
        [case.model_dump(mode="json", by_alias=True) for case in load_cases(directory)],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --- placeholders ----


def _fill(value: Any, world: Mapping[str, str]) -> Any:
    if isinstance(value, str):

        def replace(found: re.Match[str]) -> str:
            name = found.group(1)
            if name not in world:
                raise PlaceholderError(f"placeholder '{{{{{name}}}}}' has no value in the world")
            return world[name]

        return _PLACEHOLDER.sub(replace, value)
    if isinstance(value, dict):
        return {key: _fill(item, world) for key, item in value.items()}
    if isinstance(value, list):
        return [_fill(item, world) for item in value]
    return value


def substitute(case: Case, world: Mapping[str, str]) -> Case:
    """A copy of the case with every ``{{name}}`` replaced by the world's value."""
    return Case.model_validate(_fill(case.model_dump(by_alias=True), world))
