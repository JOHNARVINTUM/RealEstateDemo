from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from billing.models import MonthlyBill
from billing.services import refresh_late_fee_for_bill


class Command(BaseCommand):
    help = "Safely refresh one-time late fees on eligible unpaid bills."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report proposed changes without writing to the database.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Process at most this many unpaid/partially-paid bills.",
        )

    def handle(self, *args, **options):
        limit = options.get("limit")
        if limit is not None and limit <= 0:
            raise CommandError("--limit must be a positive integer.")

        today = timezone.localdate()
        queryset = MonthlyBill.objects.filter(
            status__in=("UNPAID", "PARTIALLY_PAID"),
        ).order_by("due_date", "pk")
        total_candidates = queryset.count()
        bill_ids = list(queryset.values_list("pk", flat=True)[:limit]) if limit else list(
            queryset.values_list("pk", flat=True)
        )

        counts = {key: 0 for key in ("created", "updated", "unchanged", "skipped", "errors")}
        self.stdout.write(f"Bills selected: {len(bill_ids)} of {total_candidates}")
        if options["dry_run"]:
            self.stdout.write("DRY RUN -- no database writes will be performed.")

        for bill_id in bill_ids:
            try:
                result = refresh_late_fee_for_bill(
                    bill_id,
                    today=today,
                    dry_run=options["dry_run"],
                )
            except Exception as exc:
                counts["errors"] += 1
                self.stderr.write(
                    f"Bill {bill_id}: ERROR ({exc.__class__.__name__}); transaction rolled back."
                )
                continue

            action = result.get("action", "skipped")
            counts[action if action in counts else "skipped"] += 1
            self.stdout.write(self._format_result(result))

        self.stdout.write(
            "Summary: "
            + ", ".join(f"{key}={value}" for key, value in counts.items())
        )
        if counts["errors"]:
            raise CommandError(f"Late-fee refresh completed with {counts['errors']} error(s).")

    @staticmethod
    def _format_result(result):
        def amount(value):
            return "-" if value is None else f"PHP {value:,.2f}"

        billing_month = result.get("billing_month")
        due_date = result.get("due_date")
        return (
            f"Bill {result.get('bill_id')}: {result.get('action')} | "
            f"month={billing_month or '-'} | due={due_date or '-'} | "
            f"days_overdue={result.get('days_overdue', '-')} | "
            f"status={result.get('status', '-')} | "
            f"rent={amount(result.get('rent'))} | "
            f"parking={amount(result.get('parking'))} | "
            f"interest={amount(result.get('current_interest'))} | "
            f"existing_fee={amount(result.get('existing_fee_amount'))} | "
            f"expected_fee={amount(result.get('expected_fee'))} | "
            f"proposed_total_due={amount(result.get('proposed_total_due'))} | "
            f"reason={result.get('reason', '-')}"
        )
