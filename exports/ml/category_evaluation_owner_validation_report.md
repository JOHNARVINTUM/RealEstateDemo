# Owner Workbook Validation Report

Date checked: 2026-07-19

Workbook inspected:
- `exports/ml/category_evaluation_reviewer.xlsx`

Source dataset used for validation:
- `exports/complete_dataset/maintenance_requests.csv`

Validation summary:
- Excel records found: `197`
- Required maintenance records present: `197 / 197`
- Duplicate `Test ID` values: `0`
- Description mismatches against source dataset: `0`
- Human-label blanks: `0`
- Human-label invalid values after capitalization and whitespace normalization: `0`
- Priority-level blanks: `0`
- Priority-level invalid values after capitalization and whitespace normalization: `0`

Normalization applied during validation only:
- `human_label`: capitalization and surrounding whitespace normalization
- `Priority_level`: capitalization and surrounding whitespace normalization

Standardized responses:
- `human_label` responses normalized: `197`
- `Priority_level` responses normalized: `197`

Validated category-label distribution:
- `PLUMBING`: `48`
- `ELECTRICAL`: `45`
- `STRUCTURAL`: `41`
- `OTHER`: `63`

Validated priority-label distribution:
- `LOW`: `9`
- `MEDIUM`: `80`
- `HIGH`: `108`

Status:
- Validation passed.
- Export and evaluation were allowed to continue.
