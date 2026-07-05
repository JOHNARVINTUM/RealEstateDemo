from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.ml.maintenance_nlp import classify_issue_category
from maintenance.forms import AdminMaintenanceUpdateForm
from maintenance.models import MaintenanceCharge, MaintenanceRequest
from rentals.models import Lease, TenantProfile, Unit
from billing.models import BillLineItem, MonthlyBill


class MaintenanceNLPTests(TestCase):
    def test_classify_issue_category_detects_plumbing(self):
        result = classify_issue_category("There is water leaking under the sink and the drain is clogged.")

        self.assertEqual(result["category"], "PLUMBING")
        self.assertGreater(result["confidence"], 0)
        self.assertIn("water", result["matched_keywords"])

    def test_classify_issue_category_falls_back_to_other(self):
        result = classify_issue_category("Please check the room because something feels unusual.")

        self.assertEqual(result["category"], "OTHER")
        self.assertEqual(result["confidence"], 0.0)


class MaintenanceSubmissionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@example.com",
            username="adminuser",
            password="password123",
            role=User.Role.ADMIN,
        )
        self.staff = User.objects.create_user(
            email="staff@example.com",
            username="staffuser",
            password="password123",
            role=User.Role.STAFF,
        )
        self.user = User.objects.create_user(
            email="tenant@example.com",
            username="tenantuser",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=self.user,
            first_name="Test",
            last_name="Tenant",
            password_change_required=False,
            created_by=self.admin,
        )
        TenantProfile.objects.create(
            user=self.staff,
            first_name="Assigned",
            last_name="Staff",
            password_change_required=False,
            created_by=self.admin,
        )
        self.unit = Unit.objects.create(
            number="101",
            unit_type="STUDIO",
            floor_level=1,
            size_sqm=24,
            monthly_rent=10000,
            status="OCCUPIED",
            is_active=True,
        )
        self.lease = Lease.objects.create(
            tenant=self.user,
            unit=self.unit,
            monthly_rent=10000,
            due_day=5,
            start_date=date.today(),
            security_deposit=20000,
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        self.client.force_login(self.user)

    @patch("accounts.ml.maintenance_nlp.predict_priority")
    def test_report_issue_auto_populates_category_and_priority(self, mock_predict_priority):
        mock_predict_priority.return_value = {
            "priority": "HIGH",
            "confidence": 0.91,
            "available": True,
        }

        response = self.client.post(
            reverse("report_issue"),
            {
                "title": "Sink issue",
                "description": "There is water leaking under the sink and the drain is clogged.",
                "requested_schedule_at": "2026-06-15T13:00",
            },
        )

        self.assertRedirects(response, reverse("maintenance_list"))

        request_obj = MaintenanceRequest.objects.get()
        self.assertEqual(request_obj.category, "PLUMBING")
        self.assertEqual(request_obj.priority, "HIGH")
        self.assertEqual(request_obj.nlp_priority, "HIGH")
        self.assertEqual(request_obj.nlp_priority_confidence, 0.91)
        self.assertEqual(timezone.localtime(request_obj.requested_schedule_at).replace(tzinfo=None), datetime(2026, 6, 15, 13, 0))
        self.assertEqual(request_obj.review_status, "PENDING")
        self.assertIsNone(request_obj.assigned_staff)

    def test_admin_approval_uses_tenant_requested_schedule_when_blank(self):
        request_obj = MaintenanceRequest.objects.create(
            tenant=self.user,
            lease=self.lease,
            category="PLUMBING",
            title="Sink issue",
            description="There is water leaking under the sink.",
            requested_schedule_at=timezone.make_aware(datetime(2026, 6, 15, 13, 0)),
        )

        form = AdminMaintenanceUpdateForm(
            {
                "category": "PLUMBING",
                "status": "OPEN",
                "priority": "MEDIUM",
                "review_status": "ACCEPTED",
                "assigned_staff": self.staff.id,
                "fixed_by": "",
                "schedule_decision": "APPROVED",
                "admin_scheduled_at": "",
                "schedule_admin_note": "Approved by admin.",
            },
            instance=request_obj,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["admin_scheduled_at"], request_obj.requested_schedule_at)

    def test_report_issue_uses_date_valid_active_lease_even_if_is_active_flag_is_false(self):
        self.lease.is_active = False
        self.lease.save(update_fields=["is_active"])

        response = self.client.post(
            reverse("report_issue"),
            {
                "title": "Outlet issue",
                "description": "The outlet sparked near the desk.",
                "requested_schedule_at": "2026-06-15T13:00",
            },
        )

        self.assertRedirects(response, reverse("maintenance_list"))
        request_obj = MaintenanceRequest.objects.latest("id")
        self.assertEqual(request_obj.lease_id, self.lease.id)


class MaintenanceWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="workflow-admin@example.com",
            username="workflowadmin",
            password="password123",
            role=User.Role.ADMIN,
        )
        self.staff = User.objects.create_user(
            email="workflow-staff@example.com",
            username="workflowstaff",
            password="password123",
            role=User.Role.STAFF,
        )
        self.other_staff = User.objects.create_user(
            email="workflow-staff-2@example.com",
            username="workflowstaff2",
            password="password123",
            role=User.Role.STAFF,
        )
        self.tenant = User.objects.create_user(
            email="workflow-tenant@example.com",
            username="workflowtenant",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(user=self.staff, first_name="Assigned", last_name="Staff", created_by=self.admin)
        TenantProfile.objects.create(user=self.other_staff, first_name="Other", last_name="Staff", created_by=self.admin)
        TenantProfile.objects.create(user=self.tenant, first_name="Tenant", last_name="User", password_change_required=False, created_by=self.admin)
        self.unit = Unit.objects.create(number="M-101", monthly_rent=10000, status="OCCUPIED", is_active=True)
        self.lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=10000,
            due_day=5,
            start_date=date(2026, 6, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        self.request_obj = MaintenanceRequest.objects.create(
            tenant=self.tenant,
            lease=self.lease,
            category="PLUMBING",
            title="Pipe leak",
            description="Water is leaking under the kitchen sink.",
            requested_schedule_at=timezone.make_aware(datetime(2026, 6, 20, 9, 0)),
            status="OPEN",
            review_status="PENDING",
        )

    def test_admin_can_accept_and_assign_staff(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin_update_maintenance", args=[self.request_obj.id]),
            {
                "category": "PLUMBING",
                "priority": "HIGH",
                "review_status": "ACCEPTED",
                "assigned_staff": self.staff.id,
                "status": "OPEN",
                "fixed_by": "",
                "schedule_decision": "APPROVED",
                "admin_scheduled_at": "",
                "schedule_admin_note": "Please start tomorrow morning.",
            },
        )

        self.assertRedirects(response, reverse("admin_maintenance"))
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.review_status, "ACCEPTED")
        self.assertEqual(self.request_obj.assigned_staff, self.staff)
        self.assertEqual(self.request_obj.status, "OPEN")
        self.assertEqual(self.request_obj.admin_scheduled_at, self.request_obj.requested_schedule_at)

    def test_admin_can_reject_request_and_clear_assignment(self):
        self.request_obj.review_status = "ACCEPTED"
        self.request_obj.assigned_staff = self.staff
        self.request_obj.status = "IN_PROGRESS"
        self.request_obj.save(update_fields=["review_status", "assigned_staff", "status"])
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin_update_maintenance", args=[self.request_obj.id]),
            {
                "category": "PLUMBING",
                "priority": "MEDIUM",
                "review_status": "REJECTED",
                "assigned_staff": "",
                "status": "OPEN",
                "fixed_by": "",
                "schedule_decision": "DECLINED",
                "admin_scheduled_at": "",
                "schedule_admin_note": "Duplicate request.",
            },
        )

        self.assertRedirects(response, reverse("admin_maintenance"))
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.review_status, "REJECTED")
        self.assertIsNone(self.request_obj.assigned_staff)
        self.assertEqual(self.request_obj.status, "CLOSED")

    def test_staff_only_sees_assigned_accepted_requests(self):
        self.request_obj.review_status = "ACCEPTED"
        self.request_obj.assigned_staff = self.staff
        self.request_obj.save(update_fields=["review_status", "assigned_staff"])
        other_request = MaintenanceRequest.objects.create(
            tenant=self.tenant,
            lease=self.lease,
            category="ELECTRICAL",
            title="Outlet issue",
            description="Outlet is not working.",
            review_status="ACCEPTED",
            assigned_staff=self.other_staff,
            status="OPEN",
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("admin_maintenance"))

        self.assertEqual(response.status_code, 200)
        visible_ids = [row.id for row in response.context["page_obj"].object_list]
        self.assertIn(self.request_obj.id, visible_ids)
        self.assertNotIn(other_request.id, visible_ids)

    def test_staff_cannot_open_unassigned_request(self):
        self.request_obj.review_status = "ACCEPTED"
        self.request_obj.assigned_staff = self.other_staff
        self.request_obj.save(update_fields=["review_status", "assigned_staff"])
        self.client.force_login(self.staff)

        response = self.client.get(reverse("admin_update_maintenance", args=[self.request_obj.id]))

        self.assertEqual(response.status_code, 404)

    def test_staff_can_update_assigned_request_status(self):
        self.request_obj.review_status = "ACCEPTED"
        self.request_obj.assigned_staff = self.staff
        self.request_obj.status = "OPEN"
        self.request_obj.save(update_fields=["review_status", "assigned_staff", "status"])
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("admin_update_maintenance", args=[self.request_obj.id]),
            {
                "status": "RESOLVED",
                "fixed_by": "Assigned Staff",
            },
        )

        self.assertRedirects(response, reverse("admin_maintenance"))
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.review_status, "ACCEPTED")
        self.assertEqual(self.request_obj.assigned_staff, self.staff)
        self.assertEqual(self.request_obj.status, "RESOLVED")
        self.assertEqual(self.request_obj.fixed_by, "Assigned Staff")
        self.assertIsNotNone(self.request_obj.resolved_at)

    def test_tenant_request_history_shows_review_and_assignment(self):
        self.request_obj.review_status = "ACCEPTED"
        self.request_obj.assigned_staff = self.staff
        self.request_obj.status = "IN_PROGRESS"
        self.request_obj.save(update_fields=["review_status", "assigned_staff", "status"])
        self.client.force_login(self.tenant)

        response = self.client.get(reverse("maintenance_list"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pipe leak")
        self.assertContains(response, "In Progress")


class MaintenanceChargeSuggestionWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="charge-flow-admin@example.com",
            username="chargeflowadmin",
            password="password123",
            role=User.Role.ADMIN,
        )
        self.staff = User.objects.create_user(
            email="charge-flow-staff@example.com",
            username="chargeflowstaff",
            password="password123",
            role=User.Role.STAFF,
        )
        self.other_staff = User.objects.create_user(
            email="charge-flow-staff-2@example.com",
            username="chargeflowstaff2",
            password="password123",
            role=User.Role.STAFF,
        )
        self.tenant = User.objects.create_user(
            email="charge-flow-tenant@example.com",
            username="chargeflowtenant",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(user=self.staff, first_name="Charge", last_name="Worker", created_by=self.admin)
        TenantProfile.objects.create(user=self.other_staff, first_name="Other", last_name="Worker", created_by=self.admin)
        TenantProfile.objects.create(user=self.tenant, first_name="Charge", last_name="Tenant", created_by=self.admin)
        self.unit = Unit.objects.create(number="MC-201", monthly_rent=12000, status="OCCUPIED", is_active=True)
        self.lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=12000,
            due_day=5,
            start_date=date(2026, 6, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        self.request_obj = MaintenanceRequest.objects.create(
            tenant=self.tenant,
            lease=self.lease,
            category="PLUMBING",
            title="Pipe repair",
            description="Pipe under the sink needs repair.",
            requested_schedule_at=timezone.make_aware(datetime(2026, 6, 21, 10, 0)),
            status="OPEN",
            review_status="ACCEPTED",
            assigned_staff=self.staff,
        )

    def _charge_url(self):
        return reverse("admin_update_maintenance", args=[self.request_obj.id])

    def test_assigned_staff_can_create_charge_suggestion(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            self._charge_url(),
            {
                "form_action": "charge_suggestion",
                "diagnosis": "Pipe joint is damaged.",
                "repair_notes": "Replace the connector and retighten fittings.",
                "labor_cost": "650.00",
                "material_cost": "350.00",
            },
        )

        self.assertRedirects(response, self._charge_url())
        charge = MaintenanceCharge.objects.get(maintenance_request=self.request_obj)
        self.assertEqual(charge.suggested_by, self.staff)
        self.assertEqual(charge.diagnosis, "Pipe joint is damaged.")
        self.assertEqual(charge.repair_notes, "Replace the connector and retighten fittings.")
        self.assertEqual(charge.labor_cost, Decimal("650.00"))
        self.assertEqual(charge.material_cost, Decimal("350.00"))
        self.assertEqual(charge.suggested_total, Decimal("1000.00"))
        self.assertEqual(charge.status, MaintenanceCharge.STATUS_PENDING_REVIEW)

    def test_assigned_staff_can_update_pending_review_suggestion(self):
        charge = MaintenanceCharge.objects.create(
            maintenance_request=self.request_obj,
            suggested_by=self.staff,
            diagnosis="Initial diagnosis",
            repair_notes="Initial notes",
            labor_cost=Decimal("200.00"),
            material_cost=Decimal("50.00"),
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            self._charge_url(),
            {
                "form_action": "charge_suggestion",
                "diagnosis": "Updated diagnosis",
                "repair_notes": "Updated repair notes",
                "labor_cost": "500.00",
                "material_cost": "125.00",
            },
        )

        self.assertRedirects(response, self._charge_url())
        charge.refresh_from_db()
        self.assertEqual(charge.diagnosis, "Updated diagnosis")
        self.assertEqual(charge.repair_notes, "Updated repair notes")
        self.assertEqual(charge.suggested_total, Decimal("625.00"))

    def test_unassigned_staff_cannot_create_or_update_charge_suggestion(self):
        self.request_obj.assigned_staff = self.other_staff
        self.request_obj.save(update_fields=["assigned_staff"])
        self.client.force_login(self.staff)

        response = self.client.post(
            self._charge_url(),
            {
                "form_action": "charge_suggestion",
                "diagnosis": "Should fail",
                "repair_notes": "Should fail",
                "labor_cost": "100.00",
                "material_cost": "50.00",
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(MaintenanceCharge.objects.filter(maintenance_request=self.request_obj).exists())

    def test_staff_cannot_edit_charge_after_admin_decision(self):
        charge = MaintenanceCharge.objects.create(
            maintenance_request=self.request_obj,
            suggested_by=self.staff,
            diagnosis="Locked diagnosis",
            repair_notes="Locked notes",
            labor_cost=Decimal("400.00"),
            material_cost=Decimal("100.00"),
            admin_approved_total=Decimal("550.00"),
            status=MaintenanceCharge.STATUS_APPROVED,
            approved_by=self.admin,
            approved_at=timezone.now(),
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            self._charge_url(),
            {
                "form_action": "charge_suggestion",
                "diagnosis": "Changed diagnosis",
                "repair_notes": "Changed notes",
                "labor_cost": "999.00",
                "material_cost": "1.00",
            },
        )

        self.assertRedirects(response, self._charge_url())
        charge.refresh_from_db()
        self.assertEqual(charge.diagnosis, "Locked diagnosis")
        self.assertEqual(charge.repair_notes, "Locked notes")
        self.assertEqual(charge.suggested_total, Decimal("500.00"))
        self.assertEqual(charge.status, MaintenanceCharge.STATUS_APPROVED)

    def test_staff_cannot_set_admin_fields_or_bill_link(self):
        bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 6, 1),
            due_date=date(2026, 6, 5),
            base_rent=Decimal("12000.00"),
            total_due=Decimal("12000.00"),
            status="UNPAID",
        )
        line_item = BillLineItem.objects.create(
            monthly_bill=bill,
            line_type=BillLineItem.LINE_TYPE_MAINTENANCE,
            amount=Decimal("900.00"),
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            self._charge_url(),
            {
                "form_action": "charge_suggestion",
                "diagnosis": "Pipe replacement",
                "repair_notes": "Materials and labor estimated.",
                "labor_cost": "700.00",
                "material_cost": "200.00",
                "admin_approved_total": "9999.99",
                "status": MaintenanceCharge.STATUS_ADDED_TO_BILL,
                "approved_by": str(self.admin.id),
                "approved_at": timezone.now().isoformat(),
                "bill_line_item": str(line_item.id),
            },
        )

        self.assertRedirects(response, self._charge_url())
        charge = MaintenanceCharge.objects.get(maintenance_request=self.request_obj)
        self.assertIsNone(charge.admin_approved_total)
        self.assertIsNone(charge.approved_by)
        self.assertIsNone(charge.approved_at)
        self.assertIsNone(charge.bill_line_item)
        self.assertEqual(charge.status, MaintenanceCharge.STATUS_PENDING_REVIEW)

    def test_non_accepted_request_cannot_receive_charge_suggestion(self):
        for review_status in ("PENDING", "REJECTED"):
            with self.subTest(review_status=review_status):
                MaintenanceCharge.objects.filter(maintenance_request=self.request_obj).delete()
                self.request_obj.review_status = review_status
                self.request_obj.save(update_fields=["review_status"])
                self.client.force_login(self.staff)

                response = self.client.post(
                    self._charge_url(),
                    {
                        "form_action": "charge_suggestion",
                        "diagnosis": "Should not save",
                        "repair_notes": "Should not save",
                        "labor_cost": "100.00",
                        "material_cost": "25.00",
                    },
                )

                self.assertEqual(response.status_code, 404)
                self.assertFalse(MaintenanceCharge.objects.filter(maintenance_request=self.request_obj).exists())


class MaintenanceAdminArchiveTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            email="admin@example.com",
            username="adminuser",
            password="password123",
            role=User.Role.ADMIN,
            is_staff=True,
        )
        self.tenant_user = User.objects.create_user(
            email="tenant-archive@example.com",
            username="tenantarchive",
            password="password123",
            role=User.Role.TENANT,
        )
        self.client.force_login(self.admin_user)

    def test_admin_maintenance_archives_orphaned_requests(self):
        request_obj = MaintenanceRequest.objects.create(
            tenant=self.tenant_user,
            lease=None,
            category="OTHER",
            title="Old request",
            description="Unit was deleted after this request was created.",
            status="OPEN",
        )

        response = self.client.get(reverse("admin_maintenance"))

        self.assertEqual(response.status_code, 200)
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, "CLOSED")
        self.assertEqual(request_obj.review_status, "REJECTED")
        self.assertIsNotNone(request_obj.resolved_at)
        self.assertIn("linked lease or unit is no longer available", request_obj.schedule_admin_note.lower())
        self.assertNotContains(response, "Old request")

    def test_admin_maintenance_can_filter_archived_requests(self):
        request_obj = MaintenanceRequest.objects.create(
            tenant=self.tenant_user,
            lease=None,
            category="OTHER",
            title="Archived request",
            description="Archived because the unit is no longer linked.",
            status="OPEN",
        )

        response = self.client.get(reverse("admin_maintenance"), {"status": "CLOSED"})

        self.assertEqual(response.status_code, 200)
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, "CLOSED")
        self.assertContains(response, "Archived because the unit is no longer linked.")
        self.assertContains(response, "Rejected")


class MaintenanceChargeAdminReviewWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="charge-review-admin@example.com",
            username="chargereviewadmin",
            password="password123",
            role=User.Role.ADMIN,
        )
        self.staff = User.objects.create_user(
            email="charge-review-staff@example.com",
            username="chargereviewstaff",
            password="password123",
            role=User.Role.STAFF,
        )
        self.tenant = User.objects.create_user(
            email="charge-review-tenant@example.com",
            username="chargereviewtenant",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(user=self.staff, first_name="Review", last_name="Staff", created_by=self.admin)
        TenantProfile.objects.create(user=self.tenant, first_name="Review", last_name="Tenant", created_by=self.admin)
        self.unit = Unit.objects.create(number="MC-301", monthly_rent=13000, status="OCCUPIED", is_active=True)
        self.lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=13000,
            due_day=5,
            start_date=date(2026, 6, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        self.request_obj = MaintenanceRequest.objects.create(
            tenant=self.tenant,
            lease=self.lease,
            category="PLUMBING",
            title="Pipe repair",
            description="Pipe under the sink needs repair.",
            requested_schedule_at=timezone.make_aware(datetime(2026, 6, 21, 10, 0)),
            status="OPEN",
            review_status="ACCEPTED",
            assigned_staff=self.staff,
        )
        self.charge = MaintenanceCharge.objects.create(
            maintenance_request=self.request_obj,
            suggested_by=self.staff,
            diagnosis="Pipe joint is damaged.",
            repair_notes="Replace the connector and retighten fittings.",
            labor_cost=Decimal("650.00"),
            material_cost=Decimal("350.00"),
        )

    def _charge_url(self):
        return reverse("admin_update_maintenance", args=[self.request_obj.id])

    def test_admin_can_approve_charge_as_is(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            self._charge_url(),
            {
                "form_action": "charge_review",
                "charge_review_action": "approve_as_is",
                "admin_approved_total": "",
            },
        )

        self.assertRedirects(response, self._charge_url())
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, MaintenanceCharge.STATUS_READY_FOR_BILLING)
        self.assertEqual(self.charge.admin_approved_total, Decimal("1000.00"))
        self.assertEqual(self.charge.approved_by, self.admin)
        self.assertIsNotNone(self.charge.approved_at)
        self.assertIsNone(self.charge.bill_line_item)

    def test_admin_can_approve_charge_with_adjusted_amount(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            self._charge_url(),
            {
                "form_action": "charge_review",
                "charge_review_action": "approve_adjusted",
                "admin_approved_total": "875.50",
            },
        )

        self.assertRedirects(response, self._charge_url())
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, MaintenanceCharge.STATUS_READY_FOR_BILLING)
        self.assertEqual(self.charge.admin_approved_total, Decimal("875.50"))
        self.assertEqual(self.charge.approved_by, self.admin)
        self.assertIsNotNone(self.charge.approved_at)
        self.assertIsNone(self.charge.bill_line_item)

    def test_admin_can_mark_no_charge(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            self._charge_url(),
            {
                "form_action": "charge_review",
                "charge_review_action": "no_charge",
                "admin_approved_total": "0.00",
            },
        )

        self.assertRedirects(response, self._charge_url())
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, MaintenanceCharge.STATUS_NO_CHARGE)
        self.assertIsNone(self.charge.admin_approved_total)
        self.assertEqual(self.charge.approved_by, self.admin)
        self.assertIsNotNone(self.charge.approved_at)
        self.assertIsNone(self.charge.bill_line_item)

    def test_admin_cannot_review_charge_for_non_accepted_request(self):
        self.request_obj.review_status = "PENDING"
        self.request_obj.save(update_fields=["review_status"])
        self.client.force_login(self.admin)

        response = self.client.post(
            self._charge_url(),
            {
                "form_action": "charge_review",
                "charge_review_action": "approve_as_is",
                "admin_approved_total": "",
            },
        )

        self.assertRedirects(response, self._charge_url())
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, MaintenanceCharge.STATUS_PENDING_REVIEW)
        self.assertIsNone(self.charge.admin_approved_total)
        self.assertIsNone(self.charge.approved_by)
        self.assertIsNone(self.charge.approved_at)

    def test_admin_cannot_review_missing_charge(self):
        self.charge.delete()
        self.client.force_login(self.admin)

        response = self.client.post(
            self._charge_url(),
            {
                "form_action": "charge_review",
                "charge_review_action": "approve_as_is",
                "admin_approved_total": "",
            },
        )

        self.assertRedirects(response, self._charge_url())
        self.assertFalse(MaintenanceCharge.objects.filter(maintenance_request=self.request_obj).exists())


class MaintenanceChargeModelTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="charge-admin@example.com",
            username="chargeadmin",
            password="password123",
            role=User.Role.ADMIN,
        )
        self.staff = User.objects.create_user(
            email="charge-staff@example.com",
            username="chargestaff",
            password="password123",
            role=User.Role.STAFF,
        )
        self.tenant = User.objects.create_user(
            email="charge-tenant@example.com",
            username="chargetenant",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(user=self.staff, first_name="Charge", last_name="Staff", created_by=self.admin)
        TenantProfile.objects.create(user=self.tenant, first_name="Charge", last_name="Tenant", created_by=self.admin)
        self.unit = Unit.objects.create(number="MC-101", monthly_rent=10000, status="OCCUPIED", is_active=True)
        self.lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=10000,
            due_day=5,
            start_date=date(2026, 6, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        self.request_obj = MaintenanceRequest.objects.create(
            tenant=self.tenant,
            lease=self.lease,
            category="PLUMBING",
            title="Broken pipe",
            description="Water leaking from the kitchen pipe.",
        )

    def test_maintenance_charge_can_be_created_for_request(self):
        charge = MaintenanceCharge.objects.create(
            maintenance_request=self.request_obj,
            suggested_by=self.staff,
            diagnosis="Pipe seal worn out.",
            repair_notes="Replaced seal and tightened fittings.",
            labor_cost=Decimal("500.00"),
            material_cost=Decimal("250.00"),
        )

        self.assertEqual(charge.maintenance_request, self.request_obj)
        self.assertEqual(charge.status, MaintenanceCharge.STATUS_PENDING_REVIEW)
        self.assertIsNone(charge.bill_line_item)
        self.assertIsNone(charge.admin_approved_total)

    def test_suggested_total_is_computed_from_labor_and_material_cost(self):
        charge = MaintenanceCharge.objects.create(
            maintenance_request=self.request_obj,
            suggested_by=self.staff,
            labor_cost=Decimal("1250.40"),
            material_cost=Decimal("349.60"),
            suggested_total=Decimal("1.00"),
        )

        self.assertEqual(charge.suggested_total, Decimal("1600.00"))

    def test_only_one_maintenance_charge_can_exist_per_request(self):
        MaintenanceCharge.objects.create(
            maintenance_request=self.request_obj,
            suggested_by=self.staff,
            labor_cost=Decimal("100.00"),
            material_cost=Decimal("50.00"),
        )

        with self.assertRaises(IntegrityError):
            MaintenanceCharge.objects.create(
                maintenance_request=self.request_obj,
                suggested_by=self.staff,
                labor_cost=Decimal("80.00"),
                material_cost=Decimal("20.00"),
            )

    def test_bill_line_item_accepts_maintenance_line_type(self):
        bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 6, 1),
            due_date=date(2026, 6, 5),
            base_rent=Decimal("10000.00"),
            total_due=Decimal("10000.00"),
            status="UNPAID",
        )

        line_item = BillLineItem.objects.create(
            monthly_bill=bill,
            line_type=BillLineItem.LINE_TYPE_MAINTENANCE,
            amount=Decimal("750.00"),
        )

        self.assertEqual(line_item.line_type, BillLineItem.LINE_TYPE_MAINTENANCE)
        self.assertEqual(line_item.status, BillLineItem.STATUS_UNPAID)
