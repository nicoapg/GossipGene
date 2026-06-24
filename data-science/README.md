# GossipGene the data science part

Offline evaluation harness for the backend making natural language transform to SQL query 

## `eval_queries.py`

Runs the real backend `translate_question` over a gold set of questions, executes the generated SQL against the gene CSV 
with DuckDB, checks whether the expected gene/s appear  in the top-K results, and writes an Excel report.

### How it works

1. Loads `genes_human_ground_truth.csv` into DuckDB as a table named `genes` (columns are renamed to the 
snake_case schema the backend expects).
2. Iterates over the cases in `gold.py` (`GOLD`).
3. For each case, calls `translate_question` (imported from `../backend/main.py`) to turn the question into SQL.
4. Executes that SQL, takes the top `K` rows (default `K = 10`), and counts **HIT** if any `expected_ids` 
(Ensembl IDs) appear in the result.
5. Prints color-coded HIT/MISS lines plus the generated SQL, and writes a timestamped `eval_results_YYYYMMDD_HHMMSS.xlsx` artifact.

Failures (like bad SQL or **some** model errors) are caught per case and logged as a MISS, a single bad query 
never crashes the run.

### Output

An Excel file with:
- a `summary` sheet (question, generated SQL, n_results, hit, error per case), and
- one sheet per `variant_id` containing that case's top-K rows.

A final hit rate is printed to the console.

### Prerequisites

- `ollama serve` must be running (the backend uses a local model via Ollama).
- Dependencies installed via Poetry (see `pyproject.toml`).

### Running

```bash
cd data-science
poetry install
poetry run python eval_queries.py
```

### Adding test cases

Edit `gold.py` and append entries to `GOLD`. Each case is a dict:

| Field          | Description                                          |
| -------------- | ---------------------------------------------------- |
| `question_id`  | Logical question group ID                            |
| `variant_id`   | Unique ID for this phrasing (also the Excel sheet)   |
| `purpose`      | Human note on what the variant tests                 |
| `question`     | Natural-language question fed to the model           |
| `expected_ids` | Set of Ensembl IDs that count as a correct hit       |

### Key knobs (top of `eval_queries.py`)

- `CSV_PATH` — ground-truth dataset used as the `genes` table.
- `K` — top-K cutoff for scoring a hit.
- `RENAME` — maps CSV headers to the backend's expected column names.

## Testing the backend endpoints with curl

Start the backend first (see the root `README.md`): `poetry run uvicorn main:app --port 8000`.
All examples use the questions from `gold.py`.

### `POST /gate` - should the DB pipeline run?

```bash
curl -s -X POST http://localhost:8000/gate \
  -H "Content-Type: application/json" \
  -d '{"question": "Which genes on Chromosome X are associated with visyn protein-coupled receptors?"}'
```

Returns e.g. `{"use_database": true}`.

### `POST /retrieve` - hybrid search over the gene table

```bash
curl -s -X POST http://localhost:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{"question": "Can you pull up genes related to the word datavisyn?"}'
```

Returns a JSON list of candidate gene rows.

### `POST /chat` - full agent pipeline (SSE stream)

`-N` disables curl buffering so you see the stream as it arrives.

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "trigger": "submit-message",
    "id": "req-1",
    "messages": [
      {"id": "m1", "role": "user",
       "parts": [{"type": "text", "text": "Which genes on Chromosome X are associated with visyn protein-coupled receptors?"}]}
    ]
  }'
```

Typo variant (001-b) to exercise symbol grounding - swap the text for:
`"Which genes on Chromosome X are associated with vissyn protein-coupled receptors?"`

### `POST /answer` - direct answer path (SSE stream)

Used when the GateKeeper decides no DB lookup is needed.

```bash
curl -N -X POST http://localhost:8000/answer \
  -H "Content-Type: application/json" \
  -d '{
    "trigger": "submit-message",
    "id": "req-1",
    "messages": [
      {"id": "m1", "role": "user",
       "parts": [{"type": "text", "text": "Can you pull up genes related to the word datavisyn?"}]}
    ]
  }'
```
