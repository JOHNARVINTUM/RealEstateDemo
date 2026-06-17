from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from billing.models import BillLineItem, MonthlyBill


def money(value):
    return Decimal(value or 0).quantize(Decimal("0.01"))


def line_status(amount, paid_amount):
    if amount <= 0 or paid_amount >= amount:
        return BillLineItem.STATUS_PAID
    if paid_amount > 0:
        return BillLineItem.STATUS_PARTIAL
    return BillLineItem.STATUS_UNPAID


def build_line(bill, line_type, amount, paid_amount, paid_at, reference, source_water_reading_id=None):
    amount = money(amount)
    paid_amount = money(paid_amount)
    if amount == 0 and paid_amount == 0:
        return None
    return BillLineItem(
        monthly_bill_id=bill.id,
        line_type=line_type,
        amount=amount,
        paid_amount=min(paid_amount, amount) if amount > 0 else paid_amount,
        status=line_status(amount, paid_amount),
        paid_at=paid_at if paid_amount > 0 else None,
        payment_reference=reference if paid_amount > 0 else "",
        source_water_reading_id=source_water_reading_id,
    )


class Command(BaseCommand):
    help = "Backfill BillLineItem rows from existing MonthlyBill rows in safe batches."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=250)
        parser.add_argument("--start-id", type=int, default=0)
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, **options):
        batch_size = max(options["batch_size"], 1)
        start_id = options["start_id"]
        limit = options["limit"]

        processed = 0
        created_attempts = 0
        last_id = start_id

        while True:
            if limit and processed >= limit:
                break

            current_batch_size = min(batch_size, limit - processed) if limit else batch_size
            bills = list(
                MonthlyBill.objects.filter(id__gt=last_id).order_by("id").only(
                    "id",
                    "base_rent",
                    "rent_paid",
                    "rent_paid_at",
                    "parking_fee",
                    "parking_paid",
                    "water_amount",
                    "water_paid",
                    "water_paid_at",
                    "interest",
                    "paid_at",
                    "payment_reference",
                    "status",
                    "source_water_reading_id",
                )[:current_batch_size]
            )
            if not bills:
                break

            buffer = []
            for bill in bills:
                last_id = bill.id
                processed += 1
                buffer.extend(
                    line for line in [
                        build_line(
                            bill,
                            BillLineItem.LINE_TYPE_RENT,
                            bill.base_rent,
                            bill.rent_paid,
                            bill.rent_paid_at or bill.paid_at,
                            bill.payment_reference,
                        ),
                        build_line(
                            bill,
                            BillLineItem.LINE_TYPE_PARKING,
                            bill.parking_fee,
                            bill.parking_paid,
                            bill.rent_paid_at or bill.paid_at,
                            bill.payment_reference,
                        ),
                        build_line(
                            bill,
                            BillLineItem.LINE_TYPE_WATER,
                            bill.water_amount,
                            bill.water_paid,
                            bill.water_paid_at or bill.paid_at,
                            bill.payment_reference,
                            bill.source_water_reading_id,
                        ),
                        build_line(
                            bill,
                            BillLineItem.LINE_TYPE_LATE_FEE,
                            bill.interest,
                            bill.interest if bill.status == "PAID" else Decimal("0.00"),
                            bill.paid_at,
                            bill.payment_reference,
                        ),
                    ]
                    if line is not None
                )

            if buffer:
                BillLineItem.objects.bulk_create(buffer, batch_size=batch_size, ignore_conflicts=True)
                created_attempts += len(buffer)
            self.stdout.write(f"Processed MonthlyBill id {last_id} ({processed} bills)")
            close_old_connections()

        self.stdout.write(self.style.SUCCESS(
            f"Backfill complete. Processed {processed} bills; attempted {created_attempts} line inserts."
        ))
