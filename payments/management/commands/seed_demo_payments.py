from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from billing.services import (
    add_months,
    bill_line_items_for_payment_type,
    ensure_bill_line_items_from_legacy,
    get_or_update_monthly_bill,
    sync_monthly_bill_from_line_items,
)
from payments.models import ManualPayment
from rentals.models import Lease


class Command(BaseCommand):
    help = "Seed demo payment history for completed months to support thesis forecasting demos."

    SEEDED_LABEL = "Seeded Demo Payment."
    SEEDED_PREFIX = "REF-DEMO-SEED"
    METHOD_CYCLE = ("PAYMONGO", "GCASH", "CASH", "PAYMONGO", "GCASH")
    PAID_DAY_OFFSETS = (0, 1, 2, 3, 5, 7, 10, 12)

    def add_arguments(self, parser):
        parser.add_argument(
            "--months",
            type=int,
            required=True,
            help="Number of completed historical months to seed.",
        )

    def handle(self, *args, **options):
        months = int(options["months"])
        if months <= 0:
            raise CommandError("months must be greater than 0")

        if not (settings.DEBUG or getattr(settings, "DEMO_MODE", False)):
            raise CommandError("seed_demo_payments can only run when DEBUG=True or DEMO_MODE=True.")

        today = timezone.localdate()
        current_month_start = date(today.year, today.month, 1)
        end_month = add_months(current_month_start, -1)
        start_month = add_months(end_month, -(months - 1))

        summary = {
            "months_covered": f"{start_month.isoformat()} to {end_month.isoformat()}",
            "bills_found": 0,
            "payments_created": 0,
            "payments_updated": 0,
            "bills_updated": 0,
            "skipped_seeded": 0,
            "skipped_paid": 0,
            "skipped_invalid": 0,
            "skipped_out_of_range": 0,
            "warnings": [],
        }

        leases = list(
            Lease.objects.select_related("tenant", "unit")
            .exclude(status=Lease.STATUS_PENDING_PAYMENT)
            .order_by("tenant_id", "unit__number", "id")
        )

        if not leases:
            self.stdout.write(self.style.WARNING("No eligible leases found for demo payment seeding."))
            self._print_summary(summary)
            return

        with transaction.atomic():
            for lease_index, lease in enumerate(leases):
                lease_start_month = date(lease.start_date.year, lease.start_date.month, 1)
                lease_end_month = end_month
                if lease.end_date:
                    lease_end_month = min(lease_end_month, date(lease.end_date.year, lease.end_date.month, 1))

                if lease_start_month > end_month or lease_end_month < start_month:
                    summary["skipped_out_of_range"] += 1
                    continue

                month_cursor = max(start_month, lease_start_month)
                while month_cursor <= lease_end_month:
                    bill = get_or_update_monthly_bill(lease, month_cursor, today=month_cursor)
                    summary["bills_found"] += 1

                    reference_code = self._reference_code(lease, month_cursor)
                    existing_payment = ManualPayment.objects.filter(reference_code=reference_code).first()

                    if self._is_seeded_bill(bill, reference_code) or existing_payment is not None:
                        summary["skipped_seeded"] += 1
                        month_cursor = add_months(month_cursor, 1)
                        continue

                    if bill.status == "PAID":
                        summary["skipped_paid"] += 1
                        month_cursor = add_months(month_cursor, 1)
                        continue

                    ensure_bill_line_items_from_legacy(bill)
                    payment_lines = [line for line in bill_line_items_for_payment_type(bill, "full") if line.amount > 0]
                    amount = sum((line.amount for line in payment_lines), Decimal("0.00")).quantize(Decimal("0.01"))

                    if amount <= Decimal("0.00"):
                        summary["skipped_invalid"] += 1
                        summary["warnings"].append(
                            f"Skipped bill {bill.id} ({bill.billing_month}) for lease {lease.id}: zero payable amount."
                        )
                        month_cursor = add_months(month_cursor, 1)
                        continue

                    paid_at = self._seeded_paid_at(bill, lease_index)
                    payment_method = self._payment_method_for_index(lease_index + month_cursor.month)
                    payment = self._create_or_update_payment(
                        bill=bill,
                        reference_code=reference_code,
                        amount=amount,
                        paid_at=paid_at,
                        payment_method=payment_method,
                    )
                    if payment[1] == "created":
                        summary["payments_created"] += 1
                    elif payment[1] == "updated":
                        summary["payments_updated"] += 1

                    for line in payment_lines:
                        line.paid_amount = line.amount
                        line.paid_at = paid_at
                        line.payment_reference = reference_code
                        line.refresh_status()
                        line.save(update_fields=["paid_amount", "paid_at", "payment_reference", "status", "updated_at"])

                    bill.payment_reference = reference_code
                    bill.save(update_fields=["payment_reference"])
                    sync_monthly_bill_from_line_items(bill)
                    summary["bills_updated"] += 1

                    month_cursor = add_months(month_cursor, 1)

        self._print_summary(summary)

    def _reference_code(self, lease, billing_month: date) -> str:
        return f"{self.SEEDED_PREFIX}-{lease.id}-{billing_month.strftime('%Y%m')}"

    def _seeded_paid_at(self, bill, index: int):
        base_date = bill.due_date or bill.billing_month
        offset = self.PAID_DAY_OFFSETS[index % len(self.PAID_DAY_OFFSETS)]
        paid_date = base_date + timedelta(days=offset)
        paid_time = time(hour=9 + (index % 8), minute=(index * 7) % 60)
        return timezone.make_aware(datetime.combine(paid_date, paid_time))

    def _payment_method_for_index(self, index: int) -> str:
        return self.METHOD_CYCLE[index % len(self.METHOD_CYCLE)]

    def _is_seeded_bill(self, bill, reference_code: str) -> bool:
        if bill.payment_reference == reference_code:
            return True
        return bool((bill.payment_reference or "").startswith(self.SEEDED_PREFIX))

    def _create_or_update_payment(self, *, bill, reference_code: str, amount: Decimal, paid_at, payment_method: str):
        payment, created = ManualPayment.objects.get_or_create(
            user=bill.lease.tenant,
            reference_code=reference_code,
            defaults={
                "bill_ids": str(bill.id),
                "payment_type": "full",
                "payment_method": payment_method,
                "amount": amount,
                "status": "APPROVED",
                "metadata": {"seed_label": self.SEEDED_LABEL},
            },
        )

        changed_fields = []
        if payment.bill_ids != str(bill.id):
            payment.bill_ids = str(bill.id)
            changed_fields.append("bill_ids")
        if payment.payment_type != "full":
            payment.payment_type = "full"
            changed_fields.append("payment_type")
        if payment.payment_method != payment_method:
            payment.payment_method = payment_method
            changed_fields.append("payment_method")
        if payment.amount != amount:
            payment.amount = amount
            changed_fields.append("amount")
        if payment.status != "APPROVED":
            payment.status = "APPROVED"
            changed_fields.append("status")
        metadata = dict(payment.metadata or {})
        if metadata.get("seed_label") != self.SEEDED_LABEL:
            metadata["seed_label"] = self.SEEDED_LABEL
            payment.metadata = metadata
            changed_fields.append("metadata")
        if payment.created_at != paid_at:
            payment.created_at = paid_at
            changed_fields.append("created_at")
        if changed_fields:
            payment.save(update_fields=changed_fields)
            return payment, "created" if created else "updated"
        return payment, "created" if created else "unchanged"

    def _print_summary(self, summary):
        self.stdout.write(f"Months covered: {summary['months_covered']}")
        self.stdout.write(f"Bills found: {summary['bills_found']}")
        self.stdout.write(f"Payments created: {summary['payments_created']}")
        self.stdout.write(f"Payments updated: {summary['payments_updated']}")
        self.stdout.write(f"Bills updated: {summary['bills_updated']}")
        self.stdout.write(f"Skipped already-seeded: {summary['skipped_seeded']}")
        self.stdout.write(f"Skipped already-paid non-seeded: {summary['skipped_paid']}")
        self.stdout.write(f"Skipped out-of-range or inactive: {summary['skipped_out_of_range']}")
        self.stdout.write(f"Skipped invalid records: {summary['skipped_invalid']}")
        warning_count = len(summary['warnings'])
        self.stdout.write(f"Warnings: {warning_count}")
        for warning in summary['warnings'][:20]:
            self.stdout.write(f"- {warning}")
