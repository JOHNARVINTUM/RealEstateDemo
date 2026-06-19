from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from billing.models import MonthlyBill
from billing.services import (
    bill_line_items_for_payment_type,
    ensure_bill_line_items_from_legacy,
    sync_monthly_bill_from_line_items,
)
from payments.models import ManualPayment


class Command(BaseCommand):
    help = (
        "Backfill approved historical payments until a month reaches a target paid ratio. "
        "Defaults to dry-run."
    )

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True)
        parser.add_argument("--month", type=int, required=True)
        parser.add_argument(
            "--target-ratio",
            type=float,
            default=0.70,
            help="Desired paid ratio for the month. Default: 0.70",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist changes. Without this flag, the command only reports what it would do.",
        )

    def handle(self, *args, **options):
        year = options["year"]
        month = options["month"]
        target_ratio = options["target_ratio"]
        apply_changes = options["apply"]

        if month < 1 or month > 12:
            raise CommandError("month must be between 1 and 12")
        if not (0 < target_ratio <= 1):
            raise CommandError("target-ratio must be greater than 0 and less than or equal to 1")

        month_bills = list(
            MonthlyBill.objects.select_related("lease__unit", "lease__tenant")
            .filter(billing_month__year=year, billing_month__month=month)
            .order_by("lease__unit__number", "id")
        )
        if not month_bills:
            raise CommandError(f"No bills found for {year}-{month:02d}")

        total = len(month_bills)
        current_paid = sum(1 for bill in month_bills if bill.status == "PAID")
        target_paid = max(int(total * Decimal(str(target_ratio)) + Decimal("0.9999")), current_paid)
        needed = max(target_paid - current_paid, 0)

        unpaid_bills = [bill for bill in month_bills if bill.status != "PAID"]
        selected = unpaid_bills[:needed]

        self.stdout.write(f"Month: {year}-{month:02d}")
        self.stdout.write(f"Mode: {'APPLY' if apply_changes else 'DRY RUN'}")
        self.stdout.write(f"Total bills: {total}")
        self.stdout.write(f"Current paid: {current_paid}")
        self.stdout.write(f"Target paid: {target_paid}")
        self.stdout.write(f"Bills to backfill: {len(selected)}")

        samples: list[str] = []

        with transaction.atomic():
            for index, bill in enumerate(selected):
                ensure_bill_line_items_from_legacy(bill)
                payment_lines = bill_line_items_for_payment_type(bill, "full")
                amount = sum((line.amount for line in payment_lines), Decimal("0.00")).quantize(Decimal("0.01"))
                paid_dt = self._historical_paid_at(bill.due_date, index)
                reference_code = f"REF-HIST-{year}{month:02d}-{bill.lease.unit.number}"

                if len(samples) < 20:
                    samples.append(
                        f"{bill.lease.unit.number}: PHP {amount:,.2f} on {paid_dt.date().isoformat()} ref={reference_code}"
                    )

                if not apply_changes:
                    continue

                payment, created = ManualPayment.objects.get_or_create(
                    user=bill.lease.tenant,
                    reference_code=reference_code,
                    defaults={
                        "bill_ids": str(bill.id),
                        "payment_type": "full",
                        "payment_method": self._payment_method_for_index(index),
                        "amount": amount,
                        "status": "APPROVED",
                    },
                )
                changed_fields = []
                if payment.bill_ids != str(bill.id):
                    payment.bill_ids = str(bill.id)
                    changed_fields.append("bill_ids")
                if payment.payment_type != "full":
                    payment.payment_type = "full"
                    changed_fields.append("payment_type")
                desired_method = self._payment_method_for_index(index)
                if payment.payment_method != desired_method:
                    payment.payment_method = desired_method
                    changed_fields.append("payment_method")
                if payment.amount != amount:
                    payment.amount = amount
                    changed_fields.append("amount")
                if payment.status != "APPROVED":
                    payment.status = "APPROVED"
                    changed_fields.append("status")
                if payment.created_at != paid_dt:
                    payment.created_at = paid_dt
                    changed_fields.append("created_at")
                if changed_fields:
                    payment.save(update_fields=changed_fields)

                for line in payment_lines:
                    if line.amount <= 0:
                        continue
                    line.paid_amount = line.amount
                    line.paid_at = paid_dt
                    line.payment_reference = reference_code
                    line.refresh_status()
                    line.save(update_fields=["paid_amount", "paid_at", "payment_reference", "status", "updated_at"])

                bill.payment_reference = reference_code
                bill.save(update_fields=["payment_reference"])
                sync_monthly_bill_from_line_items(bill)

            if not apply_changes:
                transaction.set_rollback(True)

        if samples:
            self.stdout.write("")
            self.stdout.write("Sample backfills:")
            for sample in samples:
                self.stdout.write(f"- {sample}")

    def _historical_paid_at(self, due_date: date | None, index: int):
        base_date = due_date or date.today()
        late_offsets = [15, 16, 17, 18, 19, 20, 22, 24, 26, 28, 30, 31]
        offset = late_offsets[index % len(late_offsets)]
        paid_date = base_date + timedelta(days=offset)
        paid_time = time(hour=9 + (index % 8), minute=(index * 7) % 60)
        return timezone.make_aware(datetime.combine(paid_date, paid_time))

    def _payment_method_for_index(self, index: int) -> str:
        methods = ["PAYMONGO", "GCASH", "CASH", "PAYMONGO", "GCASH"]
        return methods[index % len(methods)]
