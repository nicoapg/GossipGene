
import os
from pathlib import Path

# Paths
DATA_DIR = Path(__file__).parent.parent / "data-science"
# Single source of truth for the dataset
CSV_PATH = Path(os.getenv("GENES_CSV", DATA_DIR / "genes_human_ground_truth.csv"))

# Ollama and models
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_OPENAI_URL = f"{OLLAMA_HOST}/v1"  # OpenAI-compatible endpoint for the chat model
CHAT_MODEL = "qwen2.5:7b"
# CHAT_MODEL = "llama3.2:3b"  # smaller & faster but weaker at structured output + SQL -> this lead to quite a bit of errors
EMBED_MODEL = "nomic-embed-text"

# TODO: This does not scale or at least I'm not a fan of this approach
# The idea of saving genes to a .npy file is ok for a small dataset, not millions.
EMBED_CACHE_PATH = DATA_DIR / f"genes_embeddings_{EMBED_MODEL.replace(':', '_')}.npy"

# Genes table
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

# Retrieval & agent tuning
CANDIDATES_PER_RANKER = 25  # candidates each ranker contributes before fusion
TOP_K = 5  # final cut after fusion
REFINEMENT_ROUNDS = 2  # critique <-> revise cycles in the SQL translator
