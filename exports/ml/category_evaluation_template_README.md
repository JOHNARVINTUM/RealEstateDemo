# Maintenance Category Evaluation Template Notes

This template is for manual labeling only.

Required columns:
- test_id
- maintenance_title
- maintenance_description
- human_label

Rules:
- Leave system predictions out of the manual template.
- Fill `human_label` using only: `PLUMBING`, `ELECTRICAL`, `STRUCTURAL`, `OTHER`.
- Do not duplicate `test_id` values.
- Do not leave both title and description blank.

Production workflow alignment:
- The live maintenance submission flow in `maintenance/views.py` calls:
  `classify_issue_category(f"{obj.title} {obj.description}")`
- The evaluator reproduces that exact concatenation when it computes predictions.

After manual labeling, run:
`python scripts\evaluate_issue_category.py exports\ml\category_evaluation_template.csv --output-dir exports\ml`
