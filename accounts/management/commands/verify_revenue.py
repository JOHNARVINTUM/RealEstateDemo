from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Sum
import uuid

from billing.models import MonthlyBill
from payments.models import ManualPayment


class Command(BaseCommand):
    help = (
        "Verify dashboard revenue before/after approving a payment. "
        "Dry-run by default; use --apply to persist changes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply changes (create payment and mark bill paid).",
        )
        parser.add_argument(
            "--bill-id",
            type=int,
            help="MonthlyBill id to target (defaults to first UNPAID bill).",
        )

    def handle(self, *args, **options):
        apply_changes = options.get("apply")
        bill_id = options.get("bill_id")
        now = timezone.now()
        today = now.date()

        total_before = (
            MonthlyBill.objects.filter(
                status="PAID", paid_at__year=today.year, paid_at__month=today.month
            )
            .aggregate(total=Sum("total_due"))["total"]
            or 0
        )

        self.stdout.write(f"Total revenue (by payment date) before: {total_before}")

        if bill_id:
            try:
                bill = MonthlyBill.objects.select_related("lease", "lease__tenant").get(pk=bill_id)
            except MonthlyBill.DoesNotExist:
                self.stderr.write(f"No MonthlyBill with id {bill_id}")
                return
        else:
            bill = MonthlyBill.objects.filter(status="UNPAID").order_by("billing_month").first()
            if not bill:
                self.stderr.write("No UNPAID MonthlyBill found to approve.")
                return

        self.stdout.write(
            f"Target bill: id={bill.id} billing_month={bill.billing_month} total_due={bill.total_due} status={bill.status}"
        )

        ref = f"VERIFY-{uuid.uuid4().hex[:8].upper()}"

        if not apply_changes:
            projected = total_before + bill.total_due
            self.stdout.write("Dry-run mode (no DB changes). Use --apply to persist.)")
            self.stdout.write(f"Projected total revenue after approving this payment: {projected}")
            return

        # Persist: create ManualPayment and mark bill paid
        user = bill.lease.tenant
        mp = ManualPayment.objects.create(user=user, reference_code=ref, bill_ids=str(bill.id), status="APPROVED")
        bill.status = "PAID"
        bill.paid_at = now
        bill.payment_reference = ref
        bill.save()

        total_after = (
            MonthlyBill.objects.filter(
                status="PAID", paid_at__year=today.year, paid_at__month=today.month
            )
            .aggregate(total=Sum("total_due"))["total"]
            or 0
        )

        self.stdout.write(f"Created ManualPayment id={mp.id} ref={mp.reference_code}")
        self.stdout.write(f"Total revenue (by payment date) after: {total_after}")
