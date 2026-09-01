"""Tier-2 semantic embeddings with a graceful fallback — spec §0.4.

    sentence-transformers importable AND a local model cache  ->  MiniLM
    otherwise                                                 ->  TF-IDF char 3-5grams

Two things matter here beyond picking a model:

* **Offline.** `sentence-transformers` will happily reach out to Hugging Face to
  download weights on first use. That would break the "no network at runtime"
  guarantee (§9), so the model is loaded in offline mode only; if the weights
  are not already cached locally we fall back to TF-IDF rather than fetch them.

* **Storage.** A raw char-ngram TF-IDF vector is tens of thousands of sparse
  dimensions, which is not something to persist per item. The vectors are
  reduced with truncated SVD (latent semantic analysis) to a fixed dense width,
  which is what gets written to `item.embed_vector` and what cosine similarity
  is computed on.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from .capabilities import detect

#: Persisted vector width. Small enough to store per item, wide enough that
#: cosine still separates catalogue descriptions.
EMBED_DIM = 192


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """Row-normalize so a dot product is the cosine similarity."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


@dataclass
class EmbeddingResult:
    vectors: np.ndarray  # (n, dim) float32, L2-normalized
    mode: str
    dim: int


class Embedder:
    """Fits on a corpus and returns dense, L2-normalized vectors."""

    def __init__(self, mode: str | None = None):
        self.mode = mode or detect().embedding_mode
        self._model = None
        self._vectorizer = None
        self._svd = None

    # -- sentence-transformers -------------------------------------------

    def _load_sentence_transformer(self):
        """Load MiniLM from the local cache only. Never downloads."""
        # Set before importing: the library reads these at import time.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True)

    # -- TF-IDF fallback --------------------------------------------------

    def _fit_tfidf(self, texts: list[str]) -> np.ndarray:
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer

        # char_wb keeps n-grams inside word boundaries, which is what makes this
        # robust to the abbreviation and typo noise in the catalogues.
        self._vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            min_df=2,
            max_features=200_000,
            sublinear_tf=True,
        )
        sparse = self._vectorizer.fit_transform(texts)

        # SVD needs fewer components than features and than samples.
        components = int(min(EMBED_DIM, sparse.shape[1] - 1, sparse.shape[0] - 1))
        if components < 2:
            # Degenerate corpus (a couple of rows): return the sparse vectors
            # densified rather than failing.
            return _l2_normalize(np.asarray(sparse.todense(), dtype=np.float32))

        self._svd = TruncatedSVD(n_components=components, random_state=0)
        return _l2_normalize(self._svd.fit_transform(sparse).astype(np.float32))

    # -- public -----------------------------------------------------------

    def fit_transform(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(np.zeros((0, EMBED_DIM), dtype=np.float32), self.mode, EMBED_DIM)

        if self.mode == "sentence-transformers":
            try:
                self._model = self._load_sentence_transformer()
                vectors = self._model.encode(
                    texts, batch_size=64, show_progress_bar=False, convert_to_numpy=True
                )
                vectors = _l2_normalize(np.asarray(vectors, dtype=np.float32))
                return EmbeddingResult(vectors, "sentence-transformers", vectors.shape[1])
            except Exception:
                # Weights absent from the cache, or a broken install. Degrading
                # is always preferable to a failed pipeline run (§9).
                self.mode = "tfidf"

        vectors = self._fit_tfidf(texts)
        return EmbeddingResult(vectors, "tfidf", vectors.shape[1])


def pack(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def unpack(blob: bytes | None) -> np.ndarray | None:
    if not blob:
        return None
    return np.frombuffer(blob, dtype=np.float32)


def cosine(a: np.ndarray | None, b: np.ndarray | None) -> float:
    """Cosine similarity of two persisted vectors, clamped to [0, 1]."""
    if a is None or b is None or a.shape != b.shape or a.size == 0:
        return 0.0
    value = float(np.dot(a, b))  # both are already L2-normalized
    return max(0.0, min(1.0, value))
