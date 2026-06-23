import difflib
import json
import logging
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from pydantic_ai import Agent, NativeOutput, capture_run_messages
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.ui import SSE_CONTENT_TYPE
from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from config import REFINEMENT_ROUNDS, TABLE_SCHEMA
from db import run_query
# Shared model + corpus foundation lives in retrieval.py
from retrieval import GENE_ROWS, model, search

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gossipgene")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Catalog of real gene symbols, used to resolve typos before SQL translation. So in our case
# if we do not write visyn, but vissyn in the prompt, we can resolve it to visyn.
_REAL_SYMBOL_BY_LOWERCASE = {r["Gene symbol"].strip().lower(): r["Gene symbol"].strip() for r in GENE_ROWS if r.get("Gene symbol", "").strip()
}
_LOWERCASE_SYMBOLS = list(_REAL_SYMBOL_BY_LOWERCASE)


def resolve_symbol_typos(question: str) -> dict[str, str]:
    f"""
    Map typo-ish question tokens to single real gene symbols in the table.
    
    For example it returns a dictionary like {"vissyn": "VISYN1"}
    """
    # TODO: make this function more robust. It is rather an unstable block in the chain.
    corrections = {}
    
    # First split tokens
    tokens = {t.strip("?.,()'\"") for t in question.lower().split()}

    for token in {t for t in tokens if len(t) >= 4}:
        if token in _REAL_SYMBOL_BY_LOWERCASE:
            continue  # already exact; the translator handles it, something like GPX1

        # Then check if the token is a substring of a real symbol -> this is for family proteins
        symbol_substring_matches = [symbol for symbol in _LOWERCASE_SYMBOLS if token in symbol]
        if len(symbol_substring_matches) > 1:
            continue  # likely a gene-family search term, not a typo for one symbol

        closest_matches = difflib.get_close_matches(token, _LOWERCASE_SYMBOLS, n=1, cutoff=0.8)
        if closest_matches:
            corrections[token] = _REAL_SYMBOL_BY_LOWERCASE[closest_matches[0]]
    return corrections


class RetrieveInput(BaseModel):
    question: str


@app.post("/retrieve")
async def retrieve(body: RetrieveInput) -> list[dict]:
    logger.info("retrieve: %r", body.question)
    return await search(body.question)


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
    logger.info(f" Translating the following question: {question}");
    # TODO: This is right now a temporary fix to handle typos. Will need m more robust approach
    grounded = resolve_symbol_typos(question)
    logger.info(f" Grounded terms (original -> corrected): {grounded}");
    if grounded:
        facts = "; ".join(f"'{t}' is a misspelling of the real gene_symbol '{c}'" for t, c in grounded.items())
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
        "exactly 'This is the recommended query:' on one line, followed by the `sql` value verbatim inside"
        "a ```sql code block```. Do not alter the query. Do NOT list, count, or summarize the returned rows;"
        "the interface displays them separately."
    ),
)

# this comes from Pydantic -> it is a decorator that defines my func as a tool
@orchestrator.tool_plain
async def recommend_query(question: str) -> dict:
    sql = await translate_question(question)  # single translation (incl. its internal refine loop)
    try:
        rows = await run_query(sql)
        return {"sql": sql, "rows": rows, "error": None}
    except Exception as e:  # bad SQL shouldn't trigger a tool-retry storm
        return {"sql": sql, "rows": [], "error": str(e)}


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
    body = json.loads(await request.body())
    if isinstance(body, dict) and isinstance(body.get("messages"), list) and body["messages"]:
        body["messages"] = [body["messages"][-1]]
    run_input = VercelAIAdapter.build_run_input(json.dumps(body).encode())
    adapter = VercelAIAdapter(agent=orchestrator, run_input=run_input)
    return StreamingResponse(adapter.encode_stream(adapter.run_stream()), media_type=SSE_CONTENT_TYPE,)
