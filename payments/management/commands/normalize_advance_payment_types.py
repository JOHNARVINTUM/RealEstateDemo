from django.core.management.base import BaseCommand
from django.db import transaction

from payments.models import ManualPayment
from payments.services import should_relabel_full_payment_as_rent_only


class Command(BaseCommand):
    help = "Relabel historical advance payments that were stored as full payments."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist changes instead of running a dry run.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        payments = (
            ManualPayment.objects.exclude(payment_type="move_in")
            .filter(payment_type="full")
            .exclude(bill_ids="")
            .order_by("created_at")
        )

        matched = []
        for payment in payments:
            if should_relabel_full_payment_as_rent_only(payment):
                matched.append(payment)

        if not matched:
            self.stdout.write(self.style.SUCCESS("No historical advance payments matched the relabeling rule."))
            return

        self.stdout.write(
            f"Matched {len(matched)} payment(s) for relabeling from full to rent_only."
        )
        for payment in matched[:20]:
            self.stdout.write(f" - {payment.reference_code or payment.id} ({payment.user.email})")
        if len(matched) > 20:
            self.stdout.write(f" - ...and {len(matched) - 20} more")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run only. Re-run with --apply to save changes."))
            return

        updated = 0
        with transaction.atomic():
            for payment in matched:
                payment.payment_type = "rent_only"
                metadata = payment.metadata if isinstance(payment.metadata, dict) else {}
                if metadata:
                    metadata = dict(metadata)
                    metadata["payment_type"] = "rent_only"
                    payment.metadata = metadata
                    payment.save(update_fields=["payment_type", "metadata"])
                else:
                    payment.save(update_fields=["payment_type"])
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} payment(s) to rent_only."))

