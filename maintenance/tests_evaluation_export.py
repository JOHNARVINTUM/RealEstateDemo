import csv
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase

from maintenance.evaluation_export import (
    CATEGORY_DISPLAY,
    CSV_COLUMNS,
    PRIORITY_DISPLAY,
    compute_category_summary,
    compute_priority_summary,
    export_maintenance_evaluation,
)


class MaintenanceEvaluationExportTests(SimpleTestCase):
    def _run_export(self, output_dir: Path):
        return export_maintenance_evaluation(reports_dir=output_dir)

    def test_exports_exactly_197_unique_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_export(Path(tmpdir))
            rows = result["csv_rows"]
            self.assertEqual(len(rows), 197)
            self.assertEqual(len({row["record_code"] for row in rows}), 197)
            self.assertEqual(len({record.test_id for record in result["export_records"]}), 197)

    def test_human_labels_are_complete_and_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = self._run_export(Path(tmpdir))["csv_rows"]
            valid_categories = set(CATEGORY_DISPLAY.values())
            valid_priorities = set(PRIORITY_DISPLAY.values())
            for row in rows:
                self.assertIn(row["human_category"], valid_categories)
                self.assertIn(row["human_priority"], valid_priorities)
                self.assertTrue(row["human_category"])
                self.assertTrue(row["human_priority"])

    def test_export_has_no_direct_identifiers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = self._run_export(Path(tmpdir))["csv_rows"]
            for row in rows:
                combined_text = f"{row['sanitized_title']} {row['sanitized_description']}"
                self.assertNotRegex(combined_text, r"@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
                self.assertNotRegex(combined_text, r"\bUnit\s+[A-Z0-9-]+\b")
                self.assertNotRegex(combined_text, r"\b(?:\+?63|0)\d{10}\b")
                self.assertNotRegex(combined_text, r"\b\d{4,19}\b")

    def test_comparison_fields_match_detailed_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = self._run_export(Path(tmpdir))["csv_rows"]
            for row in rows:
                self.assertEqual(
                    row["category_correct"],
                    "Yes" if row["human_category"] == row["system_category"] else "No",
                )
                self.assertEqual(
                    row["priority_correct"],
                    "Yes" if row["human_priority"] == row["system_priority"] else "No",
                )

    def test_output_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmpdir_one, tempfile.TemporaryDirectory() as tmpdir_two:
            result_one = self._run_export(Path(tmpdir_one))
            result_two = self._run_export(Path(tmpdir_two))
            csv_one = Path(result_one["csv_path"]).read_text(encoding="utf-8")
            csv_two = Path(result_two["csv_path"]).read_text(encoding="utf-8")
            self.assertEqual(csv_one, csv_two)

    def test_summary_metrics_match_detailed_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_export(Path(tmpdir))
            category_summary = compute_category_summary(result["export_records"])
            priority_summary = compute_priority_summary(result["export_records"])
            self.assertEqual(category_summary["correct_predictions"], 164)
            self.assertEqual(category_summary["incorrect_predictions"], 33)
            self.assertEqual(category_summary["accuracy"], result["category_summary"]["accuracy"])
            self.assertEqual(priority_summary["correct_predictions"], 64)
            self.assertEqual(priority_summary["incorrect_predictions"], 133)
            self.assertEqual(priority_summary["accuracy"], result["priority_summary"]["accuracy"])

    def test_command_writes_expected_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            call_command("export_maintenance_evaluation_197", reports_dir=str(output_dir))
            self.assertTrue((output_dir / "maintenance_evaluation_197.csv").exists())
            self.assertTrue((output_dir / "maintenance_evaluation_197.xlsx").exists())
            self.assertTrue((output_dir / "maintenance_evaluation_summary.txt").exists())

    def test_csv_header_matches_required_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_export(Path(tmpdir))
            with Path(result["csv_path"]).open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, CSV_COLUMNS)
