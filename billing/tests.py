from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from billing.models import MonthlyBill
from billing.services import (
    approve_manual_payment,
    ensure_bills_since_move_in,
    parse_bill_ids,
)
from payments.models import ManualPayment
from rentals.models import Lease, Unit
from water.models import WaterBill


class BillingWorkflowTests(TestCase):
    def setUp(self):
        self.tenant = User.objects.create_user(
            email="tenant@example.com",
            username="tenant",
            password="password123",
            role=User.Role.TENANT,
        )
        self.other_tenant = User.objects.create_user(
            email="other@example.com",
            username="other",
            password="password123",
            role=User.Role.TENANT,
        )
        self.unit = Unit.objects.create(number="A-101")
        self.other_unit = Unit.objects.create(number="A-102")
        self.lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=Decimal("10000.00"),
            due_day=31,
            start_date=date(2026, 1, 15),
            is_active=True,
        )
        self.other_lease = Lease.objects.create(
            tenant=self.other_tenant,
            unit=self.other_unit,
            monthly_rent=Decimal("8000.00"),
            due_day=5,
            start_date=date(2026, 1, 1),
            is_active=True,
        )

    def test_ensure_bills_since_move_in_creates_one_bill_per_month(self):
        WaterBill.objects.create(
            unit=self.unit,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
            rate_per_cu_m=Decimal("10.00"),
            prev_reading=Decimal("1.00"),
            curr_reading=Decimal("6.00"),
            status="POSTED",
        )

        ensure_bills_since_move_in(self.lease, today=date(2026, 3, 3))
        ensure_bills_since_move_in(self.lease, today=date(2026, 3, 3))

        bills = list(MonthlyBill.objects.filter(lease=self.lease).order_by("billing_month"))
        self.assertEqual([bill.billing_month for bill in bills], [
            date(2026, 1, 1),
            date(2026, 2, 1),
            date(2026, 3, 1),
        ])
        self.assertEqual(len(bills), 3)
        self.assertEqual(bills[0].due_date, date(2026, 1, 31))
        self.assertEqual(bills[1].water_amount, Decimal("50.00"))

    def test_approve_manual_payment_is_idempotent_and_scoped_to_payment_owner(self):
        tenant_bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 2, 1),
            due_date=date(2026, 2, 28),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10000.00"),
        )
        other_bill = MonthlyBill.objects.create(
            lease=self.other_lease,
            billing_month=date(2026, 2, 1),
            due_date=date(2026, 2, 5),
            base_rent=Decimal("8000.00"),
            water_amount=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("8000.00"),
        )
        payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-123",
            bill_ids=f"{tenant_bill.id},{tenant_bill.id},{other_bill.id},invalid",
        )

        approve_manual_payment(payment)
        approve_manual_payment(payment)

        tenant_bill.refresh_from_db()
        other_bill.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(payment.status, "APPROVED")
        self.assertEqual(tenant_bill.status, "PAID")
        self.assertEqual(tenant_bill.payment_reference, "REF-123")
        self.assertIsNotNone(tenant_bill.paid_at)
        self.assertEqual(other_bill.status, "UNPAID")
        self.assertEqual(parse_bill_ids(payment.bill_ids), [tenant_bill.id, other_bill.id])

    def test_deleting_bill_removes_payment_history_reference(self):
        bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 4, 1),
            due_date=date(2026, 4, 30),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10000.00"),
        )
        payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-DELETE",
            bill_ids=f"{bill.id},9999",
            status="APPROVED",
        )

        bill.delete()
        payment.refresh_from_db()

        self.assertEqual(payment.bill_ids, "9999")


class LeaseActivationTimezoneTests(TestCase):
    """
    Ensure Lease.save() uses timezone.localdate() (Asia/Manila)
    so leases starting "today" in PH time are always marked active,
    even when UTC date is still yesterday.
    """

    def setUp(self):
        self.tenant = User.objects.create_user(
            email="tz_tenant@example.com",
            username="tz_tenant",
            password="password123",
            role=User.Role.TENANT,
        )
        self.unit = Unit.objects.create(number="TZ-001")

    def test_lease_active_when_start_date_is_today_local(self):
        from django.utils import timezone
        today_local = timezone.localdate()
        lease = Lease.objects.create(
            tenant=self.tenant, unit=self.unit,
            monthly_rent=Decimal("10000.00"), due_day=5, start_date=today_local,
        )
        self.assertTrue(lease.is_active)

    def test_lease_active_when_start_date_is_in_past(self):
        lease = Lease.objects.create(
            tenant=self.tenant, unit=self.unit,
            monthly_rent=Decimal("10000.00"), due_day=5, start_date=date(2025, 1, 1),
        )
        self.assertTrue(lease.is_active)

    def test_lease_inactive_when_start_date_is_future(self):
        from django.utils import timezone
        from datetime import timedelta
        tomorrow = timezone.localdate() + timedelta(days=1)
        lease = Lease.objects.create(
            tenant=self.tenant, unit=self.unit,
            monthly_rent=Decimal("10000.00"), due_day=5, start_date=tomorrow,
        )
        self.assertFalse(lease.is_active)

    def test_lease_uses_localdate_not_utc(self):
        """Simulate 1 AM Manila (May 25) = 5 PM UTC (May 24). Lease starting May 25 must be active."""
        from unittest.mock import patch
        from django.utils import timezone
        from datetime import datetime
        import zoneinfo

        fake_now = datetime(2026, 5, 24, 17, 0, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))
        with patch("django.utils.timezone.now", return_value=fake_now):
            local_date = timezone.localdate()
            lease = Lease.objects.create(
                tenant=self.tenant, unit=self.unit,
                monthly_rent=Decimal("10000.00"), due_day=5, start_date=date(2026, 5, 25),
            )
            self.assertEqual(local_date, date(2026, 5, 25))
            self.assertTrue(lease.is_active)


class MoveInFirstMonthPaidTests(TestCase):
    """
    Ensure the move-in flow marks the first month bill as PAID.
    """

    def setUp(self):
        self.tenant = User.objects.create_user(
            email="movein_tenant@example.com",
            username="movein_tenant",
            password="password123",
            role=User.Role.TENANT,
        )
        self.unit = Unit.objects.create(number="MI-001")

    def test_first_month_bill_marked_paid_after_move_in(self):
        from billing.services import month_start, get_or_update_monthly_bill, set_bill_status, ensure_bills_since_move_in
        from django.utils import timezone

        today_local = timezone.localdate()
        lease = Lease.objects.create(
            tenant=self.tenant, unit=self.unit,
            monthly_rent=Decimal("11666.00"), due_day=5, start_date=today_local,
        )
        ensure_bills_since_move_in(lease)

        first_bill_month = month_start(lease.start_date)
        first_bill = MonthlyBill.objects.filter(lease=lease, billing_month=first_bill_month).first()
        if not first_bill:
            first_bill = get_or_update_monthly_bill(lease, first_bill_month)

        self.assertIsNotNone(first_bill)

        set_bill_status(first_bill, status="PAID", payment_reference="REF-MOVEIN-TEST", paid_at=timezone.now())
        move_in_payment = ManualPayment.objects.create(
            user=self.tenant, payment_type="move_in", payment_method="GCASH",
            amount=lease.total_move_in_cost, reference_code="REF-MOVEIN-TEST",
            bill_ids=str(first_bill.id), status="APPROVED",
        )

        first_bill.refresh_from_db()
        self.assertEqual(first_bill.status, "PAID")
        self.assertEqual(first_bill.rent_paid, lease.monthly_rent)
        self.assertEqual(first_bill.total_balance, 0)
        self.assertEqual(move_in_payment.bill_ids, str(first_bill.id))

    def test_fallback_creates_first_bill_when_ensure_bills_skipped(self):
        from billing.services import month_start, get_or_update_monthly_bill

        lease = Lease.objects.create(
            tenant=self.tenant, unit=self.unit,
            monthly_rent=Decimal("10000.00"), due_day=5, start_date=date(2026, 5, 25),
        )
        first_bill_month = month_start(lease.start_date)
        self.assertEqual(MonthlyBill.objects.filter(lease=lease, billing_month=first_bill_month).count(), 0)

        first_bill = get_or_update_monthly_bill(lease, first_bill_month)
        self.assertIsNotNone(first_bill)
        self.assertEqual(first_bill.base_rent, Decimal("10000.00"))
        self.assertEqual(first_bill.status, "UNPAID")
