from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

from accounts.models import User
from accounts.admin_payment_views import _admin_payment_queryset
from billing.models import MonthlyBill
from payments.models import ManualPayment
from payments.paymongo_workflow import (
    auto_approve_paymongo_payment,
    get_pending_paymongo_payment,
    resolve_payment_tenant_user,
)
from payments.services import should_relabel_full_payment_as_rent_only
from rentals.models import Lease, TenantProfile, Unit


class AdvancePaymentRelabelTests(TestCase):
    def setUp(self):
        self.tenant = User.objects.create_user(
            email="tenant@gmail.com",
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
            email="john.constantine@gmail.com",
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

        self.assertEqual(resolve_payment_tenant_user(payment), self.tenant)

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

        with patch("payments.paymongo_workflow.Notification.create_notification") as notify_mock:
            auto_approve_paymongo_payment(payment)

        notify_mock.assert_called_once()
        kwargs = notify_mock.call_args.kwargs
        self.assertEqual(kwargs["related_tenant"], self.tenant)
        self.assertIn("John Constantine", kwargs["message"])
        self.assertNotIn("john.constantine@gmail.com", kwargs["message"])
        self.assertNotIn("stamaria@admin.com", kwargs["message"])

    def test_admin_generated_paymongo_checkout_is_owned_by_tenant(self):
        self.client.force_login(self.admin)
        self.lease.status = Lease.STATUS_PENDING_PAYMENT
        self.lease.is_active = False
        self.lease.save(update_fields=["status", "is_active"])

        with patch("payments.views.create_paymongo_checkout_session_or_error") as checkout_mock:
            checkout_mock.return_value = (
                {
                    "checkout_session_id": "cs_test_admin_movein",
                    "checkout_url": "https://checkout.test/session",
                },
                None,
            )
            response = self.client.get(
                reverse("admin_paymongo_checkout"),
                {
                    "amount": "30725.00",
                    "lease_id": str(self.lease.id),
                    "tenant_id": str(self.tenant.id),
                },
            )

        self.assertEqual(response.status_code, 302)
        payment = ManualPayment.objects.get(checkout_session_id="cs_test_admin_movein")
        self.assertEqual(payment.user, self.tenant)
        self.assertEqual(payment.metadata["generated_by_admin"], str(self.admin.id))
        self.assertEqual(payment.metadata["tenant_id"], str(self.tenant.id))
        self.assertEqual(payment.metadata["lease_id"], str(self.lease.id))

    def test_admin_can_resolve_tenant_owned_checkout_by_session_id(self):
        payment = ManualPayment.objects.create(
            user=self.tenant,
            payment_type="move_in",
            payment_method="PAYMONGO",
            amount=Decimal("30725.00"),
            reference_code="REF-PM-ADMIN",
            status="PENDING",
            checkout_session_id="cs_test_admin_lookup",
            metadata={
                "generated_by_admin": str(self.admin.id),
                "tenant_id": str(self.tenant.id),
                "lease_id": str(self.lease.id),
            },
        )

        self.assertEqual(get_pending_paymongo_payment(self.admin, "cs_test_admin_lookup"), payment)

    def test_pending_paymongo_move_in_for_active_lease_is_finalized(self):
        payment = ManualPayment.objects.create(
            user=self.tenant,
            payment_type="move_in",
            payment_method="PAYMONGO",
            amount=Decimal("36000.00"),
            reference_code="REF-PM-ACTIVE",
            status="PENDING",
            checkout_session_id="cs_test_active_movein",
            metadata={
                "generated_by_admin": str(self.admin.id),
                "tenant_id": str(self.tenant.id),
                "lease_id": str(self.lease.id),
            },
        )

        with patch("payments.paymongo_workflow.Notification.create_notification"):
            auto_approve_paymongo_payment(payment)

        payment.refresh_from_db()
        first_bill = MonthlyBill.objects.get(lease=self.lease, billing_month=date(2026, 6, 1))
        self.assertEqual(payment.status, "APPROVED")
        self.assertEqual(payment.bill_ids, str(first_bill.id))
        self.assertEqual(first_bill.status, "PAID")
        self.assertEqual(first_bill.payment_reference, "REF-PM-ACTIVE")

    def test_admin_payment_queryset_excludes_unpaid_paymongo_checkout_drafts(self):
        draft = ManualPayment.objects.create(
            user=self.tenant,
            payment_type="rent_only",
            payment_method="PAYMONGO",
            amount=Decimal("10475.00"),
            reference_code="REF-PM-DRAFT",
            status="PENDING",
            checkout_session_id="cs_test_cancelled",
        )
        paid_pending = ManualPayment.objects.create(
            user=self.tenant,
            payment_type="rent_only",
            payment_method="PAYMONGO",
            amount=Decimal("10475.00"),
            reference_code="REF-PM-PAID",
            status="PENDING",
            checkout_session_id="cs_test_paid",
            paymongo_payment_id="pay_test_paid",
        )

        payments = list(_admin_payment_queryset())

        self.assertNotIn(draft, payments)
        self.assertIn(paid_pending, payments)


class F2FCashScheduleTests(TestCase):
    def setUp(self):
        self.tenant = User.objects.create_user(
            email="cash.tenant@gmail.com",
            username="cashtenant",
            password="password123",
            role=User.Role.TENANT,
        )

    def test_f2f_cash_rejects_weekend_and_outside_office_hours(self):
        self.client.force_login(self.tenant)
        url = reverse("f2f_cash_payment")

        weekend_response = self.client.post(url, {
            "amount": "1000.00",
            "bill_ids": "1",
            "payment_type": "rent_only",
            "preferred_date": "2026-06-06",
            "preferred_time": "10:00",
        })
        out_of_hours_response = self.client.post(url, {
            "amount": "1000.00",
            "bill_ids": "1",
            "payment_type": "rent_only",
            "preferred_date": "2026-06-05",
            "preferred_time": "18:00",
        })

        self.assertEqual(weekend_response.status_code, 200)
        self.assertContains(weekend_response, "Monday to Friday")
        self.assertEqual(out_of_hours_response.status_code, 200)
        self.assertContains(out_of_hours_response, "office hours")
        self.assertEqual(ManualPayment.objects.filter(payment_method="CASH").count(), 0)
