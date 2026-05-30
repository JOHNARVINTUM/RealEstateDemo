from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from billing.models import MonthlyBill
from payments.models import ManualPayment
from rentals.models import Lease, TenantProfile, Unit
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
            total_due=Decimal("11150.00"),
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
        self.assertEqual(response.context["total_amount"], 10350.0)
        self.assertEqual(response.context["total_rent"], 10000.0)
        self.assertEqual(response.context["total_parking"], 350.0)
        self.assertEqual(response.context["preview_rows"][0]["bill_id"], bill.id)

    def test_advance_payment_defaults_to_rent_only(self):
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
        )

        response = self.client.get("/tenant/pay/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["payment_type"], "rent_only")
        self.assertEqual(response.context["total_amount"], 10350.0)
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
            total_due=Decimal("10350.00"),
            status="UNPAID",
        )

        response = self.client.get("/tenant/pay/?payment_type=full")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["payment_type"], "rent_only")
        self.assertEqual(response.context["total_amount"], 10350.0)
        self.assertEqual(response.context["preview_rows"][0]["bill_id"], bill.id)

    def test_payment_preview_allows_full_when_rent_and_water_are_posted(self):
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
        )

        response = self.client.get("/tenant/pay/?payment_type=full")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["full_bill_available"])
        self.assertTrue(response.context["can_pay_full_bill"])
        self.assertEqual(response.context["payment_type"], "full")
        self.assertEqual(response.context["total_amount"], 11150.0)
        self.assertEqual(response.context["preview_rows"][0]["bill_id"], bill.id)

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
            total_due=Decimal("10350.00"),
            status="UNPAID",
        )

        response = self.client.post("/tenant/pay/?payment_type=rent_only")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/payments/gcash/manual/", response["Location"])
        self.assertIn("amount=10350.0", response["Location"])
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
