"""Playing cited-answer cases through the real grounded-answer pipeline (BP-10, step EV4).

Everything except two things is real: the chunks in the database, the vector and keyword search,
the visibility rules, the numbered sources, the citation check and the refusals. Replaced are
the embedding model (a small deterministic hashing embedder - no download, no key) and the
language model (a script). Answers are scored with the project's existing deterministic metrics
(``app.modules.knowledge.evaluation``).
"""

import hashlib
import math
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from agent_evals.rag_cases import CITE, RagCase
from agent_evals.scoring import CaseResult, Check
from app.core.auth.principal import Principal
from app.core.config import Settings
from app.core.storage import MemoryFileStore, object_key
from app.modules.assistant.llm import ModelReply
from app.modules.knowledge import answers, service
from app.modules.knowledge.answers import AnswerOutcome
from app.modules.knowledge.evaluation import STOPWORDS, score_answer
from app.modules.knowledge.models import KnowledgeDocument

DIMENSIONS = 384
# Question words that carry no topic; dropped so a question and a document compare on content.
_QUESTION_WORDS = frozenset(
    "do does did can could should would many much long need get take new".split()
)
_WORD = re.compile(r"[a-z0-9%]+")
MISSING_CITATION = 99  # a title that is not among the sources: an invalid number on purpose


def _stem(word: str) -> str:
    """A light, deterministic stemmer: returns -> return, damaged -> damag, items -> item."""
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _words(text: str) -> list[str]:
    return [
        _stem(w)
        for w in _WORD.findall(text.lower())
        if len(w) > 1 and w not in STOPWORDS and w not in _QUESTION_WORDS
    ]


class HashingEmbedder:
    """A deterministic bag-of-words embedder: each word adds to one of 384 slots (by a hash), and
    the vector is scaled to length 1, so the dot product of two texts is their word overlap.
    Not a good language model - a stable stand-in so CI needs no model download."""

    model_name = "eval-hashing-384"
    dimensions = DIMENSIONS

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * DIMENSIONS
        for word in _words(text) or ["<empty>"]:
            slot = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big") % DIMENSIONS
            vector[slot] += 1.0
        norm = math.sqrt(sum(x * x for x in vector))
        return [x / norm for x in vector]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


# --- citing by title ------------------------------------------------------------------------------


def _numbered_sources(prompt: str) -> dict[int, str]:
    """{number: "Title" or "Title - heading"} from the pipeline's prompt ("[1] Title ...")."""
    return {
        int(number): rest.strip()
        for number, rest in re.findall(r"^\[(\d{1,2})\] (.+)$", prompt, flags=re.MULTILINE)
    }


def resolve_citations(answer: str, prompt: str) -> str:
    """Replace ``{cite:Title}`` with ``[n]``: the number the pipeline gave that document."""
    sources = _numbered_sources(prompt)

    def number_for(found: re.Match[str]) -> str:
        title = found.group(1).strip()
        exact = [n for n, line in sources.items() if line == title]
        prefixed = [n for n, line in sources.items() if line.startswith(title + " - ")]
        picked = (exact or prefixed or [MISSING_CITATION])[0]
        return f"[{picked}]"

    return CITE.sub(number_for, answer)


class ScriptedAnswerModel:
    """Answers with the case's text, citing by the numbers the pipeline actually used."""

    available = True

    def __init__(self, answer: str) -> None:
        self._answer = answer
        self.calls = 0

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        self.calls += 1
        return ModelReply(resolve_citations(self._answer, str(messages[0]["content"])))


# --- documents ------------------------------------------------------------------------------------


def ingest_documents(
    session: Session,
    embedder: HashingEmbedder,
    tenant_id: uuid.UUID,
    documents: Sequence[tuple[str, str, str, str]],
) -> None:
    """Index fictional documents: (title, file name, text, visibility) each, for one tenant."""
    store = MemoryFileStore()
    for title, file_name, text, visibility in documents:
        data = text.encode("utf-8")
        document_id = uuid.uuid4()
        key = object_key(tenant_id, "knowledge", document_id, document_id)
        store.put(key, data, "text/markdown")
        session.add(
            KnowledgeDocument(
                id=document_id,
                tenant_id=tenant_id,
                title=title,
                file_name=file_name,
                content_type="text/markdown",
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                storage_key=key,
                status="processing",
                page_count=0,
                visibility=visibility,
                created_by_user_id=None,
            )
        )
        session.flush()
        service.ingest_document(
            session, store, embedder, tenant_id=tenant_id, document_id=document_id
        )
    session.flush()


# --- running and scoring a case -------------------------------------------------------------


@dataclass(frozen=True)
class RagRun:
    outcome: AnswerOutcome
    model_calls: int


def run_rag_case(
    session: Session,
    principal: Principal,
    case: RagCase,
    *,
    embedder: HashingEmbedder,
    settings: Settings,
    account_ids: Sequence[uuid.UUID] | None = None,
) -> RagRun:
    model = ScriptedAnswerModel(case.answer)
    outcome = answers.answer_question(
        session,
        principal,
        embedder,
        model,
        question=case.question,
        settings=settings,
        reranker=None,
        account_ids=account_ids,
    )
    return RagRun(outcome, model.calls)


def outcome_of(outcome: AnswerOutcome) -> str:
    """The pipeline's result in the words of a case."""
    if not outcome.model_used:
        return "not_found"
    return "answered" if outcome.grounded else "ungrounded"


def score_rag_case(case: RagCase, outcome: AnswerOutcome, *, model_calls: int) -> CaseResult:
    expect = case.expect
    actual = outcome_of(outcome)
    checks = [
        Check(
            "outcome",
            actual == expect.outcome,
            "" if actual == expect.outcome else f"expected {expect.outcome!r}, got {actual!r}",
        ),
        Check(
            "model_called",
            (model_calls > 0) == expect.model_called,
            ""
            if (model_calls > 0) == expect.model_called
            else f"model called {model_calls} time(s)",
        ),
    ]
    titles = [source.document_title for source in outcome.sources]
    if expect.cited_documents:
        cited = {
            outcome.sources[n - 1].document_title for n in outcome.citations if n <= len(titles)
        }
        missing = [t for t in expect.cited_documents if t not in cited]
        checks.append(
            Check(
                "cited_documents",
                not missing,
                f"not cited: {missing}; cited: {sorted(cited)}; sources: {titles}"
                if missing
                else "",
            )
        )
    if expect.forbidden_documents:
        leaked = [t for t in expect.forbidden_documents if t in titles]
        checks.append(
            Check(
                "forbidden_documents", not leaked, f"among the sources: {leaked}" if leaked else ""
            )
        )
    if expect.outcome == "answered":
        scored = score_answer(
            outcome.answer,
            [source.text for source in outcome.sources],
            expected_facts=expect.expected_facts,
            forbidden_facts=expect.forbidden_facts,
        )
        # Safety cases are judged on behaviour, not on citation style (the same rule as the live
        # evaluation, scripts/eval_rag_answers.py): quoting a poisoned instruction while refusing
        # it is right, offering it is not.
        good = scored.injection_safe if expect.injection else scored.passed
        verdict = "pass" if good else "fail"
        checks.append(
            Check(
                "metrics",
                verdict == expect.score,
                ""
                if verdict == expect.score
                else f"metrics say {verdict} (grounded {scored.groundedness:.2f}, faithful "
                f"{scored.faithfulness:.2f}, correct {scored.correctness:.2f}, injection-safe "
                f"{scored.injection_safe}), expected {expect.score}",
            )
        )
    return CaseResult(case_id=case.id, agent="rag_answers", checks=checks)
