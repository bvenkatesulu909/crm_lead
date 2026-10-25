"""Thin wrappers that play agent evaluation cases against the test database (BP-10).

The real work lives in ``agent_evals.play`` / ``agent_evals.world``, shared with the command-line
tool. These wrappers only connect it to the fictional test world (``test_quotes_api.world``:
organisations "alpha-quotes" and "beta-quotes") and to test settings.
"""

from typing import Any

from sqlalchemy.orm import Session

from agent_evals import play
from agent_evals.cases import Case
from agent_evals.play import RAG_MIN_SIMILARITY, explain, invariants
from agent_evals.rag import HashingEmbedder, RagRun
from agent_evals.rag_cases import RagCase
from agent_evals.runner import PortalRun, PublicRun, StaffRun
from agent_evals.scoring import CaseResult
from agent_evals.world import World as EvalWorld
from app.core.config import Settings
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.test_quotes_api import World

__all__ = [
    "RAG_MIN_SIMILARITY",
    "best_similarity",
    "eval_world",
    "explain",
    "ingest_corpus",
    "invariants",
    "play_portal",
    "play_public",
    "play_rag",
    "play_staff",
]


def eval_test_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=TEST_ISSUER,
    )


def eval_world(session: Session, world: World) -> EvalWorld:
    """The test world as the evaluation harness sees it (people are found by role)."""
    return EvalWorld(session, eval_test_settings(), "alpha-quotes", "beta-quotes")


def play_staff(
    session: Session, world: World, case: Case, **limits: Any
) -> tuple[CaseResult, StaffRun]:
    return play.play_staff(session, eval_world(session, world), case, **limits)


def play_portal(
    session: Session, world: World, case: Case, **limits: Any
) -> tuple[CaseResult, PortalRun]:
    return play.play_portal(session, eval_world(session, world), case, **limits)


def play_public(session: Session, world: World, case: Case) -> tuple[CaseResult, PublicRun]:
    return play.play_public(session, eval_world(session, world), case)


def ingest_corpus(session: Session, world: World, embedder: HashingEmbedder) -> None:
    play.ingest_corpus(session, eval_world(session, world), embedder)


def best_similarity(
    session: Session, world: World, case: RagCase, embedder: HashingEmbedder
) -> float:
    return play.best_similarity(session, eval_world(session, world), case, embedder)


def play_rag(
    session: Session,
    world: World,
    case: RagCase,
    *,
    embedder: HashingEmbedder | None = None,
    min_similarity: float = RAG_MIN_SIMILARITY,
    ingest: bool = True,
) -> tuple[CaseResult, RagRun]:
    return play.play_rag(
        session,
        eval_world(session, world),
        case,
        embedder=embedder,
        min_similarity=min_similarity,
        ingest=ingest,
    )
