from datetime import date, datetime
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.ml.maintenance_nlp import classify_issue_category
from maintenance.forms import AdminMaintenanceUpdateForm
from maintenance.models import MaintenanceRequest
from rentals.models import Lease, TenantProfile, Unit


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
