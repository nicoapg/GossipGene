"""Hybrid retrieval for /retrieve. filter-then-rank hybrid retriever

    1) question 
    2) LLM self-query (RetrievalPlan: chromosome/biotype/semantic_text)
    3) metadata filter over GENE_ROWS
    4) BM25 (lexical) + Ollama dense embeddings (semantic)
    5)Reciprocal Rank Fusion -> top-k rows + score

Dense embeddings are precomputed once via `python -m retrieval build` and cached to
a .npy file next to the CSV; search() loads that cache and fails fast if it is missing.
"""

import csv
import logging
import numpy as np

from pydantic import BaseModel, Field
from rank_bm25 import BM25Okapi
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider

from config import CANDIDATES_PER_RANKER, CHAT_MODEL, CSV_PATH, OLLAMA_OPENAI_URL, TABLE_SCHEMA, TOP_K
from embeddings import build_embeddings, embed_query, get_doc_matrix

logger = logging.getLogger("gossipgene.retrieval")

# ============================ Model & corpus =============================
model = OllamaModel(CHAT_MODEL, provider=OllamaProvider(base_url=OLLAMA_OPENAI_URL))

# Corpus: here we load genes table and share with main.py 
with CSV_PATH.open(newline="") as file:
    GENE_ROWS = list(csv.DictReader(file))

# Searchable text per row from the free-text columns only -> r is row
_corpus = [f"{r['Gene symbol']} {r['Name']} {r['Biotype']}".lower().split() for r in GENE_ROWS]
# This is an out of the box implementation
_bm25 = BM25Okapi(_corpus)

# Known biotype set -> notice that here we do a set, not a list. 
_KNOWN_BIOTYPES = {r["Biotype"].strip().lower() for r in GENE_ROWS if r.get("Biotype", "").strip()}


def _doc_text(row: dict) -> str:
    """The text we embed per gene row (used to build the embedding cache)."""
    return f"{row['Gene symbol']} {row['Name']} {row['Biotype']}"


# ============================ Self-query planner =========================
class RetrievalPlan(BaseModel):
    """Whole point is to transform the natural language question into a structured retrieval plan."""
    chromosome: str | None = Field(
        description="Chromosome filter if the question names one, as a bare string like '17' or 'X'. "
        "Null when no chromosome is mentioned."
    )
    biotype: str | None = Field(
        description="Biotype filter ONLY if the question names one of the exact stored biotype values. "
        "Null otherwise. Functional descriptions like 'G protein-coupled receptor' are NOT biotypes."
    )
    semantic_text: str = Field(
        description="The descriptive part of the question to match against gene name/symbol/biotype text, "
        "e.g. 'G protein-coupled receptor'. Exclude chromosome/biotype filter words."
    )


planner_agent = Agent(
    model,
    output_type=NativeOutput(RetrievalPlan),
    retries=3,
    instructions=(
        "You split a natural-language question about a human gene table into a structured retrieval plan. "
        "Extract a `chromosome` filter only when the question names a chromosome (return a bare value like "
        "'17' or 'X'). Extract a `biotype` filter only when the question names one of the EXACT stored biotype "
        "values listed below; a functional description such as 'G protein-coupled receptor' is NOT a biotype, "
        "so leave biotype null and put that phrase in `semantic_text`. `semantic_text` is the descriptive part "
        "used for similarity search; strip out the chromosome/biotype filter words from it.\n"
        f"{TABLE_SCHEMA}"
    ),
)


# ====================== Filter & fusion helpers ==========================
def _allowed_indices(plan: RetrievalPlan) -> list[int]:
    """Takes the retrieval plan and returns the indices of the rows that are allowed."""
    # Normalize chromosome and biotype 
    chromosome = plan.chromosome.strip().lower() if plan.chromosome else None
    biotype = plan.biotype.strip().lower() if plan.biotype else None
    if biotype and biotype not in _KNOWN_BIOTYPES:
        biotype = None  # ignore a hallucinated biotype 
    if not chromosome and not biotype:
        # if no chromosome or biotype, return all rows
        return list(range(len(GENE_ROWS)))
    allowed = []
    # -------------------------------------------------------------
    # iterate to know which rows are allowed
    # -------------------------------------------------------------
    for i, r in enumerate(GENE_ROWS):
        if chromosome and r.get("Chromosome", "").strip().lower() != chromosome:
            # if the chromosome is not the same, skip
            continue
        if biotype and r.get("Biotype", "").strip().lower() != biotype:
            # if the biotype is not the same, skip
            continue
        # if the chromosome and biotype are the same, add the row index to the allowed list
        allowed.append(i)
    return allowed


def _top_by_score(allowed: list[int], scores: np.ndarray, n: int) -> list[int]:
    ranked = sorted(allowed, key=lambda i: scores[i], reverse=True)
    return ranked[:n]


def _rrf(rank_lists: list[list[int]], k: int = 60) -> list[int]:
    fused: dict[int, float] = {}
    for ranks in rank_lists:
        for pos, idx in enumerate(ranks):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + pos + 1)
    return sorted(fused, key=lambda i: fused[i], reverse=True)


def _as_result(idx: int, score: float) -> dict:
    r = GENE_ROWS[idx]
    return {
        "ensembl": r.get("Ensembl", ""),
        "gene_symbol": r.get("Gene symbol", ""),
        "name": r.get("Name", ""),
        "biotype": r.get("Biotype", ""),
        "chromosome": r.get("Chromosome", ""),
        "score": round(score, 6),
    }


# ============================ Hybrid search ==============================
async def search(question: str) -> list[dict]:
    """Self-query -> metadata filter -> BM25 + dense -> RRF -> top-k rows with scores."""
    try:
        plan = (await planner_agent.run(question)).output
    except UnexpectedModelBehavior:
        logger.warning("planner flaked; falling back to no-filter full-question search")
        plan = RetrievalPlan(chromosome=None, biotype=None, semantic_text=question)

    logger.info("retrieval plan: %r", plan)
    allowed = _allowed_indices(plan)
    if not allowed:
        return []

    semantic_text = plan.semantic_text.strip() or question

    # Lexical candidates 
    bm25_scores = _bm25.get_scores(semantic_text.lower().split())
    bm25_ranked = _top_by_score(allowed, bm25_scores, CANDIDATES_PER_RANKER)

    # Dense candidates (cosine of the query vs cached doc embeddings).
    rank_lists = [bm25_ranked]
    try:
        qvec = await embed_query(semantic_text)
        qvec = qvec / (np.linalg.norm(qvec) + 1e-8)
        allowed_arr = np.asarray(allowed)
        sub = get_doc_matrix(len(GENE_ROWS))[allowed_arr]
        sub = sub / (np.linalg.norm(sub, axis=1, keepdims=True) + 1e-8)
        sims = sub @ qvec
        dense_ranked = [int(allowed_arr[j]) for j in np.argsort(-sims)[:CANDIDATES_PER_RANKER]]
        rank_lists.append(dense_ranked)
    except Exception as e:  # dense is best-effort; never break retrieve on embedding issues
        logger.warning("dense retrieval unavailable (%s); using BM25 only", e)

    fused = _rrf(rank_lists)[:TOP_K]
    # Surface the fused position as a simple descending score for provenance.
    return [_as_result(idx, 1.0 / (rank + 1)) for rank, idx in enumerate(fused)]


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build_embeddings([_doc_text(r) for r in GENE_ROWS])
    else:
        print("usage: python -m retrieval build")
