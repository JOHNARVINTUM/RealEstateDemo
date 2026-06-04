from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.admin_notification_views import resolve_notification_target_url
from accounts.admin_portal_forms import LeaseForm
from billing.models import MonthlyBill
from maintenance.models import MaintenanceRequest
from payments.models import ManualPayment
from rentals.models import ArchivedTenant, Lease, Notification, TenantProfile, Unit
from water.models import WaterRate, WaterReading


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
            f"/admin-portal/payments/{self.payment.id}/detail/",
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

        response = self.client.get("/admin-portal/payments/")

        self.assertEqual(response.status_code, 200)
        page_payment = response.context["page_obj"][0]
        self.assertEqual(page_payment.tenant_display_name, "Tenant Person")
        self.assertEqual(page_payment.affected_months, "Sep 2026")

    def test_pending_cash_payment_detail_keeps_requested_amount_when_bill_now_paid(self):
        self.bill.status = "PAID"
        self.bill.rent_paid = self.bill.base_rent
        self.bill.parking_paid = self.bill.parking_fee
        self.bill.save(update_fields=["status", "rent_paid", "parking_paid"])
        pending_cash_payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-F2F-PENDING",
            bill_ids=str(self.bill.id),
            payment_type="rent_only",
            payment_method="CASH",
            amount=Decimal("10350.00"),
            status="PENDING",
        )
        self.client.force_login(self.admin)

        response = self.client.get(f"/admin-portal/payments/{pending_cash_payment.id}/detail/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["bills"][0]["rent"], Decimal("10000.00"))
        self.assertEqual(response.context["bills"][0]["parking"], Decimal("350.00"))
        self.assertEqual(response.context["bills"][0]["total"], Decimal("10350.00"))
        self.assertContains(response, "₱10,350.00")


class AdminWaterSaveBehaviorTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="water-admin@example.com",
            username="wateradmin",
            password="password123",
        )
        self.tenant = User.objects.create_user(
            email="water-tenant@example.com",
            username="watertenant",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=self.tenant,
            first_name="Water",
            last_name="Tenant",
            password_change_required=False,
            created_by=None,
        )
        self.unit = Unit.objects.create(number="W-101", status="OCCUPIED")
        self.lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 1, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        WaterRate.objects.create(
            effective_date=date(2026, 6, 1),
            rate_per_cu_m=Decimal("45.00"),
        )
        self.reading = WaterReading.objects.create(
            lease=self.lease,
            reading_month=date(2026, 6, 1),
            previous_reading=Decimal("0.00"),
            current_reading=Decimal("10.00"),
            consumption=Decimal("10.00"),
            rate_used=Decimal("45.00"),
            computed_amount=Decimal("450.00"),
        )
        self.bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 6, 1),
            base_rent=Decimal("10000.00"),
            rent_paid=Decimal("10000.00"),
            water_amount=Decimal("450.00"),
            water_paid=Decimal("0.00"),
            total_due=Decimal("10450.00"),
            status="PARTIALLY_PAID",
            source_water_reading=self.reading,
        )

    def test_water_save_ignores_completed_readings(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            "/admin-portal/water/process/",
            {
                "month": "6",
                "year": "2026",
                "lease_ids": [str(self.lease.id)],
                f"reading_{self.lease.id}": "10.00",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(WaterReading.objects.filter(lease=self.lease, reading_month=date(2026, 6, 1)).count(), 1)
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.water_amount, Decimal("450.00"))
        self.assertEqual(self.bill.status, "PARTIALLY_PAID")

    def test_water_filter_keeps_shared_pump_percentage_denominator_global(self):
        other_tenant = User.objects.create_user(
            email="water-other@example.com",
            username="waterother",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=other_tenant,
            first_name="Other",
            last_name="Tenant",
            password_change_required=False,
            created_by=None,
        )
        other_unit = Unit.objects.create(number="W-102", status="OCCUPIED")
        other_lease = Lease.objects.create(
            tenant=other_tenant,
            unit=other_unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 1, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        WaterReading.objects.create(
            lease=other_lease,
            reading_month=date(2026, 6, 1),
            previous_reading=Decimal("0.00"),
            current_reading=Decimal("30.00"),
            consumption=Decimal("30.00"),
            rate_used=Decimal("45.00"),
            computed_amount=Decimal("1350.00"),
        )
        self.client.force_login(self.admin)

        response = self.client.get("/admin-portal/water/?month=6&year=2026&search=W-101")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "25.00%")
        self.assertNotContains(response, "100.00%")


class AdminNotificationBehaviorTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin-notify@example.com",
            username="adminnotify",
            password="password123",
        )
        self.tenant = User.objects.create_user(
            email="notify-tenant@example.com",
            username="notifytenant",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=self.tenant,
            first_name="Notify",
            last_name="Tenant",
            password_change_required=False,
            created_by=None,
        )

    def test_delete_all_read_notifications_keeps_unread(self):
        read_notification = Notification.objects.create(
            title="Read",
            message="Done",
            notification_type="SYSTEM",
            recipient_type="ADMIN",
            is_read=True,
            read_at=timezone.now(),
        )
        unread_notification = Notification.objects.create(
            title="Unread",
            message="Pending",
            notification_type="SYSTEM",
            recipient_type="ADMIN",
            is_read=False,
        )
        self.client.force_login(self.admin)

        response = self.client.post(reverse("admin_delete_all_read_notifications"))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Notification.objects.filter(pk=read_notification.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=unread_notification.pk).exists())

    def test_old_read_notifications_are_purged_on_admin_notification_page(self):
        old_read = Notification.objects.create(
            title="Old Read",
            message="Old",
            notification_type="SYSTEM",
            recipient_type="ADMIN",
            is_read=True,
            read_at=timezone.now() - timedelta(days=2),
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_notifications"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Notification.objects.filter(pk=old_read.pk).exists())

    def test_payment_notifications_show_view_for_approved_and_approve_for_pending(self):
        approved_payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="PAY-APPROVED-1",
            payment_method="PAYMONGO",
            payment_type="full",
            amount=Decimal("1000.00"),
            status="APPROVED",
        )
        pending_payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="PAY-PENDING-1",
            payment_method="GCASH",
            payment_type="full",
            amount=Decimal("1000.00"),
            status="PENDING",
        )
        Notification.objects.create(
            title="Approved PayMongo",
            message=f"Reference: {approved_payment.reference_code}. Paid.",
            notification_type="PAYMENT",
            recipient_type="ADMIN",
            related_tenant=self.tenant,
        )
        Notification.objects.create(
            title="Pending GCash",
            message=f"Reference: {pending_payment.reference_code}. Please review.",
            notification_type="PAYMENT",
            recipient_type="ADMIN",
            related_tenant=self.tenant,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_notifications"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "View Payment")
        self.assertContains(response, "Approve Payment")

    def test_cash_schedule_notification_without_reference_prefers_pending_cash_payment(self):
        cash_payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-F2F-CASH",
            payment_method="CASH",
            payment_type="rent_only",
            amount=Decimal("9000.00"),
            status="PENDING",
        )
        ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-PM-NEWER",
            payment_method="PAYMONGO",
            payment_type="rent_only",
            amount=Decimal("9000.00"),
            status="APPROVED",
        )
        notification = Notification.objects.create(
            title="Cash Payment Scheduled",
            message=(
                f"{self.tenant.email} requested F2F cash payment of ₱9000.0 "
                "on Jun 04, 2026 at 01:00 PM. Please confirm availability."
            ),
            notification_type="PAYMENT",
            recipient_type="ADMIN",
            related_tenant=self.tenant,
        )

        target_url = resolve_notification_target_url(notification)

        self.assertEqual(target_url, reverse("admin_payment_detail", args=[cash_payment.id]))
        self.assertEqual(notification.target_label, "Approve Payment")


class AdminForecastingRevenueTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="forecast-admin@example.com",
            username="forecastadmin",
            password="password123",
        )
        self.tenant = User.objects.create_user(
            email="forecast-tenant@example.com",
            username="forecasttenant",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=self.tenant,
            first_name="Forecast",
            last_name="Tenant",
            password_change_required=False,
            created_by=None,
        )
        self.unit = Unit.objects.create(number="F-101", status="OCCUPIED")
        self.lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=Decimal("300000.00"),
            due_day=5,
            start_date=date(2026, 1, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )

    def test_forecasting_actual_revenue_uses_collected_amount_not_billed_amount(self):
        target_month = timezone.now().date().replace(day=1)
        MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=target_month,
            due_date=target_month.replace(day=5),
            base_rent=Decimal("300000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("300000.00"),
            rent_paid=Decimal("114000.00"),
            status="PARTIALLY_PAID",
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_forecasting"))

        self.assertEqual(response.status_code, 200)
        target_label = target_month.strftime("%b %Y")
        month_index = response.context["hist_labels"].index(target_label)
        self.assertEqual(response.context["hist_revenue"][month_index], 114000.0)


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

    def test_admin_tenant_detail_back_url_preserves_search_state(self):
        self.client.force_login(self.admin)
        next_url = "/admin-portal/tenants/?q=John+C&lease=active&page=2"

        response = self.client.get(
            f"/admin-portal/tenants/{self.tenant_john.tenantprofile.id}/?next=%2Fadmin-portal%2Ftenants%2F%3Fq%3DJohn%2BC%26lease%3Dactive%26page%3D2"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["back_url"], next_url)

    def test_admin_units_search_no_longer_raises_q_error(self):
        Unit.objects.create(number="700", monthly_rent=Decimal("10000.00"), status="AVAILABLE")
        self.client.force_login(self.admin)

        response = self.client.get("/admin-portal/units/?search=700&status=all")

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.context["page_obj"].paginator.count, 1)

    def test_admin_can_open_inactive_maintenance_unit_detail(self):
        unit = Unit.objects.create(
            number="702",
            monthly_rent=Decimal("10000.00"),
            status="MAINTENANCE",
            is_active=False,
        )
        self.client.force_login(self.admin)

        response = self.client.get(f"/admin-portal/units/{unit.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["unit"], unit)

    def test_admin_cannot_open_inactive_non_maintenance_unit_detail(self):
        unit = Unit.objects.create(
            number="703",
            monthly_rent=Decimal("10000.00"),
            status="AVAILABLE",
            is_active=False,
        )
        self.client.force_login(self.admin)

        response = self.client.get(f"/admin-portal/units/{unit.id}/")

        self.assertEqual(response.status_code, 404)

    def test_admin_can_open_inactive_occupied_unit_with_active_lease(self):
        unit = Unit.objects.create(
            number="704",
            monthly_rent=Decimal("10000.00"),
            status="OCCUPIED",
            is_active=False,
        )
        Lease.objects.create(
            tenant=self.tenant_john,
            unit=unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 6, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        self.client.force_login(self.admin)

        response = self.client.get(f"/admin-portal/units/{unit.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["unit"], unit)

    def test_admin_can_restore_inactive_occupied_unit_with_active_lease(self):
        unit = Unit.objects.create(
            number="705",
            monthly_rent=Decimal("10000.00"),
            status="OCCUPIED",
            is_active=False,
        )
        Lease.objects.create(
            tenant=self.tenant_john,
            unit=unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 6, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        self.client.force_login(self.admin)

        response = self.client.post(f"/admin-portal/units/{unit.id}/restore/")

        unit.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(unit.is_active)
        self.assertEqual(unit.status, "OCCUPIED")

    def test_pending_payment_unit_card_shows_pending_tenant_not_missing_info(self):
        unit = Unit.objects.create(
            number="706",
            monthly_rent=Decimal("10000.00"),
            status="OCCUPIED",
        )
        Lease.objects.create(
            tenant=self.tenant_john,
            unit=unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 6, 1),
            status=Lease.STATUS_PENDING_PAYMENT,
            is_active=False,
        )
        self.client.force_login(self.admin)

        response = self.client.get("/admin-portal/units/?search=706&status=all")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("John Constantine", content)
        self.assertIn("Pending move-in payment", content)
        self.assertIn("Pending Payment", content)
        self.assertNotIn("Reserved", content)
        self.assertNotIn("Occupied (missing info)", content)

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

    def test_new_lease_keeps_unit_available_until_move_in_payment(self):
        self.client.force_login(self.admin)
        tenant = User.objects.create_user(
            email="pending-create@example.com",
            username="pendingcreate",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=tenant,
            first_name="Pending",
            last_name="Create",
            password_change_required=False,
            created_by=None,
        )
        unit = Unit.objects.create(
            number="C-701",
            monthly_rent=Decimal("10000.00"),
            status="AVAILABLE",
        )

        response = self.client.post(
            "/admin-portal/leases/add/",
            {
                "tenant": tenant.id,
                "unit": unit.id,
                "monthly_rent": "10000.00",
                "due_day": "1",
                "start_date": "2026-06-01",
                "end_date": "",
                "security_deposit": "20000.00",
                "motorcycle_slots": "0",
                "car_slots": "0",
            },
        )

        unit.refresh_from_db()
        lease = Lease.objects.get(tenant=tenant, unit=unit)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(lease.status, Lease.STATUS_PENDING_PAYMENT)
        self.assertFalse(lease.is_active)
        self.assertEqual(unit.status, "AVAILABLE")

    def test_admin_can_cancel_pending_lease_from_unit_context(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            f"/admin-portal/leases/{self.lease.id}/delete/?next=unit",
            {"admin_password": "password123"},
        )

        self.unit.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"/admin-portal/units/{self.unit.id}/")
        self.assertFalse(Lease.objects.filter(pk=self.lease.pk).exists())
        self.assertEqual(self.unit.status, "AVAILABLE")

    def test_pending_lease_detail_pages_show_cancel_action(self):
        self.client.force_login(self.admin)

        unit_response = self.client.get(f"/admin-portal/units/{self.unit.id}/")
        payment_response = self.client.get(f"/admin-portal/leases/{self.lease.id}/payment/")

        self.assertEqual(unit_response.status_code, 200)
        self.assertEqual(payment_response.status_code, 200)
        self.assertContains(unit_response, "Cancel Pending Lease")
        self.assertContains(payment_response, "Cancel Pending Lease")


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
