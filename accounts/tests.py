from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from billing.models import MonthlyBill
from payments.models import ManualPayment
from rentals.models import Lease, TenantProfile, Unit


class AdminPaymentTypeEditTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            username="admin",
            password="password123",
        )
        self.tenant = User.objects.create_user(
            email="tenant@example.com",
            username="tenant",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=self.tenant,
            first_name="Tenant",
            last_name="Person",
            password_change_required=False,
            created_by=None,
        )
        self.unit = Unit.objects.create(number="T-101")
        self.lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 1, 1),
            is_active=True,
        )
        self.bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 9, 1),
            due_date=date(2026, 9, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10350.00"),
            status="PAID",
        )
        self.payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-F2F-TEST",
            bill_ids=str(self.bill.id),
            payment_type="full",
            payment_method="CASH",
            amount=Decimal("10350.00"),
            status="APPROVED",
        )

    def test_admin_can_change_payment_type_from_full_to_rent_only(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            f"/admin/payments/{self.payment.id}/detail/",
            {
                "action": "update_payment_type",
                "payment_type": "rent_only",
            },
            follow=True,
        )

        self.payment.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.payment.payment_type, "rent_only")
        self.assertEqual(self.payment.metadata.get("payment_type"), "rent_only")

    def test_admin_payments_context_uses_tenant_full_name_and_affected_month(self):
        self.client.force_login(self.admin)

        response = self.client.get("/admin/payments/")

        self.assertEqual(response.status_code, 200)
        page_payment = response.context["page_obj"][0]
        self.assertEqual(page_payment.tenant_display_name, "Tenant Person")
        self.assertEqual(page_payment.affected_months, "Sep 2026")
