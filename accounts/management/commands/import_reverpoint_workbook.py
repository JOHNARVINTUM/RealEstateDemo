from __future__ import annotations

from collections import Counter
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.importers.reverpoint_workbook import (
    ReverpointTenantRow,
    infer_parking_slots,
    normalize_person_name,
    parse_reverpoint_workbook,
)
from billing.services import (
    bill_line_items_for_payment_type,
    ensure_bill_line_items_from_legacy,
    get_or_update_monthly_bill,
    sync_monthly_bill_from_line_items,
)
from billing.models import MonthlyBill
from payments.models import ManualPayment
from rentals.models import Lease, Unit


class Command(BaseCommand):
    help = (
        "Safely sync Reverpoint workbook rows into the existing database. "
        "Default mode is dry-run; pass --apply to persist changes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="Path to Reverpoint_RealEstate.xlsx",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist database changes. Without this flag, the command only reports what would change.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Explicitly run without persisting changes.",
        )
        parser.add_argument(
            "--year-mode",
            choices=["start", "end"],
            default="end",
            help="How to interpret sheet labels like '2025 - 2026'. Default: end (maps Jan-Dec to 2026).",
        )
        parser.add_argument(
            "--allow-name-mismatch",
            action="store_true",
            help="Allow syncing against the latest lease on a unit even when the workbook tenant name does not match.",
        )

    def handle(self, *args, **options):
        workbook_path = Path(options["file"]).expanduser()
        apply_changes = options["apply"]
        explicit_dry_run = options["dry_run"]
        year_mode = options["year_mode"]
        allow_name_mismatch = options["allow_name_mismatch"]

        if apply_changes and explicit_dry_run:
            raise CommandError("Use either --apply or --dry-run, not both.")

        try:
            workbook_rows = parse_reverpoint_workbook(workbook_path, year_mode=year_mode)
        except Exception as exc:
            raise CommandError(f"Failed to parse workbook: {exc}") from exc

        self.stdout.write(f"Workbook: {workbook_path}")
        self.stdout.write(f"Rows parsed: {len(workbook_rows)}")
        self.stdout.write(f"Mode: {'APPLY' if apply_changes else 'DRY RUN'}")
        self.stdout.write(f"Year mode: {year_mode}")

        summary = Counter()
        notes: list[str] = []

        with transaction.atomic():
            for row in workbook_rows:
                self._sync_row(
                    row,
                    apply_changes=apply_changes,
                    allow_name_mismatch=allow_name_mismatch,
                    summary=summary,
                    notes=notes,
                )

            if not apply_changes:
                transaction.set_rollback(True)

        self.stdout.write("")
        for key in sorted(summary):
            self.stdout.write(f"{key}: {summary[key]}")

        if notes:
            self.stdout.write("")
            self.stdout.write("Notes:")
            for note in notes[:50]:
                self.stdout.write(f"- {note}")
            if len(notes) > 50:
                self.stdout.write(f"- ... {len(notes) - 50} more note(s)")

    def _sync_row(self, row: ReverpointTenantRow, *, apply_changes: bool, allow_name_mismatch: bool, summary: Counter, notes: list[str]):
        unit = Unit.objects.filter(number=row.unit_number).first()
        if unit is None:
            summary["units_missing"] += 1
            notes.append(f"{row.sheet_name} row {row.row_number}: unit {row.unit_number} not found; skipped.")
            return

        summary["units_found"] += 1
        self._sync_unit_rent(unit, row, apply_changes=apply_changes, summary=summary)

        lease = self._select_lease(unit, row, allow_name_mismatch=allow_name_mismatch)
        if lease is None:
            summary["leases_missing_or_mismatch"] += 1
            notes.append(
                f"{row.sheet_name} row {row.row_number}: no matching lease for unit {row.unit_number} / {row.tenant_name}; payment sync skipped."
            )
            return

        summary["leases_found"] += 1
        self._sync_lease_amounts(lease, row, apply_changes=apply_changes, summary=summary, notes=notes)

        for billing_month, status in sorted(row.month_statuses.items()):
            if status != "PAID":
                summary["non_paid_cells_ignored"] += 1
                continue
            self._sync_paid_month(
                lease,
                row,
                billing_month=billing_month,
                apply_changes=apply_changes,
                summary=summary,
                notes=notes,
            )

    def _sync_unit_rent(self, unit: Unit, row: ReverpointTenantRow, *, apply_changes: bool, summary: Counter):
        if unit.monthly_rent == row.monthly_rent:
            summary["unit_rent_unchanged"] += 1
            return
        summary["unit_rent_updates"] += 1
        if apply_changes:
            unit.monthly_rent = row.monthly_rent
            unit.save(update_fields=["monthly_rent", "updated_at"])

    def _select_lease(self, unit: Unit, row: ReverpointTenantRow, *, allow_name_mismatch: bool) -> Lease | None:
        candidates = list(
            Lease.objects.select_related("tenant", "tenant__tenantprofile", "unit")
            .filter(unit=unit)
            .order_by("-is_active", "-start_date", "-id")
        )
        if not candidates:
            return None

        target_name = normalize_person_name(row.tenant_name)
        for lease in candidates:
            profile = getattr(lease.tenant, "tenantprofile", None)
            full_name = getattr(profile, "full_name", "") or f"{lease.tenant.first_name} {lease.tenant.last_name}"
            if normalize_person_name(full_name) == target_name:
                return lease

        if allow_name_mismatch:
            return candidates[0]
        return None

    def _sync_lease_amounts(self, lease: Lease, row: ReverpointTenantRow, *, apply_changes: bool, summary: Counter, notes: list[str]):
        if lease.monthly_rent != row.monthly_rent:
            summary["lease_rent_updates"] += 1
            if apply_changes:
                lease.monthly_rent = row.monthly_rent
                lease.save(update_fields=["monthly_rent"])
        else:
            summary["lease_rent_unchanged"] += 1

        inferred_slots = infer_parking_slots(row.parking_fee)
        if inferred_slots is None:
            summary["parking_fee_unmapped"] += 1
            notes.append(
                f"Unit {row.unit_number}: parking fee {row.parking_fee} cannot be mapped exactly to slot counts; existing lease parking left unchanged."
            )
            return

        motorcycle_slots, car_slots = inferred_slots
        if lease.motorcycle_slots == motorcycle_slots and lease.car_slots == car_slots:
            summary["lease_parking_unchanged"] += 1
            return

        summary["lease_parking_updates"] += 1
        if apply_changes:
            lease.motorcycle_slots = motorcycle_slots
            lease.car_slots = car_slots
            lease.save(update_fields=["motorcycle_slots", "car_slots"])

    def _sync_paid_month(
        self,
        lease: Lease,
        row: ReverpointTenantRow,
        *,
        billing_month,
        apply_changes: bool,
        summary: Counter,
        notes: list[str],
    ):
        if billing_month < lease.start_date.replace(day=1):
            summary["paid_months_before_lease_start_skipped"] += 1
            return
        if lease.end_date and billing_month > lease.end_date.replace(day=1):
            summary["paid_months_after_lease_end_skipped"] += 1
            return

        if not apply_changes:
            existing_bill = (
                MonthlyBill.objects.filter(
                    lease=lease,
                    billing_month__year=billing_month.year,
                    billing_month__month=billing_month.month,
                )
                .order_by("billing_month", "id")
                .first()
            )
            if existing_bill is None:
                summary["paid_month_bills_missing_in_preview"] += 1
                return
            rent_done = Decimal(existing_bill.rent_paid or 0) >= Decimal(existing_bill.base_rent or 0)
            parking_done = Decimal(existing_bill.parking_paid or 0) >= Decimal(existing_bill.parking_fee or 0)
            if rent_done and parking_done:
                summary["paid_months_already_synced"] += 1
            else:
                summary["paid_month_bills_synced"] += 1
            return

        bill = get_or_update_monthly_bill(lease, billing_month, today=billing_month)
        ensure_bill_line_items_from_legacy(bill)
        payment_lines = bill_line_items_for_payment_type(bill, "rent_only")

        if all(line.amount <= 0 or line.paid_amount >= line.amount for line in payment_lines):
            summary["paid_months_already_synced"] += 1
            return

        summary["paid_month_bills_synced"] += 1
        paid_at = timezone.make_aware(datetime.combine(bill.due_date or billing_month, time(hour=12, minute=0)))
        reference_code = f"RWP-{billing_month:%Y%m}-{lease.unit.number}"
        amount = sum((line.amount for line in payment_lines), Decimal("0.00")).quantize(Decimal("0.01"))
        payment = ManualPayment.objects.filter(reference_code=reference_code, user=lease.tenant).first()
        if payment is None:
            payment = ManualPayment.objects.create(
                user=lease.tenant,
                reference_code=reference_code,
                bill_ids=str(bill.id),
                payment_type="rent_only",
                payment_method="CASH",
                amount=amount,
                status="APPROVED",
                metadata={
                    "source": "reverpoint_workbook",
                    "sheet_name": row.sheet_name,
                    "sheet_label": row.sheet_label,
                    "billing_month": billing_month.isoformat(),
                    "tenant_name": row.tenant_name,
                },
            )
            summary["payment_records_created"] += 1
        else:
            changed_fields = []
            if payment.bill_ids != str(bill.id):
                payment.bill_ids = str(bill.id)
                changed_fields.append("bill_ids")
            if payment.amount != amount:
                payment.amount = amount
                changed_fields.append("amount")
            if payment.payment_type != "rent_only":
                payment.payment_type = "rent_only"
                changed_fields.append("payment_type")
            if payment.status != "APPROVED":
                payment.status = "APPROVED"
                changed_fields.append("status")
            if changed_fields:
                payment.save(update_fields=changed_fields)
                summary["payment_records_updated"] += 1
            else:
                summary["payment_records_reused"] += 1

        for line in payment_lines:
            if line.amount <= 0:
                continue
            line.paid_amount = line.amount
            line.paid_at = paid_at
            line.payment_reference = reference_code
            line.refresh_status()
            line.save(update_fields=["paid_amount", "paid_at", "payment_reference", "status", "updated_at"])

        bill.payment_reference = reference_code
        bill.save(update_fields=["payment_reference"])
        sync_monthly_bill_from_line_items(bill)
        notes.append(f"Synced {lease.unit.number} {row.tenant_name} for {billing_month:%b %Y} as rent-only paid.")
