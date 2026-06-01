from datetime import date
from decimal import Decimal

from django.test import TestCase
from unittest.mock import patch

from accounts.models import User
from billing.models import MonthlyBill
from payments.models import ManualPayment
from payments.services import should_relabel_full_payment_as_rent_only
from payments.views import _resolve_payment_tenant_user, _auto_approve_paymongo_payment
from rentals.models import Lease, TenantProfile, Unit


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


class MoveInPaymentNotificationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="stamaria@admin.com",
            username="stamaria",
            password="password123",
            role=User.Role.ADMIN,
        )
        self.tenant = User.objects.create_user(
            email="john.constantine@example.com",
            username="johnconstantine",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=self.tenant,
            first_name="John",
            last_name="Constantine",
            password_change_required=False,
            created_by=None,
        )
        self.unit = Unit.objects.create(number="P-202")
        self.lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=Decimal("12000.00"),
            due_day=5,
            start_date=date(2026, 6, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )

    def test_resolve_payment_tenant_user_prefers_metadata_tenant_id(self):
        payment = ManualPayment(
            user=self.admin,
            payment_type="move_in",
            metadata={"tenant_id": self.tenant.id, "lease_id": self.lease.id},
        )

        self.assertEqual(_resolve_payment_tenant_user(payment), self.tenant)

    def test_move_in_notification_uses_tenant_identity(self):
        payment = ManualPayment.objects.create(
            user=self.admin,
            payment_type="move_in",
            payment_method="PAYMONGO",
            amount=Decimal("49896.00"),
            reference_code="REF-PM-772F8DF8",
            status="PENDING",
            metadata={"tenant_id": self.tenant.id, "lease_id": self.lease.id},
        )

        with patch("payments.views.Notification.create_notification") as notify_mock:
            _auto_approve_paymongo_payment(payment)

        notify_mock.assert_called_once()
        kwargs = notify_mock.call_args.kwargs
        self.assertEqual(kwargs["related_tenant"], self.tenant)
        self.assertIn("John Constantine", kwargs["message"])
        self.assertNotIn("john.constantine@example.com", kwargs["message"])
        self.assertNotIn("stamaria@admin.com", kwargs["message"])
