"""
Ollama dense embeddings: offline build, cached load, and on-the-go query embed.
"""

import httpx
import logging
import numpy as np

from config import EMBED_CACHE_PATH, EMBED_MODEL, OLLAMA_HOST

logger = logging.getLogger("gossipgene.embeddings")


# np.ndarray -> multidimensional array
def _embed_batch_sync(texts: list[str]) -> np.ndarray:
    """Embed a batch of texts via Ollama's /api/embed (used by the build step)."""
    response = httpx.post(
        f"{OLLAMA_HOST}/api/embed",
        json={"model": EMBED_MODEL, "input": texts},
        timeout=120.0,
    )
    # raises an exception for errors -> it'll fail
    response.raise_for_status()
    embeddings = response.json()["embeddings"]
    return np.asarray(embeddings, dtype=np.float32)


def build_embeddings(texts: list[str], batch_size: int = 200) -> None:
    """One-time: embed every text and persist the matrix to EMBED_CACHE_PATH.
    Run explicitly (`python -m retrieval build`)."""
    logger.info("Building embeddings for %d rows via %s ...", len(texts), EMBED_MODEL)
    chunks: list[np.ndarray] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        chunks.append(_embed_batch_sync(batch))
        logger.info("  embedded %d/%d", min(start + batch_size, len(texts)), len(texts))
    matrix = np.vstack(chunks).astype(np.float32)
    np.save(EMBED_CACHE_PATH, matrix)
    logger.info("Saved %s with shape %s", EMBED_CACHE_PATH, matrix.shape)


_doc_matrix: np.ndarray | None = None


def get_doc_matrix(expected_rows: int) -> np.ndarray:
    """this is a lazy load"""
    global _doc_matrix
    if _doc_matrix is None:
        if not EMBED_CACHE_PATH.exists():
            raise FileNotFoundError(
                f"Embedding cache {EMBED_CACHE_PATH} is missing. Build it once with: "
                f"`poetry run python -m retrieval build` (requires `ollama pull {EMBED_MODEL}`)."
            )
        matrix = np.load(EMBED_CACHE_PATH)
        if matrix.shape[0] != expected_rows:
            raise ValueError(
                f"Embedding cache has {matrix.shape[0]} rows but the corpus has "
                f"{expected_rows}; rebuild with `poetry run python -m retrieval build`."
            )
        _doc_matrix = matrix.astype(np.float32)
    return _doc_matrix


async def embed_query(text: str) -> np.ndarray:
    """ embeds a single query"""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{OLLAMA_HOST}/api/embed",
            json={"model": EMBED_MODEL, "input": text},
        )
        response.raise_for_status()
        embeddings = response.json()["embeddings"]
        return np.asarray(embeddings[0], dtype=np.float32)
