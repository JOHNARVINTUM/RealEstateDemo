from datetime import date
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
import zoneinfo

from django.test import TestCase

from accounts.models import User
from billing.models import MonthlyBill
from payments.models import ManualPayment
from rentals.models import Lease, TenantProfile, Unit
from rentals.services import (
    LeaseSchedulingService,
    TenantRiskService,
    _assemble_tenant_password,
    _extract_tenant_initials,
    _normalize_tenant_name_parts,
    _pad_tenant_password,
    create_tenant_with_credentials,
    generate_tenant_password,
    repair_historical_move_in_payment,
)
from rentals.views import _dashboard_billing_context
from water.models import WaterBill


class TenantViewWorkflowTests(TestCase):
    def setUp(self):
        self.tenant = User.objects.create_user(
            email="tenant-view@example.com",
            username="tenantview",
            password="password123",
            role=User.Role.TENANT,
        )
        TenantProfile.objects.create(
            user=self.tenant,
            first_name="Tenant",
            last_name="View",
            password_change_required=False,
            created_by=None,
        )
        self.unit = Unit.objects.create(number="TV-101")
        self.client.force_login(self.tenant)

    def create_active_lease(self, **kwargs):
        defaults = {
            "tenant": self.tenant,
            "unit": self.unit,
            "monthly_rent": Decimal("10000.00"),
            "due_day": 5,
            "start_date": date(2026, 1, 1),
            "status": Lease.STATUS_ACTIVE,
            "is_active": True,
            "motorcycle_slots": 1,
            "car_slots": 0,
        }
        defaults.update(kwargs)
        return Lease.objects.create(**defaults)

    def test_dashboard_loads_without_lease(self):
        response = self.client.get("/tenant/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["lease"])
        self.assertIsNone(response.context["current_balance"])
        self.assertFalse(response.context["show_paid_hero"])

    def test_dashboard_shows_unpaid_rent_and_parking_balance(self):
        lease = self.create_active_lease()
        WaterBill.objects.create(
            unit=self.unit,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            prev_reading=Decimal("0.00"),
            curr_reading=Decimal("80.00"),
            rate_per_cu_m=Decimal("10.00"),
            status="POSTED",
        )
        bill = MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 1, 1),
            due_date=date(2026, 1, 5),
            base_rent=Decimal("10000.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10350.00"),
            status="UNPAID",
        )

        response = self.client.get("/tenant/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_balance"].id, bill.id)
        self.assertEqual(response.context["current_balance"].rent_balance, Decimal("10000.00"))
        self.assertEqual(response.context["current_balance"].parking_balance, Decimal("350.00"))

    def test_dashboard_surfaces_delayed_water_after_rent_and_parking_paid(self):
        lease = self.create_active_lease()
        WaterBill.objects.create(
            unit=self.unit,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            prev_reading=Decimal("0.00"),
            curr_reading=Decimal("80.00"),
            rate_per_cu_m=Decimal("10.00"),
            status="POSTED",
        )
        bill = MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 1, 1),
            due_date=date(2026, 1, 5),
            base_rent=Decimal("10000.00"),
            parking_fee=Decimal("350.00"),
            rent_paid=Decimal("10000.00"),
            parking_paid=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10660.50"),
            status="PARTIALLY_PAID",
        )

        response = self.client.get("/tenant/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_balance"].id, bill.id)
        self.assertEqual(response.context["current_balance"].rent_balance, Decimal("0.00"))
        self.assertEqual(response.context["current_balance"].parking_balance, Decimal("0.00"))
        self.assertEqual(response.context["current_balance"].water_balance, Decimal("800.00"))

    def test_dashboard_keeps_future_bill_as_preview_when_current_month_is_paid(self):
        lease = self.create_active_lease(start_date=date(2026, 5, 1), due_day=5)
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 5, 1),
            due_date=date(2026, 5, 5),
            base_rent=Decimal("10000.00"),
            parking_fee=Decimal("350.00"),
            rent_paid=Decimal("10000.00"),
            parking_paid=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10350.00"),
            status="PAID",
        )
        june_bill = MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 6, 1),
            due_date=date(2026, 6, 5),
            base_rent=Decimal("10000.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10350.00"),
            status="UNPAID",
        )

        context = _dashboard_billing_context(self.tenant, lease, date(2026, 5, 30))

        self.assertIsNone(context["current_balance"])
        self.assertTrue(context["show_paid_hero"])
        self.assertEqual(context["paid_hero_month"], date(2026, 5, 1))
        self.assertEqual(context["next_bill_preview"].id, june_bill.id)
        self.assertEqual(context["next_due_in_days"], 6)
        self.assertEqual(context["next_due_label"], "Due in 6 days")

    def test_payment_preview_rent_only_includes_parking(self):
        lease = self.create_active_lease()
        bill = MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 1, 1),
            due_date=date(2026, 1, 5),
            base_rent=Decimal("10000.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("11150.00"),
            status="UNPAID",
        )

        response = self.client.get("/tenant/pay/?payment_type=rent_only")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["payment_type"], "rent_only")
        self.assertEqual(response.context["total_amount"], 10660.5)
        self.assertEqual(response.context["total_rent"], 10000.0)
        self.assertEqual(response.context["total_parking"], 350.0)
        self.assertEqual(response.context["total_penalty"], 310.5)
        self.assertEqual(response.context["preview_rows"][0]["bill_id"], bill.id)

    def test_advance_payment_defaults_to_full_when_rent_and_water_are_due(self):
        lease = self.create_active_lease()
        bill = MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 1, 1),
            due_date=date(2026, 1, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("800.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("11150.00"),
            status="UNPAID",
            water_computed_from_system=True,
        )

        response = self.client.get("/tenant/pay/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["payment_type"], "full")
        self.assertEqual(response.context["total_amount"], 11460.5)
        self.assertEqual(response.context["preview_rows"][0]["bill_id"], bill.id)

    def test_advance_payment_defaults_to_rent_only_when_only_rent_is_due(self):
        lease = self.create_active_lease()
        bill = MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 1, 1),
            due_date=date(2026, 1, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("310.50"),
            total_due=Decimal("10660.50"),
            status="UNPAID",
        )

        response = self.client.get("/tenant/pay/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["payment_type"], "rent_only")
        self.assertEqual(response.context["total_amount"], 10660.5)
        self.assertEqual(response.context["total_penalty"], 310.5)
        self.assertEqual(response.context["preview_rows"][0]["bill_id"], bill.id)

    def test_advance_payment_ignores_full_and_stays_rent_only(self):
        lease = self.create_active_lease()
        bill = MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 1, 1),
            due_date=date(2026, 1, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10660.50"),
            status="UNPAID",
        )

        response = self.client.get("/tenant/pay/?payment_type=full")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["payment_type"], "rent_only")
        self.assertEqual(response.context["total_amount"], 10660.5)
        self.assertEqual(response.context["preview_rows"][0]["bill_id"], bill.id)

    def test_payment_preview_allows_full_when_rent_and_water_are_posted(self):
        lease = self.create_active_lease()
        WaterBill.objects.create(
            unit=self.unit,
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            prev_reading=Decimal("0.00"),
            curr_reading=Decimal("80.00"),
            rate_per_cu_m=Decimal("10.00"),
            status="POSTED",
        )
        bill = MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 6, 1),
            due_date=date(2026, 6, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("800.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("11150.00"),
            status="UNPAID",
            water_computed_from_system=True,
        )

        response = self.client.get("/tenant/pay/?payment_type=full")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["full_bill_available"])
        self.assertTrue(response.context["can_pay_full_bill"])
        self.assertEqual(response.context["payment_type"], "full")

    def test_payment_preview_locks_to_water_only_when_only_water_remains(self):
        lease = self.create_active_lease()
        WaterBill.objects.create(
            unit=self.unit,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            prev_reading=Decimal("0.00"),
            curr_reading=Decimal("80.00"),
            rate_per_cu_m=Decimal("10.00"),
            status="POSTED",
        )
        bill = MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 1, 1),
            due_date=date(2026, 1, 5),
            base_rent=Decimal("10000.00"),
            parking_fee=Decimal("350.00"),
            rent_paid=Decimal("10000.00"),
            parking_paid=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("11150.00"),
            status="PARTIALLY_PAID",
        )

        response = self.client.get("/tenant/pay/?payment_type=full")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["water_only_locked"])
        self.assertEqual(response.context["payment_type"], "water_only")
        self.assertEqual(response.context["total_amount"], 800.0)
        self.assertEqual(response.context["preview_rows"][0]["bill_id"], bill.id)

    def test_payment_post_redirect_includes_amount_bill_ids_and_payment_type(self):
        lease = self.create_active_lease()
        bill = MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 1, 1),
            due_date=date(2026, 1, 5),
            base_rent=Decimal("10000.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10660.50"),
            status="UNPAID",
        )

        response = self.client.post("/tenant/pay/?payment_type=rent_only")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/payments/gcash/manual/", response["Location"])
        self.assertIn("amount=10660.5", response["Location"])
        self.assertIn(f"bill_ids={bill.id}", response["Location"])
        self.assertIn("payment_type=rent_only", response["Location"])

    def test_tenant_billing_payment_history_uses_manual_payment_bill_ids(self):
        lease = self.create_active_lease()
        bill = MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 1, 1),
            due_date=date(2026, 1, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10000.00"),
            status="PAID",
        )
        ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-HISTORY",
            bill_ids=str(bill.id),
            payment_type="full",
            amount=Decimal("10000.00"),
            status="APPROVED",
        )

        response = self.client.get("/tenant/billing/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["transactions"]), 1)
        self.assertEqual(response.context["transactions"][0]["reference"], "REF-HISTORY")
        self.assertEqual(response.context["transactions"][0]["months_paid"], 1)

    def test_tenant_billing_monthly_status_rows_show_paid_and_unpaid_months(self):
        lease = self.create_active_lease()
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 1, 1),
            due_date=date(2026, 1, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10350.00"),
            status="PAID",
        )
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 2, 1),
            due_date=date(2026, 2, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10350.00"),
            rent_paid=Decimal("10000.00"),
            parking_paid=Decimal("350.00"),
            status="PARTIALLY_PAID",
        )
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 3, 1),
            due_date=date(2026, 3, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10350.00"),
            status="UNPAID",
        )

        response = self.client.get("/tenant/billing/")

        self.assertEqual(response.status_code, 200)
        status_by_month = {
            row["month_label"]: row["status_label"]
            for row in response.context["monthly_status_rows"]
        }
        self.assertEqual(status_by_month["January 2026"], "Paid")
        self.assertEqual(status_by_month["February 2026"], "Partially Paid")
        self.assertEqual(status_by_month["March 2026"], "Unpaid")

    def test_tenant_billing_selected_paid_contract_month_shows_paid_bill(self):
        lease = self.create_active_lease()
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 6, 1),
            due_date=date(2026, 6, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10350.00"),
            rent_paid=Decimal("10000.00"),
            parking_paid=Decimal("350.00"),
            status="PAID",
        )

        response = self.client.get("/tenant/billing/?billing_month=2026-06-01")

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["current_bill"])
        self.assertEqual(response.context["current_bill"].billing_month, date(2026, 6, 1))
        self.assertEqual(response.context["current_bill"].status, "PAID")
        self.assertEqual(response.context["current_bill"].total_due, Decimal("10350.00"))


class MoveInRepairWorkflowTests(TestCase):
    def setUp(self):
        self.tenant = User.objects.create_user(
            email="repair@example.com",
            username="repair",
            password="password123",
            role=User.Role.TENANT,
        )
        self.unit = Unit.objects.create(number="RP-101")

    def test_repair_historical_move_in_payment_activates_lease_and_marks_payment_approved(self):
        lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 1, 1),
            status=Lease.STATUS_PENDING_PAYMENT,
            is_active=False,
        )
        payment = ManualPayment.objects.create(
            user=self.tenant,
            payment_type="move_in",
            payment_method="CASH",
            amount=lease.total_move_in_cost,
            reference_code="MOVEIN-REPAIR",
            status="REJECTED",
            metadata={"lease_id": lease.id},
        )

        success, message = repair_historical_move_in_payment(payment)

        lease.refresh_from_db()
        payment.refresh_from_db()
        first_bill = MonthlyBill.objects.filter(lease=lease, billing_month=date(2026, 1, 1)).first()

        self.assertTrue(success)
        self.assertIn("repaired", message.lower())
        self.assertEqual(lease.status, Lease.STATUS_ACTIVE)
        self.assertTrue(lease.is_active)
        self.assertEqual(lease.unit.status, "OCCUPIED")
        self.assertEqual(payment.status, "APPROVED")
        self.assertIsNotNone(first_bill)
        self.assertEqual(first_bill.status, "PAID")


class LeaseSchedulePreviewTests(TestCase):
    def test_payment_schedule_preview_uses_expected_move_in_and_rent_sequence(self):
        service = LeaseSchedulingService()
        preview = service.get_payment_schedule_preview({
            "monthly_rent": Decimal("10000.00"),
            "advance_months": 2,
            "security_deposit": Decimal("20000.00"),
            "start_date": date(2026, 1, 15),
            "due_day": 5,
        })

        self.assertIsNotNone(preview)
        self.assertEqual(preview["advance_payment_amount"], Decimal("20000.00"))
        self.assertEqual(preview["total_move_in_cost"], Decimal("40000.00"))
        self.assertEqual(len(preview["events"]), 8)
        self.assertEqual(preview["events"][0]["type"], "Security Deposit")
        self.assertEqual(preview["events"][1]["type"], "Advance Payment")
        self.assertEqual(preview["events"][2]["type"], "Rent Due")
        self.assertEqual(preview["events"][2]["date"], date(2026, 3, 5))


class TenantRiskTimelinessTests(TestCase):
    def test_payment_timeliness_ignores_future_bills(self):
        tenant = User.objects.create_user(
            email="risk@example.com",
            username="risk",
            password="password123",
            role=User.Role.TENANT,
        )
        unit = Unit.objects.create(number="RK-101")
        lease = Lease.objects.create(
            tenant=tenant,
            unit=unit,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 1, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 3, 1),
            due_date=date(2026, 3, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10000.00"),
            status="PAID",
            paid_at=datetime(2026, 3, 5, 10, 0, tzinfo=zoneinfo.ZoneInfo("UTC")),
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
            status="UNPAID",
        )

        with patch("rentals.services.timezone.now", return_value=datetime(2026, 6, 2, 12, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))):
            score = TenantRiskService._calculate_payment_timeliness(tenant)

        self.assertEqual(score, 100)


class TenantPasswordTests(TestCase):
    def test_generate_tenant_password_uses_initials_and_last_name(self):
        self.assertEqual(generate_tenant_password("John Michael", "Smith"), "JMSmith")

    def test_generate_tenant_password_pads_short_values(self):
        password = generate_tenant_password("Al", "Li")
        self.assertGreaterEqual(len(password), 6)
        self.assertTrue(password.startswith("ALi"))

    def test_password_helper_steps_are_deterministic(self):
        first_name, last_name = _normalize_tenant_name_parts("  John  Michael ", " Smith ")
        initials = _extract_tenant_initials(first_name)
        password = _assemble_tenant_password(initials, last_name)
        padded = _pad_tenant_password("AB")

        self.assertEqual(first_name, "John  Michael")
        self.assertEqual(last_name, "Smith")
        self.assertEqual(initials, "JM")
        self.assertEqual(password, "JMSmith")
        self.assertEqual(len(padded), 6)

    def test_create_tenant_with_credentials_supports_legacy_call_shape(self):
        uploader = User.objects.create_user(
            email="admin@example.com",
            username="adminuser",
            password="password123",
            role=User.Role.ADMIN,
        )
        with patch("rentals.services.generate_tenant_password", return_value="JDoe99"), patch(
            "rentals.services.send_tenant_credentials_email", return_value=True
        ):
            profile, password, email_sent = create_tenant_with_credentials(
                "John",
                "Doe",
                "john.doe@example.com",
                "09171234567",
                uploader,
            )

        self.assertEqual(password, "JDoe99")
        self.assertTrue(email_sent)
        self.assertEqual(profile.first_name, "John")
        self.assertEqual(profile.last_name, "Doe")
        self.assertEqual(profile.contact_no, "09171234567")
