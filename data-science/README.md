# GossipGene the data science part

Offline evaluation harness for the backend making natural language transform to SQL query 

## `eval_queries.py`

Runs the real backend `translate_question` over a gold set of questions, executes the 
generated SQL against the gene CSV with DuckDB, checks whether the expected gene(s) appear 
in the top-K results, and writes an Excel report.

### How it works

1. Loads `genes_human_ground_truth.csv` into DuckDB as a table named `genes` (columns 
are renamed to the snake_case schema the backend expects).
2. Iterates over the cases in `gold.py` (`GOLD`).
3. For each case, calls `translate_question` (imported from `../backend/main.py`)
   to turn the question into SQL.
4. Executes that SQL, takes the top `K` rows (default `K = 10`), and counts a
   **HIT** if any `expected_ids` (Ensembl IDs) appear in the result.
5. Prints color-coded HIT/MISS lines plus the generated SQL, and writes a
   timestamped `eval_results_YYYYMMDD_HHMMSS.xlsx` artifact.

Failures (like bad SQL or **some** model errors) are caught per case and logged as a MISS, a
single bad query never crashes the run.

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
