GOLD = [
    {
        "question_id": "001",
        "variant_id": "001-a",
        "purpose": "baseline phrasing: chromosome filter + biotype keyword",
        "question": "Which genes on Chromosome X are associated with visyn protein-coupled receptors?",
        "expected_ids": {"ENSG00000000000"},  # VISYN1
    },
    {
        "question_id": "001",
        "variant_id": "001-b",
        "purpose": "baseline phrasing mit TYPO: chromosome filter + biotype keyword",
        "question": "Which genes on Chromosome X are associated with vissyn protein-coupled receptors?",
        "expected_ids": {"ENSG00000000000"},  # VISYN1
    },
]
