from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from billing.models import MonthlyBill
from payments.models import ManualPayment
from payments.services import should_relabel_full_payment_as_rent_only
from rentals.models import Lease, Unit


class AdvancePaymentRelabelTests(TestCase):
    def setUp(self):
        self.tenant = User.objects.create_user(
            email="tenant@example.com",
            username="tenant",
            password="password123",
            role=User.Role.TENANT,
        )
        self.unit = Unit.objects.create(number="P-101")
        self.lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 1, 1),
            is_active=True,
        )

    def test_relabels_full_payment_when_amount_matches_rent_and_parking_only(self):
        bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 2, 1),
            due_date=date(2026, 2, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("1200.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("11550.00"),
        )
        payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-ADV-1",
            bill_ids=str(bill.id),
            payment_type="full",
            amount=Decimal("10350.00"),
        )

        self.assertTrue(should_relabel_full_payment_as_rent_only(payment))

    def test_does_not_relabel_true_full_payment_including_water(self):
        bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 2, 1),
            due_date=date(2026, 2, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("1200.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("11550.00"),
        )
        payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-FULL-1",
            bill_ids=str(bill.id),
            payment_type="full",
            amount=Decimal("11550.00"),
        )

        self.assertFalse(should_relabel_full_payment_as_rent_only(payment))
