"""Check the local embedding model end to end (ADR 0010).

Run from the backend folder with the venv active:

    python -m scripts.check_embeddings

The first run downloads the model and caches it. No API key is needed, and no text leaves this
machine.
"""

import time

from app.core.ai.embeddings import build_embedder
from app.core.config import get_settings

DOCUMENTS = [
    "Returns policy: damaged items may be returned within 14 days of delivery.",
    "Delivery usually takes 3 to 5 working days.",
]
QUESTION = "How long do I have to return a damaged item?"


def cosine(left: list[float], right: list[float]) -> float:
    dot = sum(float(a) * float(b) for a, b in zip(left, right, strict=True))
    left_norm = sum(float(a) * float(a) for a in left) ** 0.5
    right_norm = sum(float(b) * float(b) for b in right) ** 0.5
    return float(dot / (left_norm * right_norm))


def main() -> None:
    embedder = build_embedder(get_settings())
    started = time.perf_counter()
    document_vectors = embedder.embed_documents(DOCUMENTS)
    question_vector = embedder.embed_query(QUESTION)
    elapsed = time.perf_counter() - started
    print(f"model={embedder.model_name} dimensions={embedder.dimensions}")
    print(f"embedded {len(document_vectors) + 1} texts in {elapsed:.2f}s")
    print("vector lengths:", [len(v) for v in document_vectors], len(question_vector))
    for index, vector in enumerate(document_vectors, start=1):
        print(f"similarity question<->document {index}: {cosine(question_vector, vector):.4f}")


if __name__ == "__main__":
    main()
