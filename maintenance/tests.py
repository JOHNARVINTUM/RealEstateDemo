from datetime import date
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from accounts.ml.maintenance_nlp import classify_issue_category
from maintenance.models import MaintenanceRequest
from rentals.models import Lease, Unit


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
        self.user = User.objects.create_user(
            email="tenant@example.com",
            username="tenantuser",
            password="password123",
            role=User.Role.TENANT,
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
            },
        )

        self.assertRedirects(response, reverse("maintenance_list"))

        request_obj = MaintenanceRequest.objects.get()
        self.assertEqual(request_obj.category, "PLUMBING")
        self.assertEqual(request_obj.priority, "HIGH")
        self.assertEqual(request_obj.nlp_priority, "HIGH")
        self.assertEqual(request_obj.nlp_priority_confidence, 0.91)
