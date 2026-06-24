"""Embedded DuckDB query layer.

This is a transitory solution to handle DB outside the main.py file. 
TODO: In an ideal scenario I'd replace this with a proper DB layer. 
The dataset path is read from the GENES_CSV env var so Docker can mount/override it.
"""

import asyncio

import duckdb

from config import CSV_PATH

# One in-memory connection. The genes table exposes the agent target, mapped from CSV headers.
_db = duckdb.connect(":memory:")
_db.execute(f"""
    CREATE TABLE genes AS SELECT
        "Ensembl" AS ensembl, "Gene symbol" AS gene_symbol, "Name" AS name,
        "Biotype" AS biotype, "Chromosome" AS chromosome,
        "Seq region start" AS seq_region_start, "Seq region end" AS seq_region_end
    FROM read_csv_auto('{CSV_PATH}')
""")


async def run_query(sql: str) -> list[dict]:
    if not sql.lstrip().lower().startswith("select"):
        raise ValueError("Only SELECT queries are allowed")

    def _exec():
        cursor = _db.cursor()  
        cursor.execute(sql)
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    # 
    return await asyncio.to_thread(_exec) # this helps with concurrency.
