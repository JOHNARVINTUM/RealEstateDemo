# Maintenance Priority Evaluation

## Methodology Notes

- The evaluator calls the deployed production function `accounts.ml.maintenance_nlp.predict_priority()` directly.
- The classifier input mirrors the maintenance submission flow in `maintenance/views.py`.
- Exact production call: `predict_priority(obj.description)`
- Only the maintenance description is passed into the priority classifier.

## Priority Evaluation Overview

| Metric | Value |
|---|---:|
| Total test records | 197 |
| Correct predictions | 64 |
| Incorrect predictions | 133 |
| Overall accuracy | 0.3249 |
| Macro precision | 0.3239 |
| Macro recall | 0.3636 |
| Macro F1-score | 0.2847 |

## Per-Class Metrics

| Class | Support | Precision | Recall | F1-score |
|---|---:|---:|---:|---:|
| LOW | 9 | 0.0656 | 0.4444 | 0.1143 |
| MEDIUM | 80 | 0.3636 | 0.3500 | 0.3567 |
| HIGH | 108 | 0.5424 | 0.2963 | 0.3832 |

## Confusion Matrix

| Human \\ Predicted | LOW | MEDIUM | HIGH |
|---|---:|---:|---:|
| LOW | 4 | 1 | 4 |
| MEDIUM | 29 | 28 | 23 |
| HIGH | 28 | 48 | 32 |

## Predicted Class Distribution

| Predicted Class | Count |
|---|---:|
| LOW | 61 |
| MEDIUM | 77 |
| HIGH | 59 |
