from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from accounts.admin_portal_forms import LeaseForm
from billing.models import MonthlyBill
from maintenance.models import MaintenanceRequest
from payments.models import ManualPayment
from rentals.models import ArchivedTenant, Lease, Notification, TenantProfile, Unit


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


class AdminTenantAndUnitSearchTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin-search@example.com",
            username="adminsearch",
            password="password123",
        )
        self.tenant_john = User.objects.create_user(
            email="john.constantine@example.com",
            username="johnconstantine",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=self.tenant_john,
            first_name="John",
            last_name="Constantine",
            contact_no="09170000001",
            password_change_required=False,
            created_by=None,
        )
        self.tenant_mary = User.objects.create_user(
            email="mary.sue@example.com",
            username="marysue",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=self.tenant_mary,
            first_name="Mary",
            last_name="Sue",
            contact_no="09170000002",
            password_change_required=False,
            created_by=None,
        )

    def test_admin_tenant_search_supports_multi_word_queries(self):
        self.client.force_login(self.admin)

        response = self.client.get("/admin-portal/tenants/?q=John+C")

        self.assertEqual(response.status_code, 200)
        tenant_ids = [tenant.id for tenant in response.context["page_obj"]]
        self.assertIn(self.tenant_john.tenantprofile.id, tenant_ids)
        self.assertNotIn(self.tenant_mary.tenantprofile.id, tenant_ids)

    def test_admin_units_search_no_longer_raises_q_error(self):
        Unit.objects.create(number="700", monthly_rent=Decimal("10000.00"), status="AVAILABLE")
        self.client.force_login(self.admin)

        response = self.client.get("/admin-portal/units/?search=700&status=all")

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.context["page_obj"].paginator.count, 1)

    def test_new_lease_form_blocks_occupied_units(self):
        occupied_unit = Unit.objects.create(number="701", monthly_rent=Decimal("12000.00"), status="OCCUPIED")
        tenant = User.objects.create_user(
            email="tenant.form@example.com",
            username="tenantform",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=tenant,
            first_name="Tenant",
            last_name="Form",
            password_change_required=False,
            created_by=None,
        )

        form = LeaseForm(
            data={
                "tenant": tenant.id,
                "unit": occupied_unit.id,
                "monthly_rent": "12000.00",
                "due_day": "5",
                "start_date": "2026-06-01",
                "end_date": "",
                "security_deposit": "24000.00",
                "motorcycle_slots": "0",
                "car_slots": "0",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("unit", form.errors)


class AdminCashMoveInNotificationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin-cash@example.com",
            username="admincash",
            password="password123",
        )
        self.tenant = User.objects.create_user(
            email="john.constantine@example.com",
            username="johncash",
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
        self.unit = Unit.objects.create(
            number="C-700",
            monthly_rent=Decimal("10000.00"),
            status="AVAILABLE",
        )
        self.lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 6, 1),
            security_deposit=Decimal("20000.00"),
            status=Lease.STATUS_PENDING_PAYMENT,
            is_active=False,
        )

    def test_cash_move_in_activation_creates_admin_notification_for_tenant(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            f"/admin-portal/leases/{self.lease.id}/payment/",
            {
                "payment_method": "CASH",
                "admin_password": "password123",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        notification = Notification.objects.filter(
            title="Move-in Payment Received - Lease Activated",
            related_tenant=self.tenant,
            recipient_type="ADMIN",
        ).latest("created_at")
        self.assertIn("John Constantine", notification.message)
        self.assertIn("Face-to-Face Cash", notification.message)
        self.assertNotIn("admin-cash@example.com", notification.message)


class AdminTenantDeleteArchiveTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin-delete@example.com",
            username="admindelete",
            password="password123",
        )
        self.tenant = User.objects.create_user(
            email="archive.tenant@example.com",
            username="archivetenant",
            password="password123",
            role=User.Role.TENANT,
        )
        self.profile = TenantProfile.objects.create(
            user=self.tenant,
            first_name="Archive",
            last_name="Tenant",
            password_change_required=False,
            created_by=None,
        )
        self.unit = Unit.objects.create(
            number="A-245",
            monthly_rent=Decimal("10000.00"),
            status="OCCUPIED",
        )
        self.lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 6, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-ARCHIVE-1",
            payment_method="CASH",
            payment_type="full",
            amount=Decimal("10000.00"),
            status="APPROVED",
        )
        MaintenanceRequest.objects.create(
            tenant=self.tenant,
            lease=self.lease,
            category="PLUMBING",
            title="Archive Test Request",
            description="Leaking faucet",
        )

    def test_archive_tenant_serializes_record_snapshot_dates(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            f"/admin-portal/tenants/{self.profile.id}/delete/",
            {
                "phase": "2",
                "admin_password": "password123",
                "deletion_type": "ARCHIVE",
                "deletion_reason": "Regression test",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        archive = ArchivedTenant.objects.get(original_tenant_id=self.profile.id)
        summary = archive.tenant_data["records_summary"]
        self.assertIsInstance(summary["leases"][0]["start_date"], str)
        self.assertIsInstance(summary["payments_sample"][0]["created_at"], str)
        self.assertIsInstance(summary["maintenance_sample"][0]["created_at"], str)
