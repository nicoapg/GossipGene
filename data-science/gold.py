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
    {
        "question_id": "002",
        "variant_id": "001-a",
        "purpose": "search the protein datavisyn within the table in chromosome 7 and retour 3 results",
        "question": "Can you pull up genes related to the word datavisyn?",
        "expected_ids": {"ENSG00000000001", "ENSG00000000002", "ENSG00000000003", "ENSG00000000004", "ENSG00000000005"},  # DATAVISYN5,6,7,8,9
    },
]
