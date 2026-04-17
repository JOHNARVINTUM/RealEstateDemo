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
