from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from billing.models import MonthlyBill
from payments.models import ManualPayment


class Command(BaseCommand):
    help = (
        "Normalize bulk-created payment timestamps by copying each linked bill's "
        "existing paid_at back into ManualPayment.created_at. Defaults to dry-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--target-date",
            default="2026-05-15",
            help="Bulk-created payment date to normalize (YYYY-MM-DD). Default: 2026-05-15",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist the timestamp updates. Without this flag, the command only reports changes.",
        )

    def handle(self, *args, **options):
        try:
            target_date = date.fromisoformat(options["target_date"])
        except ValueError as exc:
            raise CommandError("target-date must be in YYYY-MM-DD format.") from exc

        apply_changes = options["apply"]
        updated = 0
        skipped = 0
        missing = 0
        samples: list[str] = []

        payments = list(
            ManualPayment.objects.filter(created_at__date=target_date)
            .exclude(bill_ids="")
            .only("id", "bill_ids", "created_at", "reference_code", "payment_type", "status")
            .order_by("id")
        )

        if not payments:
            self.stdout.write(f"No payments found for {target_date.isoformat()}.")
            return

        with transaction.atomic():
            for payment in payments:
                first_bill_id = (payment.bill_ids.split(",")[0] or "").strip()
                if not first_bill_id.isdigit():
                    missing += 1
                    continue

                bill = MonthlyBill.objects.filter(pk=int(first_bill_id)).only("id", "billing_month", "paid_at").first()
                if bill is None or bill.paid_at is None:
                    missing += 1
                    continue

                if bill.paid_at.date() >= target_date:
                    skipped += 1
                    continue

                if payment.created_at == bill.paid_at:
                    skipped += 1
                    continue

                if len(samples) < 20:
                    samples.append(
                        f"{payment.id}: {payment.created_at.isoformat()} -> {bill.paid_at.isoformat()} "
                        f"(bill {bill.id} {bill.billing_month:%Y-%m})"
                    )

                updated += 1
                if apply_changes:
                    payment.created_at = bill.paid_at
                    payment.save(update_fields=["created_at"])

            if not apply_changes:
                transaction.set_rollback(True)

        self.stdout.write(f"Target date: {target_date.isoformat()}")
        self.stdout.write(f"Mode: {'APPLY' if apply_changes else 'DRY RUN'}")
        self.stdout.write(f"Payments scanned: {len(payments)}")
        self.stdout.write(f"Payments to normalize: {updated}")
        self.stdout.write(f"Skipped: {skipped}")
        self.stdout.write(f"Missing bill/paid_at: {missing}")

        if samples:
            self.stdout.write("")
            self.stdout.write("Sample changes:")
            for sample in samples:
                self.stdout.write(f"- {sample}")
