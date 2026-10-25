"""The format of a cited-answer case and its loader (BP-10, step EV4).

A RAG case asks the real grounded-answer pipeline a question against a small fictional document
set. A scripted model answers and cites documents BY TITLE (``{cite:Returns policy}``); the
pipeline decides the source numbers. Case files live in ``backend/evals/rag/ci_cases.json``.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

RagOutcome = Literal["answered", "not_found", "ungrounded"]
RagPersona = Literal["sales_agent", "sales_manager", "customer", "beta_agent"]

CITE = re.compile(r"\{cite:([^{}]*)\}")


class RagCaseFileError(ValueError):
    """A RAG case file can't be used; the message names the file."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RagExpect(_Strict):
    # answered: the pipeline returned a cited answer; not_found: nothing close enough, the model
    # is not called; ungrounded: the model answered but the answer was not properly cited.
    outcome: RagOutcome
    model_called: bool
    cited_documents: list[str] = Field(default_factory=list)
    forbidden_documents: list[str] = Field(default_factory=list)
    expected_facts: list[str] = Field(default_factory=list)
    forbidden_facts: list[str] = Field(default_factory=list)
    injection: bool = False
    # What the existing answer metrics must say. "fail" marks a negative control: an answer that
    # follows a poisoned instruction, which the metrics have to catch.
    score: Literal["pass", "fail"] = "pass"

    @model_validator(mode="after")
    def _consistent(self) -> "RagExpect":
        if self.outcome != "answered" and (
            self.cited_documents
            or self.expected_facts
            or self.forbidden_facts
            or self.injection
            or self.score != "pass"
        ):
            raise ValueError(
                f"{self.outcome}: nothing is cited or scored when the pipeline refuses to answer"
            )
        if self.outcome == "not_found" and self.model_called:
            raise ValueError("not_found: the model is never called when nothing is found")
        if self.outcome != "not_found" and not self.model_called:
            raise ValueError(f"{self.outcome}: the model must have been called")
        return self


class RagCase(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,60}$")
    description: str = Field(min_length=1, max_length=300)
    question: str = Field(min_length=1, max_length=2000)
    persona: RagPersona = Field(alias="as")
    # What the scripted model says; "{cite:Title}" becomes the number of that source.
    answer: str = Field(default="", max_length=2000)
    # False: the scripted answer is deliberately bad (uncited, invented number, obeys a poisoned
    # document). A real model is not run on it.
    live: bool = True
    expect: RagExpect

    @model_validator(mode="after")
    def _citations_are_well_formed(self) -> "RagCase":
        marks = self.answer.count("{cite:")
        found = [title for title in CITE.findall(self.answer)]
        if marks != len(found) or any(not title.strip() for title in found):
            raise ValueError("answer: write citations as {cite:Document title}")
        return self


class _RagFile(_Strict):
    version: Literal[1]
    cases: list[RagCase]


def _describe(path: Path, exc: ValidationError) -> RagCaseFileError:
    problems = [
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
    ]
    return RagCaseFileError(f"{path.name}: " + "; ".join(problems))


def load_rag_cases(path: Path) -> list[RagCase]:
    """Every case of the file, sorted by id."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RagCaseFileError(f"{path.name}: not valid JSON ({exc})") from exc
    try:
        loaded = _RagFile.model_validate(raw)
    except ValidationError as exc:
        raise _describe(path, exc) from exc
    seen: set[str] = set()
    for case in loaded.cases:
        if case.id in seen:
            raise RagCaseFileError(f"{path.name}: duplicate case id '{case.id}'")
        seen.add(case.id)
    return sorted(loaded.cases, key=lambda c: c.id)


def rag_dataset_hash(path: Path) -> str:
    """SHA-256 of the cases themselves (not of formatting)."""
    payload = json.dumps(
        [case.model_dump(mode="json", by_alias=True) for case in load_rag_cases(path)],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
