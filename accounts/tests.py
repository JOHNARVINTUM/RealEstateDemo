from datetime import date, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.admin_notification_views import resolve_notification_target_url
from accounts.admin_portal_forms import LeaseForm, TenantProfileForm
from billing.models import MonthlyBill
from maintenance.models import MaintenanceRequest
from payments.models import ManualPayment
from rentals.models import ArchivedTenant, Lease, Notification, TenantAttachment, TenantProfile, Unit
from water.models import WaterRate, WaterReading


class AccountProfileTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="profile-admin@example.com",
            username="profileadmin",
            password="password123",
            role=User.Role.ADMIN,
        )
        self.tenant = User.objects.create_user(
            email="profile-tenant@example.com",
            username="profiletenant",
            password="password123",
            role=User.Role.TENANT,
        )
        self.profile = TenantProfile.objects.create(
            user=self.tenant,
            first_name="Ada",
            last_name="Lovelace",
            contact_no="09170000000",
            password_change_required=False,
            created_by=self.admin,
        )
        self.unit = Unit.objects.create(number="P-101", monthly_rent=Decimal("12000.00"))
        self.lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=Decimal("12000.00"),
            due_day=5,
            start_date=date(2026, 6, 1),
            end_date=date(2027, 6, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        self.attachment = TenantAttachment.objects.create(
            tenant=self.tenant,
            attachment_type="VALID_ID",
            file="tenant_attachments/valid-id.pdf",
            description="Government ID",
            uploaded_by=self.admin,
        )

    def test_tenant_profile_page_shows_basic_info_lease_and_files(self):
        self.client.force_login(self.tenant)

        response = self.client.get(reverse("account_profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ada Lovelace")
        self.assertContains(response, "09170000000")
        self.assertContains(response, "#P-101")
        self.assertContains(response, "Jun 01, 2027")
        self.assertContains(response, "Government ID")
        self.assertTemplateUsed(response, "accounts/profile_tenant.html")

    def test_password_change_updates_current_user_password(self):
        self.client.force_login(self.tenant)

        response = self.client.post(
            reverse("account_profile"),
            {
                "old_password": "password123",
                "new_password1": "NewPassword123!",
                "new_password2": "NewPassword123!",
            },
            follow=True,
        )

        self.tenant.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.tenant.check_password("NewPassword123!"))

    def test_attachment_view_rejects_other_tenant(self):
        other_tenant = User.objects.create_user(
            email="other-profile-tenant@example.com",
            username="otherprofiletenant",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=other_tenant,
            first_name="Other",
            last_name="Tenant",
            password_change_required=False,
            created_by=self.admin,
        )

        self.client.force_login(other_tenant)
        blocked = self.client.get(reverse("account_profile_attachment", args=[self.attachment.id]))
        self.assertEqual(blocked.status_code, 404)

    def test_admin_attachment_view_missing_file_returns_404(self):
        self.client.force_login(self.admin)
        missing_attachment = TenantAttachment.objects.create(
            tenant=self.tenant,
            attachment_type="VALID_ID",
            file="tenant_attachments/missing-file.png",
            description="Missing file",
            uploaded_by=self.admin,
        )

        response = self.client.get(reverse("admin_view_attachment", args=[missing_attachment.id]))

        self.assertEqual(response.status_code, 404)

    def test_tenant_profile_form_accepts_iphone_heic_attachment(self):
        form = TenantProfileForm(
            data={
                "email": "heic-tenant@example.com",
                "first_name": "Heic",
                "last_name": "Tenant",
                "contact_no": "09170000001",
            },
            files={
                "valid_id_file": SimpleUploadedFile("iphone-id.HEIC", b"sample", content_type="image/heic"),
            },
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_tenant_profile_form_rejects_unsupported_attachment_type(self):
        form = TenantProfileForm(
            data={
                "email": "docx-tenant@example.com",
                "first_name": "Docx",
                "last_name": "Tenant",
                "contact_no": "09170000002",
            },
            files={
                "valid_id_file": SimpleUploadedFile(
                    "id.docx",
                    b"sample",
                    content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Accepted formats", str(form.errors))


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

    def test_admin_payments_all_view_includes_pending_f2f_cash_records(self):
        ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-F2F-PENDING-1",
            bill_ids=str(self.bill.id),
            payment_type="rent_only",
            payment_method="CASH",
            amount=Decimal("10350.00"),
            status="PENDING",
            preferred_date=date(2026, 6, 5),
        )
        ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-F2F-PENDING-2",
            bill_ids=str(self.bill.id),
            payment_type="rent_only",
            payment_method="CASH",
            amount=Decimal("10350.00"),
            status="PENDING",
            preferred_date=date(2026, 6, 8),
            schedule_confirmed=True,
        )
        self.client.force_login(self.admin)

        all_response = self.client.get("/admin-portal/payments/")
        f2f_response = self.client.get("/admin-portal/payments/?status=PENDING&method=CASH")

        self.assertEqual(all_response.status_code, 200)
        self.assertEqual(f2f_response.status_code, 200)
        self.assertEqual(all_response.context["page_obj"].paginator.count, 3)
        self.assertEqual(len(all_response.context["other_payments"]), 3)
        self.assertFalse(all_response.context["is_f2f_schedule_view"])
        self.assertEqual(f2f_response.context["page_obj"].paginator.count, 2)
        self.assertEqual(len(f2f_response.context["cash_schedule_payments"]), 2)
        self.assertTrue(f2f_response.context["is_f2f_schedule_view"])
        self.assertNotContains(f2f_response, "Manage in View")
        self.assertNotContains(f2f_response, "Mark Paid")
        self.assertNotContains(f2f_response, "Confirm</span>")

    def test_admin_payments_excludes_admin_owned_payment_records(self):
        admin_owned_payment = ManualPayment.objects.create(
            user=self.admin,
            reference_code="REF-ADMIN-BAD",
            bill_ids="",
            payment_type="move_in",
            payment_method="PAYMONGO",
            amount=Decimal("30725.00"),
            status="APPROVED",
        )
        self.client.force_login(self.admin)

        response = self.client.get("/admin-portal/payments/")

        self.assertEqual(response.status_code, 200)
        payment_ids = [payment.id for payment in response.context["page_obj"].object_list]
        self.assertNotIn(admin_owned_payment.id, payment_ids)

    def test_admin_payment_calendar_groups_cash_schedules_by_week_day(self):
        first_payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-F2F-CAL-1",
            bill_ids=str(self.bill.id),
            payment_type="rent_only",
            payment_method="CASH",
            amount=Decimal("10350.00"),
            status="PENDING",
            preferred_date=date(2026, 6, 16),
            preferred_time=time(13, 0),
        )
        second_payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-F2F-CAL-2",
            bill_ids=str(self.bill.id),
            payment_type="rent_only",
            payment_method="CASH",
            amount=Decimal("5000.00"),
            status="PENDING",
            preferred_date=date(2026, 6, 18),
            preferred_time=time(15, 30),
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("admin_payment_calendar"),
            {"week": "2026-06-15", "day": "2026-06-16"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["week_start"], date(2026, 6, 15))
        self.assertEqual(response.context["week_end"], date(2026, 6, 21))
        self.assertEqual(response.context["week_total_count"], 2)
        self.assertEqual(response.context["selected_payments"], [first_payment])
        self.assertContains(response, "Tenant Person")
        self.assertContains(response, "1:00 PM")
        self.assertContains(response, "3:30 PM")
        self.assertContains(response, "REF-F2F-CAL-1")
        self.assertNotIn(second_payment, response.context["selected_payments"])

    def test_admin_payment_calendar_excludes_admin_owned_cash_records(self):
        tenant_payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-F2F-TENANT-CAL",
            bill_ids=str(self.bill.id),
            payment_type="rent_only",
            payment_method="CASH",
            amount=Decimal("10350.00"),
            status="PENDING",
            preferred_date=date(2026, 6, 16),
            preferred_time=time(13, 0),
        )
        admin_owned_payment = ManualPayment.objects.create(
            user=self.admin,
            reference_code="REF-F2F-ADMIN-CAL",
            bill_ids="",
            payment_type="rent_only",
            payment_method="CASH",
            amount=Decimal("10350.00"),
            status="PENDING",
            preferred_date=date(2026, 6, 16),
            preferred_time=time(14, 0),
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("admin_payment_calendar"),
            {"week": "2026-06-15", "day": "2026-06-16"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_payments"], [tenant_payment])
        self.assertContains(response, "REF-F2F-TENANT-CAL")
        self.assertNotContains(response, "REF-F2F-ADMIN-CAL")
        self.assertNotIn(admin_owned_payment, response.context["selected_payments"])

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

    def test_pending_cash_payment_detail_has_reschedule_action(self):
        pending_cash_payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-F2F-RESCHEDULE-ACTION",
            bill_ids=str(self.bill.id),
            payment_type="rent_only",
            payment_method="CASH",
            amount=Decimal("10350.00"),
            status="PENDING",
            preferred_date=date(2026, 6, 16),
            preferred_time=time(13, 0),
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_payment_detail", args=[pending_cash_payment.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reschedule")
        self.assertContains(response, reverse("admin_reschedule_cash_payment", args=[pending_cash_payment.id]))

    @patch("accounts.admin_payment_views.send_email_via_resend", return_value=True)
    def test_admin_can_reschedule_pending_cash_payment_and_notify_tenant(self, mock_send_email):
        pending_cash_payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-F2F-RESCHEDULE",
            bill_ids=str(self.bill.id),
            payment_type="rent_only",
            payment_method="CASH",
            amount=Decimal("10350.00"),
            status="PENDING",
            preferred_date=date(2026, 6, 16),
            preferred_time=time(13, 0),
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin_reschedule_cash_payment", args=[pending_cash_payment.id]),
            {
                "preferred_date": "2026-06-17",
                "preferred_time": "14:30",
                "schedule_admin_note": "Please visit after lunch.",
            },
            follow=True,
        )

        pending_cash_payment.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(pending_cash_payment.preferred_date, date(2026, 6, 17))
        self.assertEqual(pending_cash_payment.preferred_time, time(14, 30))
        self.assertEqual(pending_cash_payment.schedule_admin_note, "Please visit after lunch.")
        self.assertTrue(pending_cash_payment.schedule_confirmed)
        self.assertEqual(pending_cash_payment.status, "PENDING")
        self.assertTrue(
            Notification.objects.filter(
                user=self.tenant,
                title="Cash Payment Appointment Rescheduled",
                message__icontains="Please visit after lunch.",
            ).exists()
        )
        mock_send_email.assert_called_once()
        self.assertContains(response, "Cash appointment rescheduled")

    def test_admin_reschedule_rejects_weekend_cash_schedule(self):
        pending_cash_payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-F2F-WEEKEND",
            bill_ids=str(self.bill.id),
            payment_type="rent_only",
            payment_method="CASH",
            amount=Decimal("10350.00"),
            status="PENDING",
            preferred_date=date(2026, 6, 16),
            preferred_time=time(13, 0),
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin_reschedule_cash_payment", args=[pending_cash_payment.id]),
            {
                "preferred_date": "2026-06-20",
                "preferred_time": "14:30",
                "schedule_admin_note": "Weekend attempt.",
            },
        )

        pending_cash_payment.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "weekday schedule")
        self.assertEqual(pending_cash_payment.preferred_date, date(2026, 6, 16))
        self.assertEqual(pending_cash_payment.preferred_time, time(13, 0))
        self.assertEqual(pending_cash_payment.schedule_admin_note, "")


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

    def test_water_page_uses_tenant_profile_full_name(self):
        self.tenant.username = "WTenantShort"
        self.tenant.save(update_fields=["username"])
        profile = self.tenant.tenantprofile
        profile.first_name = "Display"
        profile.last_name = "Person"
        profile.save(update_fields=["first_name", "last_name"])
        self.client.force_login(self.admin)

        response = self.client.get("/admin-portal/water/?month=6&year=2026&search=Display")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Display Person")
        self.assertNotContains(response, "WTenantShort")

    def test_water_page_includes_status_active_lease_when_is_active_flag_is_stale(self):
        Lease.objects.filter(pk=self.lease.pk).update(is_active=False)
        self.client.force_login(self.admin)

        response = self.client.get("/admin-portal/water/?month=6&year=2026")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Water Tenant")
        self.assertContains(response, "#W-101")

    def test_water_page_starts_occupied_mid_month_lease_on_next_water_month(self):
        tenant = User.objects.create_user(
            email="sophia.sinco.water@example.com",
            username="sophiasincowater",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=tenant,
            first_name="Sophia",
            last_name="Sinco",
            password_change_required=False,
            created_by=None,
        )
        unit = Unit.objects.create(number="W-605", status="OCCUPIED")
        lease = Lease.objects.create(
            tenant=tenant,
            unit=unit,
            monthly_rent=Decimal("14060.00"),
            due_day=16,
            start_date=date(2026, 6, 16),
            end_date=date(2027, 6, 16),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        Lease.objects.filter(pk=lease.pk).update(status=Lease.STATUS_PENDING_PAYMENT, is_active=False)
        self.client.force_login(self.admin)

        move_in_month_response = self.client.get("/admin-portal/water/?month=6&year=2026&search=Sinco")
        next_month_response = self.client.get("/admin-portal/water/?month=7&year=2026&search=Sinco")

        self.assertEqual(move_in_month_response.status_code, 200)
        self.assertNotContains(move_in_month_response, "Sophia Sinco")
        self.assertNotContains(move_in_month_response, "#W-605")
        self.assertEqual(next_month_response.status_code, 200)
        self.assertContains(next_month_response, "Sophia Sinco")
        self.assertContains(next_month_response, "#W-605")

    def test_water_page_includes_advance_paid_contract_month_even_with_stale_lifecycle(self):
        tenant = User.objects.create_user(
            email="advance.sinco.water@example.com",
            username="advancesincowater",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=tenant,
            first_name="Sophia",
            last_name="Sinco",
            password_change_required=False,
            created_by=None,
        )
        unit = Unit.objects.create(number="W-606", status="AVAILABLE")
        lease = Lease.objects.create(
            tenant=tenant,
            unit=unit,
            monthly_rent=Decimal("14060.00"),
            due_day=16,
            start_date=date(2026, 6, 16),
            end_date=date(2027, 6, 16),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        Lease.objects.filter(pk=lease.pk).update(status=Lease.STATUS_PENDING_PAYMENT, is_active=False)
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 7, 1),
            due_date=date(2026, 7, 16),
            base_rent=Decimal("14060.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("14060.00"),
            status="PAID",
        )
        self.client.force_login(self.admin)

        response = self.client.get("/admin-portal/water/?month=7&year=2026&search=Sinco")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sophia Sinco")
        self.assertContains(response, "#W-606")


class AdminBillingSettlementWarningTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="billing-admin@example.com",
            username="billingadmin",
            password="password123",
        )
        self.tenant = User.objects.create_user(
            email="billing-tenant@example.com",
            username="billingtenant",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=self.tenant,
            first_name="Billing",
            last_name="Tenant",
            password_change_required=False,
            created_by=None,
        )
        self.unit = Unit.objects.create(number="B-101", status="OCCUPIED")
        self.lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 1, 1),
            is_active=True,
        )
        self.old_bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 5, 1),
            due_date=date(2026, 5, 5),
            base_rent=Decimal("9000.00"),
            water_amount=Decimal("500.00"),
            parking_fee=Decimal("300.00"),
            interest=Decimal("200.00"),
            total_due=Decimal("10000.00"),
            status="UNPAID",
        )
        self.current_bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 6, 1),
            due_date=date(2026, 6, 5),
            base_rent=Decimal("10125.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10475.00"),
            status="UNPAID",
        )

    def test_settle_current_bill_warns_when_prior_unpaid_balance_exists(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse("admin_mark_bill_paid", args=[self.current_bill.id]))

        self.current_bill.refresh_from_db()
        self.old_bill.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Older unpaid bills were found")
        self.assertContains(response, "May 2026")
        self.assertContains(response, "Unpaid Months to Present")
        self.assertContains(response, "Settle All")
        self.assertNotContains(response, "Settle Selected Only")
        self.assertEqual(self.current_bill.status, "UNPAID")
        self.assertEqual(self.old_bill.status, "UNPAID")

    def test_settle_warning_refreshes_stale_prior_late_fee_before_display(self):
        self.old_bill.interest = Decimal("0.00")
        self.old_bill.total_due = Decimal("9800.00")
        self.old_bill.save(update_fields=["interest", "total_due"])
        self.client.force_login(self.admin)

        response = self.client.post(reverse("admin_mark_bill_paid", args=[self.current_bill.id]))

        self.old_bill.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "300.00")
        self.assertContains(response, "10,300.00")
        self.assertEqual(self.old_bill.interest, Decimal("300.00"))
        self.assertEqual(self.old_bill.total_due, Decimal("10300.00"))
        self.assertEqual(self.old_bill.status, "UNPAID")

    def test_settle_selected_action_is_not_allowed_when_prior_balance_exists(self):
        self.client.force_login(self.admin)

        with patch("accounts.admin_billing_views.create_and_send_invoice_for_paid_bill"):
            response = self.client.post(
                reverse("admin_mark_bill_paid", args=[self.current_bill.id]),
                {"action": "settle_selected"},
            )

        self.current_bill.refresh_from_db()
        self.old_bill.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Older unpaid bills were found")
        self.assertEqual(self.current_bill.status, "UNPAID")
        self.assertEqual(self.old_bill.status, "UNPAID")

    def test_settle_all_pays_prior_balances_and_selected_bill(self):
        self.client.force_login(self.admin)

        with patch("accounts.admin_billing_views.create_and_send_invoice_for_paid_bill"):
            response = self.client.post(
                reverse("admin_mark_bill_paid", args=[self.current_bill.id]),
                {"action": "settle_all"},
            )

        self.current_bill.refresh_from_db()
        self.old_bill.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.current_bill.status, "PAID")
        self.assertEqual(self.old_bill.status, "PAID")

    def test_admin_repair_late_fees_preview_and_apply(self):
        self.old_bill.interest = Decimal("106944.75")
        self.old_bill.total_due = Decimal("116744.75")
        self.old_bill.save(update_fields=["interest", "total_due"])
        self.client.force_login(self.admin)

        preview_response = self.client.get(reverse("admin_repair_late_fees"))

        self.assertEqual(preview_response.status_code, 200)
        self.assertContains(preview_response, "Repair Inflated Late Fees")
        self.assertContains(preview_response, "106,944.75")
        self.assertContains(preview_response, "279.00")

        apply_response = self.client.post(reverse("admin_repair_late_fees"))
        self.old_bill.refresh_from_db()

        self.assertEqual(apply_response.status_code, 302)
        self.assertEqual(self.old_bill.interest, Decimal("279.00"))
        self.assertEqual(self.old_bill.total_due, Decimal("10079.00"))

    def test_admin_cleanup_duplicate_bills_removes_unpaid_duplicate_shell(self):
        paid_april = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 4, 1),
            due_date=date(2026, 4, 10),
            base_rent=Decimal("24585.00"),
            water_amount=Decimal("2084.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("26669.00"),
            status="PAID",
            rent_paid=Decimal("24585.00"),
            water_paid=Decimal("2084.00"),
        )
        duplicate_april = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 4, 10),
            due_date=date(2026, 4, 10),
            base_rent=Decimal("24585.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("737.55"),
            total_due=Decimal("25322.55"),
            status="UNPAID",
        )
        self.client.force_login(self.admin)

        preview_response = self.client.get(reverse("admin_cleanup_duplicate_bills"))

        self.assertEqual(preview_response.status_code, 200)
        self.assertContains(preview_response, "Clean Duplicate Billing Records")
        self.assertContains(preview_response, f"#{duplicate_april.id}")
        self.assertContains(preview_response, f"#{paid_april.id}")

        apply_response = self.client.post(reverse("admin_cleanup_duplicate_bills"))

        self.assertEqual(apply_response.status_code, 302)
        self.assertTrue(MonthlyBill.objects.filter(pk=paid_april.pk).exists())
        self.assertFalse(MonthlyBill.objects.filter(pk=duplicate_april.pk).exists())

    def test_settle_warning_excludes_paid_month_duplicate_unpaid_shell(self):
        paid_april = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 4, 1),
            due_date=date(2026, 4, 10),
            base_rent=Decimal("24585.00"),
            water_amount=Decimal("2084.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("26669.00"),
            status="PAID",
            rent_paid=Decimal("24585.00"),
            water_paid=Decimal("2084.00"),
        )
        duplicate_april = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 4, 10),
            due_date=date(2026, 4, 10),
            base_rent=Decimal("24585.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("737.55"),
            total_due=Decimal("25322.55"),
            status="UNPAID",
        )
        self.client.force_login(self.admin)

        response = self.client.post(reverse("admin_mark_bill_paid", args=[self.current_bill.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "May 2026")
        self.assertNotContains(response, "Apr 2026")
        self.assertTrue(MonthlyBill.objects.filter(pk=paid_april.pk).exists())

    def test_admin_billing_shows_future_paid_contract_months_in_main_table(self):
        today = date.today()
        current_month = today.replace(day=1)
        if current_month.month == 12:
            next_month = date(current_month.year + 1, 1, 1)
            following_month = date(current_month.year + 1, 2, 1)
        elif current_month.month == 11:
            next_month = date(current_month.year, 12, 1)
            following_month = date(current_month.year + 1, 1, 1)
        else:
            next_month = date(current_month.year, current_month.month + 1, 1)
            following_month = date(current_month.year, current_month.month + 2, 1)
        self.current_bill.status = "PAID"
        self.current_bill.save(update_fields=["status"])
        future_paid = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=next_month,
            due_date=next_month.replace(day=5),
            base_rent=Decimal("10125.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10475.00"),
            status="PAID",
        )
        future_unpaid = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=following_month,
            due_date=following_month.replace(day=5),
            base_rent=Decimal("10125.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10475.00"),
            status="UNPAID",
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_billing"), {"q": "billing-tenant"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["paid_count"], 2)
        self.assertEqual(response.context["upcoming_count"], 1)
        self.assertEqual(response.context["active_count"], 2)
        bill_ids = [bill.id for bill in response.context["page_obj"]]
        self.assertIn(self.current_bill.id, bill_ids)
        self.assertIn(future_paid.id, bill_ids)
        self.assertNotIn(future_unpaid.id, bill_ids)


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

    def test_admin_notifications_exclude_tenant_specific_notifications(self):
        Notification.create_tenant_notification(
            title="Welcome to Your New Unit 102!",
            message="Tenant-only welcome details.",
            notification_type="SYSTEM",
            tenant_user=self.tenant,
        )
        Notification.objects.create(
            title="Admin Lease Audit",
            message="Admin lease audit.",
            notification_type="LEASE",
            recipient_type="ADMIN",
            related_tenant=self.tenant,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_notifications"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Admin Lease Audit")
        self.assertNotContains(response, "Welcome to Your New Unit 102!")


class TenantPortalBoundaryTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="boundary-admin@example.com",
            username="boundaryadmin",
            password="password123",
            role=User.Role.ADMIN,
        )
        self.tenant = User.objects.create_user(
            email="boundary-tenant@example.com",
            username="boundarytenant",
            password="password123",
            role=User.Role.TENANT,
        )

    def test_admin_is_redirected_away_from_tenant_dashboard(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("tenant_dashboard"))

        self.assertRedirects(response, reverse("admin_dashboard"))
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any("tenant portal" in str(message).lower() for message in messages))

    def test_admin_is_redirected_away_from_tenant_maintenance(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("maintenance_list"))

        self.assertRedirects(response, reverse("admin_dashboard"))
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any("tenant portal" in str(message).lower() for message in messages))

    def test_admin_is_redirected_away_from_tenant_payment_checkout(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("paymongo_checkout"))

        self.assertRedirects(response, reverse("admin_dashboard"))
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any("tenant portal" in str(message).lower() for message in messages))

    def test_tenant_is_redirected_away_from_admin_dashboard(self):
        self.client.force_login(self.tenant)

        response = self.client.get(reverse("admin_dashboard"))

        self.assertRedirects(response, reverse("tenant_dashboard"))
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any("admin portal" in str(message).lower() for message in messages))


class TenantNotificationBehaviorTests(TestCase):
    def setUp(self):
        self.tenant = User.objects.create_user(
            email="tenant-notify@example.com",
            username="tenantnotify",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=self.tenant,
            first_name="Tenant",
            last_name="Notify",
            password_change_required=False,
            created_by=None,
        )

    def test_tenant_can_delete_read_notification(self):
        notification = Notification.objects.create(
            title="Read",
            message="Done",
            notification_type="SYSTEM",
            recipient_type="TENANT",
            user=self.tenant,
            is_read=True,
        )
        self.client.force_login(self.tenant)

        response = self.client.post(reverse("delete_notification", args=[notification.id]))

        self.assertRedirects(response, reverse("tenant_notifications"))
        self.assertFalse(Notification.objects.filter(pk=notification.pk).exists())

    def test_tenant_cannot_delete_unread_notification(self):
        notification = Notification.objects.create(
            title="Unread",
            message="Pending",
            notification_type="SYSTEM",
            recipient_type="TENANT",
            user=self.tenant,
            is_read=False,
        )
        self.client.force_login(self.tenant)

        response = self.client.post(reverse("delete_notification", args=[notification.id]))

        self.assertRedirects(response, reverse("tenant_notifications"))
        self.assertTrue(Notification.objects.filter(pk=notification.pk).exists())
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any("already marked as read" in str(message).lower() for message in messages))

    def test_tenant_can_delete_all_read_notifications_without_touching_unread(self):
        read_notification = Notification.objects.create(
            title="Read",
            message="Done",
            notification_type="SYSTEM",
            recipient_type="TENANT",
            user=self.tenant,
            is_read=True,
        )
        unread_notification = Notification.objects.create(
            title="Unread",
            message="Pending",
            notification_type="SYSTEM",
            recipient_type="TENANT",
            user=self.tenant,
            is_read=False,
        )
        self.client.force_login(self.tenant)

        response = self.client.post(reverse("delete_all_read_notifications"))

        self.assertRedirects(response, reverse("tenant_notifications"))
        self.assertFalse(Notification.objects.filter(pk=read_notification.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=unread_notification.pk).exists())


class AdminMaintenanceDisplayTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="maintenance-admin@example.com",
            username="maintenanceadmin",
            password="password123",
            role=User.Role.ADMIN,
        )
        self.tenant = User.objects.create_user(
            email="sophia.sinco@example.com",
            username="sophiasinco",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=self.tenant,
            first_name="Sophia",
            last_name="Sinco",
            password_change_required=False,
            created_by=None,
        )
        self.unit = Unit.objects.create(
            number="107",
            status="OCCUPIED",
            monthly_rent=Decimal("10000.00"),
        )
        self.lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=timezone.localdate().replace(day=1),
            status=Lease.STATUS_ACTIVE,
            is_active=False,
        )

    def test_admin_maintenance_page_shows_tenant_name_without_lease(self):
        MaintenanceRequest.objects.create(
            tenant=self.tenant,
            lease=None,
            category="ELECTRICAL",
            title="Light issue",
            description="Ceiling light exploded.",
            priority="MEDIUM",
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_maintenance"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sophia Sinco")
        self.assertContains(response, "Unit #107")

    def test_admin_maintenance_page_falls_back_to_latest_room_when_status_is_stale(self):
        self.lease.status = Lease.STATUS_PENDING_PAYMENT
        self.lease.save(update_fields=["status"])
        MaintenanceRequest.objects.create(
            tenant=self.tenant,
            lease=None,
            category="PLUMBING",
            title="Water leak",
            description="Water leak in cr",
            priority="MEDIUM",
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_maintenance"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sophia Sinco")
        self.assertContains(response, "Unit #107")


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

        response = self.client.get(reverse("admin_forecasting_data"))

        self.assertEqual(response.status_code, 200)
        target_label = target_month.strftime("%b %Y")
        payload = response.json()
        month_index = payload["hist_labels"].index(target_label)
        self.assertEqual(payload["hist_revenue"][month_index], 114000.0)


class AdminTenantPaymentHistoryTests(TestCase):
    def test_tenant_detail_payment_history_excludes_future_unpaid_bills_but_keeps_paid_future(self):
        admin = User.objects.create_superuser(
            email="history-admin@example.com",
            username="historyadmin",
            password="password123",
        )
        tenant_user = User.objects.create_user(
            email="history-tenant@example.com",
            username="historytenant",
            password="password123",
            role=User.Role.TENANT,
        )
        tenant = TenantProfile.objects.create(
            user=tenant_user,
            first_name="History",
            last_name="Tenant",
            password_change_required=False,
            created_by=None,
        )
        unit = Unit.objects.create(number="H-101", status="OCCUPIED")
        lease = Lease.objects.create(
            tenant=tenant_user,
            unit=unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 1, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=timezone.localdate().replace(day=1),
            due_date=timezone.localdate().replace(day=5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10000.00"),
            status="PAID",
        )
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 11, 1),
            due_date=date(2026, 11, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10000.00"),
            status="UNPAID",
        )
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 7, 1),
            due_date=date(2026, 7, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10000.00"),
            status="PAID",
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("admin_tenant_detail", args=[tenant.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, timezone.localdate().replace(day=1).strftime("%b %Y"))
        self.assertContains(response, "Jul 2026")
        self.assertNotContains(response, "Nov 2026")


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

    def test_admin_tenant_detail_shows_contract_start_and_end_dates(self):
        unit = Unit.objects.create(number="605", monthly_rent=Decimal("14060.00"))
        Lease.objects.create(
            tenant=self.tenant_john,
            unit=unit,
            monthly_rent=Decimal("14060.00"),
            due_day=16,
            start_date=date(2026, 6, 16),
            end_date=date(2027, 6, 16),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_tenant_detail", args=[self.tenant_john.tenantprofile.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Contract Dates")
        self.assertContains(response, "In: Jun 16, 2026")
        self.assertContains(response, "Jun 16, 2027")

    def test_admin_tenant_detail_contract_ledger_labels_partial_and_upcoming(self):
        today = date.today()
        current_month = today.replace(day=1)
        next_month = (
            date(current_month.year + 1, 1, 1)
            if current_month.month == 12
            else date(current_month.year, current_month.month + 1, 1)
        )
        unit = Unit.objects.create(number="606", monthly_rent=Decimal("10000.00"))
        lease = Lease.objects.create(
            tenant=self.tenant_john,
            unit=unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=current_month,
            end_date=next_month,
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=current_month,
            due_date=current_month.replace(day=5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("500.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10500.00"),
            rent_paid=Decimal("10000.00"),
            status="PARTIALLY_PAID",
        )
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=next_month,
            due_date=next_month.replace(day=5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10000.00"),
            status="UNPAID",
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_tenant_detail", args=[self.tenant_john.tenantprofile.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Contract Ledger")
        self.assertContains(response, "PARTIAL")
        self.assertContains(response, "UPCOMING")

    def test_admin_tenant_detail_orders_ledger_from_start_and_shows_payment_covered_month(self):
        unit = Unit.objects.create(number="607", monthly_rent=Decimal("10000.00"))
        lease = Lease.objects.create(
            tenant=self.tenant_john,
            unit=unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 8, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        june_bill = MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 6, 1),
            due_date=date(2026, 6, 5),
            base_rent=Decimal("10000.00"),
            total_due=Decimal("10000.00"),
            status="PAID",
        )
        august_bill = MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 8, 1),
            due_date=date(2026, 8, 5),
            base_rent=Decimal("10000.00"),
            total_due=Decimal("10000.00"),
            status="PAID",
        )
        ManualPayment.objects.create(
            user=self.tenant_john,
            bill_ids=f"{june_bill.id},{august_bill.id}",
            payment_type="full",
            payment_method="PAYMONGO",
            amount=Decimal("20000.00"),
            status="APPROVED",
            reference_code="REF-COVERED-MONTHS",
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_tenant_detail", args=[self.tenant_john.tenantprofile.id]))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertLess(content.index("Jun 2026"), content.index("Aug 2026"))
        self.assertContains(response, "Jun 2026 - Aug 2026")

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

    def test_new_lease_form_excludes_tenants_with_active_or_pending_leases(self):
        available_tenant = User.objects.create_user(
            email="available.tenant@example.com",
            username="availabletenant",
            password="password123",
            role=User.Role.TENANT,
        )
        active_tenant = User.objects.create_user(
            email="active.tenant@example.com",
            username="activetenant",
            password="password123",
            role=User.Role.TENANT,
        )
        pending_tenant = User.objects.create_user(
            email="pending.tenant@example.com",
            username="pendingtenant",
            password="password123",
            role=User.Role.TENANT,
        )
        for tenant, first in [
            (available_tenant, "Available"),
            (active_tenant, "Active"),
            (pending_tenant, "Pending"),
        ]:
            TenantProfile.objects.create(user=tenant, first_name=first, last_name="Tenant")

        active_unit = Unit.objects.create(number="707", monthly_rent=Decimal("10000.00"), status="OCCUPIED")
        pending_unit = Unit.objects.create(number="708", monthly_rent=Decimal("10000.00"), status="AVAILABLE")
        Lease.objects.create(
            tenant=active_tenant,
            unit=active_unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 6, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        Lease.objects.create(
            tenant=pending_tenant,
            unit=pending_unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 6, 1),
            status=Lease.STATUS_PENDING_PAYMENT,
            is_active=False,
        )

        form = LeaseForm()
        tenant_ids = set(form.fields["tenant"].queryset.values_list("id", flat=True))

        self.assertIn(available_tenant.id, tenant_ids)
        self.assertNotIn(active_tenant.id, tenant_ids)
        self.assertNotIn(pending_tenant.id, tenant_ids)


class TenantCreationEmailTests(TestCase):
    def test_tenant_form_sends_credentials_immediately_after_creation(self):
        admin = User.objects.create_superuser(
            email="admin-create-tenant@example.com",
            username="admincreatetenant",
            password="password123",
        )
        form = TenantProfileForm(
            data={
                "email": "instant.tenant@example.com",
                "first_name": "Instant",
                "last_name": "Tenant",
                "contact_no": "09170000000",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        with patch("accounts.admin_portal_forms.send_tenant_credentials_email", return_value=True) as send_email:
            profile = form.save(uploaded_by=admin)

        send_email.assert_called_once_with(
            tenant_email="instant.tenant@example.com",
            tenant_name="Instant Tenant",
            password="ITenant",
        )
        self.assertTrue(profile.credentials_email_sent)
        self.assertTrue(profile.user.check_password("ITenant"))


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
