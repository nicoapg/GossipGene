import csv
import difflib
import logging
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from rank_bm25 import BM25Okapi
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from pydantic_ai import Agent, NativeOutput, capture_run_messages
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.ui import SSE_CONTENT_TYPE
from pydantic_ai.ui.vercel_ai import VercelAIAdapter

# Swap this to change the model powering both agents.
MODEL_NAME = "qwen2.5:7b"
# MODEL_NAME = "llama3.2:3b"  # smaller/faster, weaker at structured output + SQL

model = OllamaModel(MODEL_NAME, provider=OllamaProvider(base_url="http://localhost:11434/v1"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gossipgene")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- Step 1: BM25 retrieval over the full gene table -------------------------
CSV_PATH = Path(__file__).parent.parent / "data-science" / "genes_human_ground_truth.csv"
with CSV_PATH.open(newline="") as f:
    GENE_ROWS = list(csv.DictReader(f))

# Searchable text per row from the free-text columns only.
_corpus = [
    f"{r['Gene symbol']} {r['Name']} {r['Biotype']}".lower().split()
    for r in GENE_ROWS
]
_bm25 = BM25Okapi(_corpus)

# Catalog of real gene symbols, used to resolve typos before SQL translation.
_SYMBOL_BY_LOWER = {
    r["Gene symbol"].strip().lower(): r["Gene symbol"].strip()
    for r in GENE_ROWS if r.get("Gene symbol", "").strip()
}
_SYMBOL_KEYS = list(_SYMBOL_BY_LOWER)


def ground_terms(question: str) -> dict[str, str]:
    """Map typo-ish question tokens to real gene symbols that exist in the table."""
    out = {}
    for tok in {t.strip("?.,()") for t in question.lower().split() if len(t) >= 4}:
        if tok in _SYMBOL_BY_LOWER:
            continue  # already exact; the translator handles it
        match = difflib.get_close_matches(tok, _SYMBOL_KEYS, n=1, cutoff=0.8)
        if match:
            out[tok] = _SYMBOL_BY_LOWER[match[0]]
    return out


class RetrieveInput(BaseModel):
    question: str


@app.post("/retrieve")
async def retrieve(body: RetrieveInput) -> list[dict]:
    logger.info("retrieve: %r", body.question)
    hits = _bm25.get_top_n(body.question.lower().split(), GENE_ROWS, n=5)
    return [
        {
            "ensembl": h.get("Ensembl", ""),
            "gene_symbol": h.get("Gene symbol", ""),
            "name": h.get("Name", ""),
            "biotype": h.get("Biotype", ""),
            "chromosome": h.get("Chromosome", ""),
        }
        for h in hits
    ]


# Number of critique <-> revise cycles the senior runs the translator through.
REFINEMENT_ROUNDS = 2

TABLE_NAME = "genes"
TABLE_SCHEMA = """
Table: genes
Column            | Meaning
ensembl           | Stable Ensembl gene ID, e.g. ENSG00000171657
gene_symbol       | Common short gene name, e.g. GPR82, GPX1, GPX2
name              | Full gene name and source metadata (HGNC / EntrezGene)
biotype           | Gene/feature type. Exact stored values (match verbatim): 'Protein Coding', 'Processed Pseudogene', 'Antisense', 'Unprocessed Pseudogene', 'Linc R N A', 'Sense Intronic', 'Misc R N A', 'T E C', 'Transcribed Unprocessed Pseudogene', 'Transcribed Unitary Pseudogene', 'Processed Transcript', 'Transcribed Processed Pseudogene'
chromosome        | Chromosome as a string: '1'..'22' or 'X' (e.g. 'X')
seq_region_start  | Start genomic coordinate
seq_region_end    | End genomic coordinate
"""


class TranslatorOutput(BaseModel):
    query: str = Field(description="A single SQL query over the genes table")
    reasoning: str = Field(description="Brief justification for why this query answers the question")


class CritiqueOutput(BaseModel):
    critique: str = Field(description="Specific, demanding feedback on the proposed query")
    approved: bool = Field(description="True only when nothing else can be improved")


translator_agent = Agent(
    model,
    output_type=NativeOutput(TranslatorOutput),
    retries=3,
    instructions=(
        "You translate a natural-language question into ONE SQL query over the table below. ALWAYS write the query"
        "as `SELECT * FROM genes ...` to return every column; never select a subset of columns. Put all filtering"
        "logic in the WHERE clause. For text columns (gene_symbol, name, biotype) ALWAYS match case-insensitively"
        "using ILIKE, e.g. `gene_symbol ILIKE '%visyn%'` (never case-sensitive LIKE). Return valid SQL."
        "When given reviewer feedback, be self-critical and revise your previous query to address it.\n"
        f"{TABLE_SCHEMA}"
    ),
)

# The senior does NOT rewrite the query. It only challenges the translator.
senior_translator_agent = Agent(
    model,
    output_type=NativeOutput(CritiqueOutput),
    retries=3,
    instructions=(
        "You are a SENIOR SQL reviewer. You do NOT write or fix queries. Your job is to challenge the translator"
        "on WHERE-clause correctness: missing or wrong filters, incorrect biotype values, and chromosome formatting."
        "Text matching on gene_symbol/name/biotype MUST be case-insensitive via ILIKE; flag any case-sensitive"
        "LIKE or = on text columns. The query MUST use `SELECT *` (all columns); flag it if it selects a subset."
        "Be specific and skeptical. Set approved=true only when you genuinely find nothing left to improve.\n"
        f"{TABLE_SCHEMA}"
    ),
)


async def step(label, coro):
    """Log the start and elapsed time of an awaited step so a stall shows which step never finished."""
    logger.info("→ %s", label)
    t = time.perf_counter()
    out = await coro
    logger.info("← %s (%.1fs)", label, time.perf_counter() - t)
    return out


async def translate_question(question: str) -> str:
    grounded = ground_terms(question)
    if grounded:
        facts = "; ".join(
            f"'{t}' is a misspelling of the real gene_symbol '{c}'"
            for t, c in grounded.items()
        )
        question = f"{question}\n\n[Verified table facts: {facts}. Use the corrected symbol(s).]"

    result = await step("translate", translator_agent.run(question))
    history = result.all_messages()
    query = result.output.query

    for i in range(REFINEMENT_ROUNDS):
        logger.info(f"Refinement round {i} starting...");
        try:
            critique = await step(f"critique r{i}", senior_translator_agent.run(
                f"Question: {question}\n\nProposed query:\n{query}\n\n"
                "Critique this query. What is wrong or could be improved?"
            ))
            if critique.output.approved:
                break

            revised = await step(f"revise r{i}", translator_agent.run(
                f"A senior reviewer raised this critique:\n{critique.output.critique}\n\n"
                "Be self-critical and revise your query to address it.",
                message_history=history,
            ))
            history = revised.all_messages()
            query = revised.output.query
        except UnexpectedModelBehavior:
            break  # reviewer/translator flaked; keep the best query so far

    return query


orchestrator = Agent(
    model,
    instructions=(
        "When the user asks a data question, call the `recommend_query` tool with their question. Then reply with"
        "exactly 'This is the recommended query:' on one line, followed by the returned query verbatim inside"
        "a ```sql code block```. Do not alter the query."
    ),
)


@orchestrator.tool_plain
async def recommend_query(question: str) -> str:
    return await translate_question(question)


# Step 0: GateKeeper decides whether the DB pipeline is needed
class GateOutput(BaseModel):
    use_database: bool = Field(
        description="True only if answering REQUIRES querying the genes table (searching, filtering, or"
        "counting rows). False for greetings, off-topic questions, or general knowledge you can answer directly."
    )
    answer: str = Field(
        # TODO: Make sure default removal makes returned answer in negative cases more reliable. 
        # Removal should make it as per Pydantic rules, required. Eval if Ollama complies.
        # default="",
        description="Your reply to the user when use_database is False. Leave empty when use_database is True.",
    )


gatekeeper_agent = Agent(
    model,
    output_type=NativeOutput(GateOutput),
    retries=3,
    instructions=(
        "You are the GateKeeper for a tool that answers questions about a human gene database. Decide whether"
        "the user's message needs a database query.\n - Greetings/small talk (e.g. 'Hi!') -> use_database=False;"
        "greet briefly and invite a gene question.\n - Off-topic (credit cards, math, etc.) -> use_database=False;"
        "politely say you only help with the human gene dataset.\n - General gene/protein knowledge you can"
        "answer without looking up specific rows (e.g. 'what does protein P42 do') -> use_database=False;"
        "answer it.\n- Anything requiring searching, filtering, or counting genes in the table "
        "-> use_database=True and leave answer empty.\n"
        f"{TABLE_SCHEMA}"
    ),
)


class GateInput(BaseModel):
    question: str


@app.post("/gate")
async def gate(body: GateInput) -> GateOutput:
    with capture_run_messages() as messages:
        try:
            result = await gatekeeper_agent.run(body.question)
            logger.info("GateKeeper messages:\n%s", messages)
            return result.output
        except UnexpectedModelBehavior:
            # If the GateKeeper flaked, we need to query the database... this is also an issue,
            # for example if the Model does not retrieve the right format (right answer, but wrong format)
            # ToDo: Handle edge case.
            logger.warning("GateKeeper flaked; raw messages:\n%s", messages)
            return GateOutput(use_database=True)


@app.post("/chat")
async def chat(request: Request) -> Response:
    logger.info("chat: streaming handoff")
    run_input = VercelAIAdapter.build_run_input(await request.body())
    adapter = VercelAIAdapter(agent=orchestrator, run_input=run_input)
    return StreamingResponse(adapter.encode_stream(adapter.run_stream()), media_type=SSE_CONTENT_TYPE,)
