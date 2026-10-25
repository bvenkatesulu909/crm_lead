"""Playing whole datasets and estimating what a real-model run would cost (BP-10, step EV5).

``run_suite`` is used by the command-line tool. Every case runs in its own savepoint that is rolled
back afterwards, so the records a case creates (leads, proposals, tickets ...) never pile up and a
database error in one case can't spoil the next. The caller rolls the outer transaction back too.

Scripted run (no model given): every case, strict scoring - the hard CI gate.
Real-model run: only cases marked ``live`` (a case that forces a bad call on purpose is skipped),
lenient scoring - a report, not a gate (docs/agent-evals.md).
"""

import functools
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from agent_evals import play
from agent_evals.cases import Case, dataset_hash, load_cases, substitute
from agent_evals.rag import HashingEmbedder
from agent_evals.rag_cases import RagCase, load_rag_cases, rag_dataset_hash
from agent_evals.runner import ScriptedModel, run_portal_case, run_public_chat_case, run_staff_case
from agent_evals.scoring import CaseResult, Check, Scorecard, build_scorecard
from agent_evals.world import World
from app.modules.assistant.llm import ChatModel, ModelReply

BACKEND = Path(__file__).resolve().parents[1]
CASES_DIR = BACKEND / "evals" / "agents"
RAG_FILE = BACKEND / "evals" / "rag" / "ci_cases.json"

AGENTS = ("staff_assistant", "portal_assistant", "public_chat")
CITED = "cited_answers"
ALL_SUITES = (*AGENTS, CITED)

Progress = Callable[[str], None]


def select_cases(cases: list[Case], *, live_only: bool, only: str | None = None) -> list[Case]:
    return [c for c in cases if (c.live or not live_only) and (only is None or only in c.id)]


def select_rag(cases: list[RagCase], *, live_only: bool, only: str | None = None) -> list[RagCase]:
    return [c for c in cases if (c.live or not live_only) and (only is None or only in c.id)]


def _failed(case_id: str, agent: str, error: Exception) -> CaseResult:
    """A case the model or the database broke on counts as failed - it never aborts the run."""
    return CaseResult(
        case_id, agent, [Check("run", False, f"{type(error).__name__}: {str(error)[:300]}")]
    )


def _in_savepoint(session: Session, fn: Callable[[], CaseResult]) -> CaseResult:
    nested = session.begin_nested()
    try:
        return fn()
    finally:
        if nested.is_active:
            nested.rollback()


def run_suite(
    session: Session,
    world: World,
    *,
    provider: str,
    model: ChatModel | None = None,
    suites: tuple[str, ...] = ALL_SUITES,
    only: str | None = None,
    cases_dir: Path = CASES_DIR,
    rag_file: Path = RAG_FILE,
    progress: Progress | None = None,
) -> dict[str, Scorecard]:
    """One scorecard per suite that has at least one case to play."""
    say = progress or (lambda _line: None)
    live_only = model is not None
    sha = dataset_hash(cases_dir)
    every = load_cases(cases_dir)
    cards: dict[str, Scorecard] = {}
    for agent in (a for a in AGENTS if a in suites):
        chosen = select_cases(
            [c for c in every if c.agent == agent], live_only=live_only, only=only
        )
        if not chosen:
            continue
        results: list[CaseResult] = []
        for case in chosen:

            def play_one(c: Case = case, name: str = agent) -> CaseResult:
                if name == "staff_assistant":
                    return play.play_staff(session, world, c, model=model)[0]
                if name == "portal_assistant":
                    return play.play_portal(session, world, c, model=model)[0]
                return play.play_public(session, world, c, model=model)[0]

            try:
                result = _in_savepoint(session, play_one)
            except Exception as error:  # noqa: BLE001 - one broken case must not stop the run
                result = _failed(case.id, agent, error)
            say(f"{'PASS' if result.passed else 'FAIL'}  {case.id}")
            results.append(result)
        cards[agent] = build_scorecard(results, provider=provider, dataset_sha256=sha)
    if CITED in suites:
        rag_cases = select_rag(load_rag_cases(rag_file), live_only=live_only, only=only)
        if rag_cases:
            embedder = HashingEmbedder()
            play.ingest_corpus(session, world, embedder)
            rag_results: list[CaseResult] = []

            def play_rag_one(c: RagCase) -> CaseResult:
                return play.play_rag(
                    session, world, c, embedder=embedder, ingest=False, model=model
                )[0]

            for rag_case in rag_cases:
                try:
                    result = _in_savepoint(session, functools.partial(play_rag_one, rag_case))
                except Exception as error:  # noqa: BLE001
                    result = _failed(rag_case.id, CITED, error)
                say(f"{'PASS' if result.passed else 'FAIL'}  {rag_case.id}")
                rag_results.append(result)
            cards[CITED] = build_scorecard(
                rag_results, provider=provider, dataset_sha256=rag_dataset_hash(rag_file)
            )
    return cards


# --- what a real-model run would cost -----------------------------------------------------------


class _Probe:
    """Wraps a model and adds up how much text it was sent (system prompt, tool list, messages)."""

    available = True

    def __init__(self, inner: ChatModel) -> None:
        self._inner = inner
        self.calls = 0
        self.chars = 0
        self.reply_chars = 0

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        self.calls += 1
        self.chars += (
            len(system)
            + len(json.dumps(tools, default=str))
            + len(json.dumps(messages, default=str))
        )
        reply = self._inner.reply(system=system, messages=messages, tools=tools)
        self.reply_chars += len(reply.text or "") + sum(
            len(json.dumps(u.input, default=str)) + len(u.name) for u in reply.tool_uses
        )
        return reply


@dataclass(frozen=True)
class Estimate:
    cases: int
    model_calls: int
    input_tokens: int
    output_tokens: int
    input_usd: float
    output_usd: float

    @property
    def total_usd(self) -> float:
        return self.input_usd + self.output_usd


# A real model usually reads a little more than the script does, and writes longer answers.
CALL_FACTOR = 2.0
CHARS_PER_TOKEN = 4  # a rough rule for English text and JSON
MIN_ANSWER_TOKENS = 120  # what even a short answer costs


def estimate_cost(
    session: Session,
    world: World,
    *,
    price_in_per_million: float,
    price_out_per_million: float,
    only: str | None = None,
    cases_dir: Path = CASES_DIR,
    rag_file: Path = RAG_FILE,
) -> Estimate:
    """Play the live cases once with the script, measure what would be sent to a model in each
    call, and scale by ``CALL_FACTOR``. An estimate, not a promise: it is an upper-ish guess."""
    calls = chars = reply_chars = 0
    chosen = select_cases(load_cases(cases_dir), live_only=True, only=only)
    for case in chosen:

        def play_one(c: Case = case) -> CaseResult:
            nonlocal calls, chars, reply_chars
            probe = _Probe(ScriptedModel(c.script))
            ready = substitute(c, world.placeholders(c.persona))
            if c.agent == "staff_assistant":
                run_staff_case(session, world.principal(c.persona), ready, model=probe)
            elif c.agent == "portal_assistant":
                run_portal_case(session, world.principal(c.persona), ready, model=probe)
            else:
                run_public_chat_case(session, play.public_chat_settings(world), ready, model=probe)
            calls += probe.calls
            chars += probe.chars
            reply_chars += probe.reply_chars
            return CaseResult(c.id, c.agent, [])

        _in_savepoint(session, play_one)
    rag_cases = select_rag(load_rag_cases(rag_file), live_only=True, only=only)
    # A cited answer sends the question and the retrieved passages once: about 1,500 tokens.
    rag_calls = len(rag_cases)
    rag_chars = rag_calls * 1500 * CHARS_PER_TOKEN
    total_calls = calls + rag_calls
    input_tokens = int((chars + rag_chars) / CHARS_PER_TOKEN * CALL_FACTOR)
    output_tokens = int(
        max(reply_chars / CHARS_PER_TOKEN, total_calls * MIN_ANSWER_TOKENS) * CALL_FACTOR
    )
    return Estimate(
        cases=len(chosen) + len(rag_cases),
        model_calls=int(total_calls * CALL_FACTOR),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_usd=input_tokens / 1_000_000 * price_in_per_million,
        output_usd=output_tokens / 1_000_000 * price_out_per_million,
    )
