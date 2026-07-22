# Maintenance Issue Category Evaluation

## Methodology Notes

- The evaluator calls the deployed production function `accounts.ml.maintenance_nlp.classify_issue_category()` directly.
- The classifier input mirrors the maintenance submission flow in `maintenance/views.py`.
- Exact production concatenation: `classify_issue_category(f"{obj.title} {obj.description}")`
- The evaluator therefore combines the maintenance title, a single space, and the maintenance description before classification.
- Human labels must be one of: PLUMBING, ELECTRICAL, STRUCTURAL, OTHER.
- The blank manual-labeling template intentionally excludes system predictions and keyword-match fields.

## Category Evaluation Overview

| Metric | Value |
|---|---:|
| Total test records | 197 |
| Correct predictions | 164 |
| Incorrect predictions | 33 |
| Overall accuracy | 0.8325 |
| Match coverage | 0.8274 |
| Unmatched rate | 0.1726 |
| Predicted as Other (count) | 34 |
| Predicted as Other (%) | 17.2589 |
| Macro precision | 0.8605 |
| Macro recall | 0.8641 |
| Macro F1-score | 0.8358 |

## Per-Class Metrics

| Class | Support | Precision | Recall | F1-score |
|---|---:|---:|---:|---:|
| PLUMBING | 48 | 0.7586 | 0.9167 | 0.8302 |
| ELECTRICAL | 45 | 1.0000 | 1.0000 | 1.0000 |
| STRUCTURAL | 41 | 0.6833 | 1.0000 | 0.8119 |
| OTHER | 63 | 1.0000 | 0.5397 | 0.7010 |

## Confusion Matrix

| Human \\ Predicted | PLUMBING | ELECTRICAL | STRUCTURAL | OTHER |
|---|---:|---:|---:|---:|
| PLUMBING | 44 | 0 | 4 | 0 |
| ELECTRICAL | 0 | 45 | 0 | 0 |
| STRUCTURAL | 0 | 0 | 41 | 0 |
| OTHER | 14 | 0 | 15 | 34 |
