"""Tests for the local embedding interface (no model download, no network).

The real fastembed model is exercised by scripts/check_embeddings.py; here a fake model proves the
contract: lazy loading, dimensions, error mapping and the configured model name.
"""

from typing import Any

import pytest

from app.core.ai.embeddings import (
    EmbeddingUnavailableError,
    FastEmbedder,
    build_embedder,
)
from app.core.config import Settings


class FakeModel:
    """Stands in for fastembed's TextEmbedding."""

    def __init__(self, dimensions: int = 384, fail: bool = False) -> None:
        self.dimensions = dimensions
        self.fail = fail

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise RuntimeError("model broke")
        return [[0.1] * self.dimensions for _ in texts]


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "database_url": "postgresql+psycopg://user:pass@127.0.0.1:1/unused",
        "oidc_issuer": "http://localhost:8080/realms/crm",
    }
    values.update(overrides)
    return Settings(**values)


def test_empty_batch_does_not_load_the_model() -> None:
    embedder = FastEmbedder("BAAI/bge-small-en-v1.5", 384)
    assert embedder.embed_documents([]) == []
    assert embedder._embedding is None


def test_query_uses_the_same_path_as_documents() -> None:
    embedder = FastEmbedder("test-model", 3)
    embedder._embedding = FakeModel(dimensions=3)
    assert embedder.embed_query("hello") == [0.1, 0.1, 0.1]


def test_wrong_dimensions_are_reported() -> None:
    embedder = FastEmbedder("test-model", 384)
    embedder._embedding = FakeModel(dimensions=3)
    with pytest.raises(EmbeddingUnavailableError):
        embedder.embed_documents(["hello"])


def test_model_failure_becomes_a_domain_error() -> None:
    embedder = FastEmbedder("test-model", 384)
    embedder._embedding = FakeModel(fail=True)
    with pytest.raises(EmbeddingUnavailableError):
        embedder.embed_documents(["hello"])


def test_build_embedder_uses_the_settings() -> None:
    embedder = build_embedder(settings(embeddings_model="custom/model", embeddings_dimensions=768))
    assert embedder.model_name == "custom/model"
    assert embedder.dimensions == 768
