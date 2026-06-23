
from pydantic import BaseModel, Field
from pydantic_ai import Agent, NativeOutput

from config import TABLE_SCHEMA
from retrieval import model


# ============================ SQL translator ============================
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


# ============================ Orchestrator ==============================
orchestrator = Agent(
    model,
    instructions=(
        "When the user asks a data question, call the `recommend_query` tool with their question. Then reply with"
        "exactly 'This is the recommended query:' on one line, followed by the `sql` value verbatim inside"
        "a ```sql code block```. Do not alter the query. Do NOT list, count, or summarize the returned rows;"
        "the interface displays them separately."
    ),
)


# ============================ GateKeeper ================================
# Step 0: GateKeeper decides whether the DB pipeline is needed
class GateOutput(BaseModel):
    use_database: bool = Field(
        description="True only if answering REQUIRES querying the genes table (searching, filtering, or"
        "counting rows). False for greetings, off-topic questions, or general knowledge you can answer directly."
    )


gatekeeper_agent = Agent(
    model,
    output_type=NativeOutput(GateOutput),
    retries=3,
    instructions=(
        "You are the GateKeeper for a tool that answers questions about a human gene database. Decide ONLY"
        "whether the user's message needs a database query; do not write a reply.\n"
        " - Greetings/small talk (e.g. 'Hi!') -> use_database=False.\n"
        " - Off-topic (credit cards, math, etc.) -> use_database=False.\n"
        " - General gene/protein knowledge you can answer without looking up specific rows "
        "(e.g. 'what does protein P42 do') -> use_database=False.\n"
        " - Anything requiring searching, filtering, or counting genes in the table -> use_database=True.\n"
        f"{TABLE_SCHEMA}"
    ),
)


# ============================ Direct answer =============================
# Plain-text agent for direct answers (no output_type, so its text can stream).
answer_agent = Agent(
    model,
    instructions=(
        "Answer the user directly, no database lookup. Greet briefly on small talk, answer general "
        "gene/protein knowledge you know, and politely decline off-topic questions (you only help with "
        "the human gene dataset). Be concise."
    ),
)
