"""Offline eval harness for the backend query-builder.

Runs the real `translate_question` over a growable gold set, executes the
generated SQL on the CSV with DuckDB, checks LIMIT-k membership by Ensembl ID,
and writes an Excel artifact. Requires `ollama serve` running.
"""

import asyncio
import sys
import traceback
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from gold import GOLD

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from main import translate_question  # noqa: E402

CSV_PATH = Path(__file__).parent / "genes_human_ground_truth.csv"
K = 10
OUTPUT = Path(__file__).parent / f"eval_results_{datetime.now():%Y%m%d_%H%M%S}.xlsx"

RENAME = {
    "Ensembl": "ensembl",
    "Gene symbol": "gene_symbol",
    "Name": "name",
    "Biotype": "biotype",
    "Chromosome": "chromosome",
    "Seq region start": "seq_region_start",
    "Seq region end": "seq_region_end",
}


def evaluate():
    genes = pd.read_csv(CSV_PATH).rename(columns=RENAME)
    con = duckdb.connect()
    con.register("genes", genes)

    summary = []
    sheets = {}

    for case in GOLD:
        question_id = case["question_id"]
        variant_id = case["variant_id"]
        purpose = case["purpose"]
        question = case["question"]
        expected_ids = case["expected_ids"]
        sql, error, topk, hit = "", "", pd.DataFrame(), False

        try:
            sql = asyncio.run(translate_question(question))
            result = con.execute(sql).df()
            topk = result.head(K)
            hit = "ensembl" in topk.columns and bool(expected_ids & set(topk["ensembl"]))
        except Exception as exc:  # bad SQL / model failure never crashes the run
            error = f"{type(exc).__name__}: {exc}"
            cause = exc.__cause__ or exc.__context__
            if cause:
                error += f"\n  caused by {type(cause).__name__}: {cause}"
            print("    !! failure on this case, full traceback below:")
            traceback.print_exc()

        summary.append(
            {
                "question_id": question_id,
                "variant_id": variant_id,
                "purpose": purpose,
                "question": question,
                "sql": sql,
                "n_results": len(topk),
                "hit": hit,
                "error": error,
            }
        )
        sheets[variant_id] = topk
        color = "\033[32m" if hit else "\033[31m"  # green = HIT, red = MISS
        print(f"{color}[{'HIT ' if hit else 'MISS'}] {variant_id} {question}\033[0m")  # \033[0m resets color
        print(f"\033[36m{sql}\033[0m")  # cyan = generated SQL; \033[0m resets
        if error:
            print(f"\033[31m    error: {error}\033[0m")  # red = error; \033[0m resets

    with pd.ExcelWriter(OUTPUT, engine="openpyxl") as writer:
        pd.DataFrame(summary).to_excel(writer, sheet_name="summary", index=False)
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)

    hits = sum(row["hit"] for row in summary)
    print(f"\nHit rate: {hits}/{len(summary)} ({hits / len(summary):.0%})")
    print(f"Results written to {OUTPUT}")


if __name__ == "__main__":
    evaluate()
