"""Local text embeddings for the knowledge base (ADR 0010).

The rest of the code depends only on the Embedder interface. The fastembed implementation runs an
ONNX model inside this process (CPU, no PyTorch); knowledge text never leaves the machine.
"""

from collections.abc import Sequence
from typing import Any, Protocol

from app.core.config import Settings
from app.core.errors import DomainError


class EmbeddingUnavailableError(DomainError):
    """The local embedding model cannot be used right now (missing library or bad output)."""

    status_code = 503
    code = "embeddings_unavailable"


class Embedder(Protocol):
    """What ingestion and search need from an embedding model."""

    model_name: str
    dimensions: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedder:
    """fastembed (ONNX Runtime, CPU) implementation, loaded lazily on first use."""

    def __init__(self, model_name: str, dimensions: int, cache_dir: str | None = None) -> None:
        self.model_name = model_name
        self.dimensions = dimensions
        self._cache_dir = cache_dir
        self._embedding: Any | None = None

    def _load(self) -> Any:
        if self._embedding is None:
            try:
                from fastembed import TextEmbedding
            except ImportError as exc:  # pragma: no cover - guarded by requirements.txt
                raise EmbeddingUnavailableError(
                    "The local embedding library is not installed."
                ) from exc
            try:
                self._embedding = TextEmbedding(
                    model_name=self.model_name, cache_dir=self._cache_dir
                )
            except Exception as exc:
                raise EmbeddingUnavailableError(
                    "The local embedding model could not be loaded."
                ) from exc
        return self._embedding

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        items = list(texts)
        if not items:
            return []
        try:
            vectors = [list(map(float, vector)) for vector in self._load().embed(items)]
        except EmbeddingUnavailableError:
            raise
        except Exception as exc:
            raise EmbeddingUnavailableError("The local embedding model failed.") from exc
        if len(vectors) != len(items) or any(len(v) != self.dimensions for v in vectors):
            raise EmbeddingUnavailableError(
                f"The embedding model returned unexpected dimensions (expected {self.dimensions})."
            )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def build_embedder(settings: Settings) -> Embedder:
    """The configured local embedder (ADR 0010: fastembed, BAAI/bge-small-en-v1.5, 384 dims)."""
    return FastEmbedder(
        model_name=settings.embeddings_model,
        dimensions=settings.embeddings_dimensions,
        cache_dir=settings.embeddings_cache_dir,
    )
