from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from threading import Barrier

from django.core.management import call_command
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import User
from billing.models import BillLineItem, MonthlyBill
from billing.services import refresh_late_fee_for_bill
from billing.services import set_bill_status
from rentals.models import Lease, Unit


class LateFeeRefreshCommandTests(TestCase):
    def setUp(self):
        self.tenant = User.objects.create_user(
            email="late-fee-refresh@example.test",
            username="late-fee-refresh",
            password="test-password",
            role=User.Role.TENANT,
        )
        self.unit = Unit.objects.create(number="LFR-1")
        self.lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=Decimal("10000.00"),
            due_day=1,
            start_date=date(2026, 1, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )

    def make_bill(
        self,
        *,
        days_due=14,
        status="UNPAID",
        water=Decimal("0.00"),
        maintenance=Decimal("0.00"),
        rent_paid=Decimal("0.00"),
        existing_fee=None,
        paid=False,
    ):
        due_date = timezone.localdate() - timedelta(days=days_due)
        billing_month = due_date.replace(day=1)
        rent = Decimal("10000.00")
        parking = Decimal("350.00")
        lines = [
            (BillLineItem.LINE_TYPE_RENT, rent, rent_paid),
            (BillLineItem.LINE_TYPE_PARKING, parking, Decimal("0.00")),
        ]
        if water:
            lines.append((BillLineItem.LINE_TYPE_WATER, water, Decimal("0.00")))
        if maintenance:
            lines.append((BillLineItem.LINE_TYPE_MAINTENANCE, maintenance, Decimal("0.00")))
        interest = Decimal("0.00")
        if existing_fee is not None:
            fee_amount, fee_paid = existing_fee
            interest = fee_amount
            lines.append((BillLineItem.LINE_TYPE_LATE_FEE, fee_amount, fee_paid))
        if paid:
            lines = [(kind, amount, amount) for kind, amount, _ in lines]

        total_due = sum((amount for _, amount, _ in lines), Decimal("0.00"))
        bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=billing_month,
            due_date=due_date,
            base_rent=rent,
            parking_fee=parking,
            water_amount=water,
            rent_paid=rent_paid,
            water_paid=Decimal("0.00"),
            parking_paid=Decimal("0.00"),
            interest=interest,
            total_due=total_due,
            status=status,
        )
        for line_type, amount, allocated in lines:
            line = BillLineItem(
                monthly_bill=bill,
                line_type=line_type,
                amount=amount,
                paid_amount=allocated,
            )
            line.refresh_status()
            line.save()
        return bill

    def assert_reconciled(self, bill):
        bill.refresh_from_db()
        lines = list(bill.line_items.all())
        self.assertEqual(sum((line.amount for line in lines), Decimal("0.00")), bill.total_due)
        self.assertEqual(sum((line.balance for line in lines), Decimal("0.00")), bill.total_balance)

    def test_unpaid_bill_at_day_14_receives_one_fee_and_reconciles(self):
        bill = self.make_bill()

        result = refresh_late_fee_for_bill(bill.pk)

        bill.refresh_from_db()
        fee = bill.line_items.get(line_type=BillLineItem.LINE_TYPE_LATE_FEE)
        self.assertEqual(result["action"], "created")
        self.assertEqual(fee.amount, Decimal("310.50"))
        self.assertEqual(bill.interest, Decimal("310.50"))
        self.assert_reconciled(bill)

    def test_day_15_keeps_exact_same_fee(self):
        bill = self.make_bill()
        refresh_late_fee_for_bill(bill.pk, today=bill.due_date + timedelta(days=14))

        result = refresh_late_fee_for_bill(bill.pk, today=bill.due_date + timedelta(days=15))

        self.assertEqual(result["action"], "unchanged")
        self.assertEqual(bill.line_items.get(line_type=BillLineItem.LINE_TYPE_LATE_FEE).amount, Decimal("310.50"))
        self.assertEqual(bill.line_items.filter(line_type=BillLineItem.LINE_TYPE_LATE_FEE).count(), 1)

    def test_repeated_command_is_idempotent(self):
        bill = self.make_bill()
        call_command("refresh_late_fees", stdout=StringIO())
        call_command("refresh_late_fees", stdout=StringIO())

        self.assertEqual(bill.line_items.filter(line_type=BillLineItem.LINE_TYPE_LATE_FEE).count(), 1)
        self.assertEqual(bill.line_items.get(line_type=BillLineItem.LINE_TYPE_LATE_FEE).amount, Decimal("310.50"))
        self.assert_reconciled(bill)

    def test_partially_paid_bill_keeps_existing_allocations(self):
        bill = self.make_bill(status="PARTIALLY_PAID", rent_paid=Decimal("2000.00"))
        before = {
            line.line_type: (line.amount, line.paid_amount)
            for line in bill.line_items.all()
        }

        result = refresh_late_fee_for_bill(bill.pk)

        bill.refresh_from_db()
        after = {
            line.line_type: (line.amount, line.paid_amount)
            for line in bill.line_items.all()
            if line.line_type != BillLineItem.LINE_TYPE_LATE_FEE
        }
        self.assertEqual(result["action"], "created")
        self.assertEqual(after, before)
        self.assertEqual(bill.status, "PARTIALLY_PAID")
        self.assertEqual(bill.total_balance, Decimal("8660.50"))
        self.assert_reconciled(bill)

    def test_paid_bill_never_receives_a_fee(self):
        bill = self.make_bill(status="PAID", paid=True)

        result = refresh_late_fee_for_bill(bill.pk)

        self.assertEqual(result["action"], "skipped")
        self.assertEqual(bill.line_items.filter(line_type=BillLineItem.LINE_TYPE_LATE_FEE).count(), 0)
        self.assert_reconciled(bill)

    def test_day_13_is_not_eligible(self):
        bill = self.make_bill(days_due=13)

        result = refresh_late_fee_for_bill(bill.pk)

        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["reason"], "less than 14 days past due")
        self.assertEqual(bill.line_items.filter(line_type=BillLineItem.LINE_TYPE_LATE_FEE).count(), 0)

    def test_future_bill_is_not_eligible(self):
        today = timezone.localdate()
        due_date = today + timedelta(days=20)
        bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=(today.replace(day=1) + timedelta(days=32)).replace(day=1),
            due_date=due_date,
            base_rent=Decimal("10000.00"),
            parking_fee=Decimal("350.00"),
            total_due=Decimal("10350.00"),
            status="UNPAID",
        )
        for line_type, amount in (
            (BillLineItem.LINE_TYPE_RENT, Decimal("10000.00")),
            (BillLineItem.LINE_TYPE_PARKING, Decimal("350.00")),
        ):
            BillLineItem.objects.create(monthly_bill=bill, line_type=line_type, amount=amount)

        result = refresh_late_fee_for_bill(bill.pk)

        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["reason"], "future bill")
        self.assertEqual(bill.line_items.filter(line_type=BillLineItem.LINE_TYPE_LATE_FEE).count(), 0)

    def test_fee_uses_rent_and_parking_but_excludes_water_and_maintenance(self):
        bill = self.make_bill(water=Decimal("500.00"), maintenance=Decimal("250.00"))

        refresh_late_fee_for_bill(bill.pk)

        bill.refresh_from_db()
        self.assertEqual(bill.line_items.get(line_type=BillLineItem.LINE_TYPE_LATE_FEE).amount, Decimal("310.50"))
        self.assertEqual(bill.line_items.get(line_type=BillLineItem.LINE_TYPE_WATER).amount, Decimal("500.00"))
        self.assertEqual(bill.line_items.get(line_type=BillLineItem.LINE_TYPE_MAINTENANCE).amount, Decimal("250.00"))
        self.assertEqual(bill.total_due, Decimal("11410.50"))
        self.assert_reconciled(bill)

    def test_existing_paid_fee_and_allocation_are_preserved(self):
        bill = self.make_bill(
            status="PARTIALLY_PAID",
            rent_paid=Decimal("100.00"),
            existing_fee=(Decimal("310.50"), Decimal("100.00")),
        )

        result = refresh_late_fee_for_bill(bill.pk)

        fee = bill.line_items.get(line_type=BillLineItem.LINE_TYPE_LATE_FEE)
        self.assertEqual(result["action"], "unchanged")
        self.assertEqual((fee.amount, fee.paid_amount, fee.balance), (
            Decimal("310.50"), Decimal("100.00"), Decimal("210.50"),
        ))
        self.assert_reconciled(bill)

    def test_existing_unpaid_fee_is_updated_in_place_without_duplicate(self):
        bill = self.make_bill(existing_fee=(Decimal("300.00"), Decimal("0.00")))

        result = refresh_late_fee_for_bill(bill.pk)

        bill.refresh_from_db()
        fee = bill.line_items.get(line_type=BillLineItem.LINE_TYPE_LATE_FEE)
        self.assertEqual(result["action"], "updated")
        self.assertEqual(fee.amount, Decimal("310.50"))
        self.assertEqual(fee.paid_amount, Decimal("0.00"))
        self.assertEqual(bill.line_items.filter(line_type=BillLineItem.LINE_TYPE_LATE_FEE).count(), 1)
        self.assert_reconciled(bill)

    def test_dry_run_is_read_only_and_reports_plan(self):
        bill = self.make_bill()
        output = StringIO()
        with CaptureQueriesContext(connection) as queries:
            call_command("refresh_late_fees", "--dry-run", stdout=output)

        writes = [
            query["sql"] for query in queries
            if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        ]
        self.assertEqual(writes, [])
        self.assertIn(f"Bill {bill.pk}", output.getvalue())
        self.assertIn("expected_fee=PHP 310.50", output.getvalue())
        self.assertEqual(bill.line_items.filter(line_type=BillLineItem.LINE_TYPE_LATE_FEE).count(), 0)
        self.assertEqual(bill.interest, Decimal("0.00"))

    def test_bill_that_becomes_paid_after_candidate_selection_is_skipped(self):
        bill = self.make_bill()
        selected_id = bill.pk
        set_bill_status(bill, status="PAID", payment_reference="REF-PAID-BEFORE-REFRESH")

        result = refresh_late_fee_for_bill(selected_id)

        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["reason"], "status is not UNPAID or PARTIALLY_PAID")
        self.assertEqual(bill.line_items.filter(line_type=BillLineItem.LINE_TYPE_LATE_FEE).count(), 0)

    def test_inconsistent_line_backed_bill_is_skipped_without_repair(self):
        bill = self.make_bill()
        bill.total_due += Decimal("1.00")
        bill.save(update_fields=["total_due"])

        result = refresh_late_fee_for_bill(bill.pk)

        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["reason"], "bill summary does not reconcile to its line-item ledger")
        self.assertEqual(bill.line_items.filter(line_type=BillLineItem.LINE_TYPE_LATE_FEE).count(), 0)


class LateFeeRefreshConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        tenant = User.objects.create_user(
            email="late-fee-race@example.test",
            username="late-fee-race",
            password="test-password",
            role=User.Role.TENANT,
        )
        unit = Unit.objects.create(number="LFR-2")
        lease = Lease.objects.create(
            tenant=tenant,
            unit=unit,
            monthly_rent=Decimal("10000.00"),
            due_day=1,
            start_date=date(2026, 1, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        due_date = timezone.localdate() - timedelta(days=14)
        self.bill = MonthlyBill.objects.create(
            lease=lease,
            billing_month=due_date.replace(day=1),
            due_date=due_date,
            base_rent=Decimal("10000.00"),
            parking_fee=Decimal("350.00"),
            total_due=Decimal("10350.00"),
            status="UNPAID",
        )
        BillLineItem.objects.create(
            monthly_bill=self.bill,
            line_type=BillLineItem.LINE_TYPE_RENT,
            amount=Decimal("10000.00"),
        )
        BillLineItem.objects.create(
            monthly_bill=self.bill,
            line_type=BillLineItem.LINE_TYPE_PARKING,
            amount=Decimal("350.00"),
        )

    def test_concurrent_refreshes_create_only_one_late_fee_line(self):
        if connection.vendor != "postgresql":
            self.skipTest("Row-lock concurrency behavior requires PostgreSQL.")
        barrier = Barrier(2)

        def refresh():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return refresh_late_fee_for_bill(self.bill.pk)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: refresh(), range(2)))

        self.assertCountEqual([result["action"] for result in results], ["created", "unchanged"])
        self.assertEqual(
            self.bill.line_items.filter(line_type=BillLineItem.LINE_TYPE_LATE_FEE).count(),
            1,
        )
