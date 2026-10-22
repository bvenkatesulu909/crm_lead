"""Pure tests for hybrid retrieval helpers (no database, no model)."""

import uuid

from app.core.config import Settings
from app.modules.knowledge.retrieval import (
    CrossEncoderReranker,
    build_reranker,
    rrf_fuse,
)


def _ids(*names: str) -> list[uuid.UUID]:
    return [uuid.uuid5(uuid.NAMESPACE_URL, name) for name in names]


def test_rrf_rewards_chunks_found_by_both_lists():
    a, b, c = _ids("a", "b", "c")
    scores = rrf_fuse([a, b], [b, c], k=60)

    # b appears second in the vector list and first in the keyword list.
    assert scores[b] == 1 / 62 + 1 / 61
    assert scores[b] > scores[a] > scores[c]
    assert scores[c] == 1 / 62


def test_rrf_k_controls_how_flat_the_ranks_are():
    a, b = _ids("a", "b")
    small = rrf_fuse([a, b], [], k=1)
    large = rrf_fuse([a, b], [], k=1000)
    assert small[a] / small[b] > large[a] / large[b]


def test_reranker_can_be_disabled_and_uses_the_configured_model():
    assert build_reranker(Settings(knowledge_reranker_enabled=False)) is None
    reranker = build_reranker(
        Settings(
            knowledge_reranker_enabled=True,
            knowledge_reranker_model="Xenova/ms-marco-MiniLM-L-6-v2",
        )
    )
    assert isinstance(reranker, CrossEncoderReranker)
    assert reranker.name == "Xenova/ms-marco-MiniLM-L-6-v2"
