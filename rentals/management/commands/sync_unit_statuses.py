from django.core.management.base import BaseCommand

from rentals.models import Unit
from rentals.unit_status import expected_unit_status, sync_unit_status


class Command(BaseCommand):
    help = "Synchronize Unit.status with active leases while preserving maintenance rooms."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--unit", type=str, default="", help="Optional unit number to sync.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        unit_number = (options["unit"] or "").strip()

        queryset = Unit.objects.order_by("floor_level", "number")
        if unit_number:
            queryset = queryset.filter(number__iexact=unit_number)

        checked = 0
        changed = 0
        for unit in queryset:
            checked += 1
            expected_status = expected_unit_status(unit)
            if unit.status == expected_status:
                continue

            changed += 1
            self.stdout.write(
                f"Unit {unit.number}: {unit.status} -> {expected_status}"
                f"{' (dry-run)' if dry_run else ''}"
            )
            if not dry_run:
                sync_unit_status(unit)

        message = f"Checked {checked} units; {'would update' if dry_run else 'updated'} {changed}."
        self.stdout.write(self.style.SUCCESS(message))
