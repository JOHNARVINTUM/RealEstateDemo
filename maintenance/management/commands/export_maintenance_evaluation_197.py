from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from maintenance.evaluation_export import (
    DEFAULT_OWNER_WORKBOOK,
    DEFAULT_REPORTS_DIR,
    DEFAULT_SOURCE_DATASET,
    export_maintenance_evaluation,
)


class Command(BaseCommand):
    help = "Create a read-only evaluation export for the 197 owner-labeled maintenance request records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--owner-workbook",
            default=str(DEFAULT_OWNER_WORKBOOK),
            help="Path to the owner-labeled evaluation workbook.",
        )
        parser.add_argument(
            "--source-csv",
            default=str(DEFAULT_SOURCE_DATASET),
            help="Path to the maintenance request source CSV.",
        )
        parser.add_argument(
            "--reports-dir",
            default=str(DEFAULT_REPORTS_DIR),
            help="Directory where the export files will be written.",
        )

    def handle(self, *args, **options):
        try:
            result = export_maintenance_evaluation(
                workbook_path=Path(options["owner_workbook"]).resolve(),
                source_csv_path=Path(options["source_csv"]).resolve(),
                reports_dir=Path(options["reports_dir"]).resolve(),
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Maintenance evaluation export generated."))
        self.stdout.write(f"Human-label source: {result['workbook_path']}")
        self.stdout.write(f"CSV export: {result['csv_path']}")
        self.stdout.write(f"Excel export: {result['xlsx_path']}")
        self.stdout.write(f"Summary report: {result['summary_path']}")
