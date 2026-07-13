from datetime import date
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
import zoneinfo

from django.test import TestCase

from accounts.models import User
from billing.models import BillLineItem, MonthlyBill
from payments.models import ManualPayment
from rentals.models import Lease, TenantProfile, Unit
from rentals.services import (
    LeaseActivationService,
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
from rentals.views import _dashboard_billing_context, _monthly_status_rows
from water.models import WaterBill


class TenantViewWorkflowTests(TestCase):
    def setUp(self):
        self.tenant = User.objects.create_user(
            email="tenant-view@gmail.com",
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

    def test_advance_payment_options_stop_at_contract_end_after_current_month_is_paid(self):
        lease = self.create_active_lease(
            start_date=date(2026, 6, 18),
            end_date=date(2026, 10, 18),
            due_day=18,
        )
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 6, 1),
            due_date=date(2026, 6, 18),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10350.00"),
            status="PAID",
        )

        with patch("rentals.views.timezone.localdate", return_value=date(2026, 6, 18)):
            with patch("rentals.views.date") as view_date:
                view_date.today.return_value = date(2026, 6, 18)
                view_date.fromisoformat.side_effect = date.fromisoformat
                view_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
                with patch("billing.services.date") as service_date:
                    service_date.today.return_value = date(2026, 6, 18)
                    service_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
                    response = self.client.get("/tenant/pay/?months_to_pay=6&payment_type=rent_only")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["months_options"], [1, 2, 3, 4])
        self.assertEqual(response.context["months_to_pay"], 4)
        self.assertEqual(response.context["max_months_to_pay"], 4)
        self.assertEqual(
            [row["month_label"] for row in response.context["preview_rows"]],
            ["July 2026", "August 2026", "September 2026", "October 2026"],
        )
        self.assertFalse(MonthlyBill.objects.filter(lease=lease, billing_month=date(2026, 11, 1)).exists())

    def test_advance_payment_preview_caps_open_contract_to_six_months(self):
        lease = self.create_active_lease(
            start_date=date(2026, 6, 18),
            end_date=date(2027, 6, 18),
            due_day=18,
        )
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 6, 1),
            due_date=date(2026, 6, 18),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10350.00"),
            status="PAID",
        )

        with patch("rentals.views.timezone.localdate", return_value=date(2026, 6, 18)):
            with patch("rentals.views.date") as view_date:
                view_date.today.return_value = date(2026, 6, 18)
                view_date.fromisoformat.side_effect = date.fromisoformat
                view_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
                with patch("billing.services.date") as service_date:
                    service_date.today.return_value = date(2026, 6, 18)
                    service_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
                    response = self.client.get("/tenant/pay/?months_to_pay=12&payment_type=rent_only")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["months_options"], [1, 2, 3, 4, 5, 6])
        self.assertEqual(response.context["months_to_pay"], 6)
        self.assertEqual(response.context["max_months_to_pay"], 6)
        self.assertEqual(
            [row["month_label"] for row in response.context["preview_rows"]],
            [
                "July 2026",
                "August 2026",
                "September 2026",
                "October 2026",
                "November 2026",
                "December 2026",
            ],
        )

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

    def test_payment_preview_allows_maintenance_only_when_full_is_disabled(self):
        lease = self.create_active_lease()
        bill = MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 1, 1),
            due_date=date(2026, 1, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("11250.00"),
            status="UNPAID",
        )
        BillLineItem.objects.create(
            monthly_bill=bill,
            line_type=BillLineItem.LINE_TYPE_MAINTENANCE,
            amount=Decimal("900.00"),
        )

        response = self.client.get("/tenant/pay/?payment_type=maintenance_only")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_pay_full_bill"])
        self.assertTrue(response.context["maintenance_only_available"])
        self.assertEqual(response.context["payment_type"], "maintenance_only")
        self.assertEqual(response.context["total_amount"], 900.0)
        self.assertEqual(response.context["total_maintenance"], 900.0)

    def test_payment_post_redirect_preserves_maintenance_only_payment_type(self):
        lease = self.create_active_lease()
        bill = MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 1, 1),
            due_date=date(2026, 1, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10900.00"),
            status="UNPAID",
        )
        BillLineItem.objects.create(
            monthly_bill=bill,
            line_type=BillLineItem.LINE_TYPE_MAINTENANCE,
            amount=Decimal("900.00"),
        )

        response = self.client.post("/tenant/pay/?payment_type=maintenance_only")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/payments/gcash/manual/", response["Location"])
        self.assertIn("amount=900.0", response["Location"])
        self.assertIn(f"bill_ids={bill.id}", response["Location"])
        self.assertIn("payment_type=maintenance_only", response["Location"])

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
        self.assertEqual(response.context["transactions"][0]["bill_months_label"], "January 2026")

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

    def test_tenant_billing_ignores_bills_after_contract_end(self):
        lease = self.create_active_lease(
            start_date=date(2026, 6, 18),
            end_date=date(2026, 10, 18),
            due_day=18,
        )
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 6, 1),
            due_date=date(2026, 6, 18),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10350.00"),
            status="PAID",
        )
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2027, 1, 1),
            due_date=date(2027, 1, 18),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10350.00"),
            status="UNPAID",
        )

        with patch("rentals.views.timezone.localdate", return_value=date(2026, 6, 18)):
            with patch("billing.services.date") as service_date:
                service_date.today.return_value = date(2026, 6, 18)
                service_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
                response = self.client.get("/tenant/billing/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["current_bill"])
        self.assertEqual(
            [row["month_label"] for row in response.context["monthly_status_rows"]],
            ["June 2026", "July 2026", "August 2026", "September 2026", "October 2026"],
        )

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

    def test_monthly_status_rows_include_full_contract_range_as_upcoming(self):
        lease = self.create_active_lease(
            start_date=date(2026, 6, 1),
            end_date=date(2027, 6, 1),
        )
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 6, 1),
            due_date=date(2026, 6, 5),
            base_rent=Decimal("10000.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10350.00"),
            rent_paid=Decimal("10000.00"),
            parking_paid=Decimal("350.00"),
            status="PAID",
        )

        rows = _monthly_status_rows(lease, today=date(2026, 6, 13))

        self.assertEqual(len(rows), 13)
        self.assertEqual(rows[0]["month_label"], "June 2026")
        self.assertEqual(rows[0]["status_label"], "Paid")
        self.assertEqual(rows[1]["month_label"], "July 2026")
        self.assertEqual(rows[1]["status_label"], "Upcoming")
        self.assertEqual(rows[-1]["month_label"], "June 2027")
        self.assertEqual(rows[-1]["status_label"], "Upcoming")
        self.assertEqual(rows[1]["balance"], Decimal("10350.00"))

    def test_monthly_status_rows_keep_future_partial_balance_visible(self):
        lease = self.create_active_lease(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 8, 1),
        )
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 7, 1),
            due_date=date(2026, 7, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("500.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10850.00"),
            rent_paid=Decimal("4000.00"),
            status="PARTIALLY_PAID",
        )

        rows = _monthly_status_rows(lease, today=date(2026, 6, 13))
        july_row = next(row for row in rows if row["month_label"] == "July 2026")

        self.assertEqual(july_row["status_label"], "Partially Paid")
        self.assertEqual(july_row["balance"], Decimal("6850.00"))

    def test_cancelled_paymongo_checkout_draft_is_removed_from_tenant_payment_page(self):
        lease = self.create_active_lease()
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 6, 1),
            due_date=date(2026, 6, 5),
            base_rent=Decimal("10000.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10350.00"),
            status="UNPAID",
        )
        payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-PM-CANCELLED",
            bill_ids="1",
            payment_type="rent_only",
            payment_method="PAYMONGO",
            amount=Decimal("10350.00"),
            status="PENDING",
            checkout_session_id="cs_test_cancelled",
        )

        response = self.client.get("/tenant/pay/?cancelled=1")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ManualPayment.objects.filter(pk=payment.pk).exists())
        self.assertFalse(
            ManualPayment.objects.filter(
                user=self.tenant,
                payment_method="PAYMONGO",
                status="PENDING",
                paymongo_payment_id="",
            ).exists()
        )


class MoveInRepairWorkflowTests(TestCase):
    def setUp(self):
        self.tenant = User.objects.create_user(
            email="repair@gmail.com",
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
    def _create_lease_with_tenant(self):
        tenant = User.objects.create_user(
            email="risk@gmail.com",
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
        return tenant, lease

    def test_payment_timeliness_ignores_future_bills(self):
        tenant, lease = self._create_lease_with_tenant()
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

    def test_payment_consistency_ignores_future_unpaid_bills(self):
        tenant, lease = self._create_lease_with_tenant()
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 5, 1),
            due_date=date(2026, 5, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10000.00"),
            status="PAID",
            paid_at=datetime(2026, 5, 5, 10, 0, tzinfo=zoneinfo.ZoneInfo("UTC")),
        )
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 9, 1),
            due_date=date(2026, 9, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10000.00"),
            status="UNPAID",
        )

        with patch("rentals.services.timezone.now", return_value=datetime(2026, 6, 2, 12, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))):
            score = TenantRiskService._calculate_payment_consistency(tenant)

        self.assertEqual(score, 100)

    def test_current_payment_status_ignores_future_unpaid_bills(self):
        tenant, lease = self._create_lease_with_tenant()
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 10, 1),
            due_date=date(2026, 10, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10000.00"),
            status="UNPAID",
        )

        with patch("rentals.services.timezone.now", return_value=datetime(2026, 6, 2, 12, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))):
            score = TenantRiskService._calculate_current_payment_status(tenant)

        self.assertEqual(score, 70)

    def test_late_payment_count_does_not_flag_same_due_date_payment(self):
        tenant, lease = self._create_lease_with_tenant()
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 6, 1),
            due_date=date(2026, 6, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10000.00"),
            status="PAID",
            paid_at=datetime(2026, 6, 5, 23, 59, tzinfo=zoneinfo.ZoneInfo("UTC")),
        )

        with patch("rentals.services.timezone.now", return_value=datetime(2026, 6, 6, 12, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))):
            risk = TenantRiskService.update_tenant_risk_classification(tenant)

        self.assertIsNotNone(risk)
        self.assertEqual(risk.late_payment_count, 0)

    def test_risk_score_uses_date_valid_active_lease_when_is_active_flag_is_stale(self):
        tenant, lease = self._create_lease_with_tenant()
        lease.is_active = False
        lease.save(update_fields=["is_active"])
        MonthlyBill.objects.create(
            lease=lease,
            billing_month=date(2026, 6, 1),
            due_date=date(2026, 6, 5),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10000.00"),
            status="PAID",
            paid_at=datetime(2026, 6, 5, 10, 0, tzinfo=zoneinfo.ZoneInfo("UTC")),
        )

        with patch("rentals.services.timezone.now", return_value=datetime(2026, 6, 6, 12, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))):
            risk = TenantRiskService.update_tenant_risk_classification(tenant)

        self.assertIsNotNone(risk)
        self.assertGreaterEqual(risk.payment_score, 80)

    def test_advance_paid_future_contract_months_count_as_strong_payment_history(self):
        tenant, lease = self._create_lease_with_tenant()
        for month in (7, 8, 9):
            MonthlyBill.objects.create(
                lease=lease,
                billing_month=date(2026, month, 1),
                due_date=date(2026, month, 5),
                base_rent=Decimal("10000.00"),
                water_amount=Decimal("0.00"),
                parking_fee=Decimal("0.00"),
                interest=Decimal("0.00"),
                total_due=Decimal("10000.00"),
                status="PAID",
                paid_at=datetime(2026, 6, 16, 10, 0, tzinfo=zoneinfo.ZoneInfo("UTC")),
            )

        with patch("rentals.services.timezone.now", return_value=datetime(2026, 6, 17, 12, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))):
            risk = TenantRiskService.update_tenant_risk_classification(tenant)

        self.assertIsNotNone(risk)
        self.assertGreaterEqual(risk.payment_score, 90)
        self.assertEqual(risk.risk_level, "LOW")
        self.assertEqual(risk.risk_factors["payment_timeliness"], 100)
        self.assertEqual(risk.risk_factors["payment_consistency"], 100)


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
            email="admin@gmail.com",
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
                "john.doe@gmail.com",
                "09171234567",
                uploader,
            )

        self.assertEqual(password, "JDoe99")
        self.assertTrue(email_sent)
        self.assertEqual(profile.first_name, "John")
        self.assertEqual(profile.last_name, "Doe")
        self.assertEqual(profile.contact_no, "09171234567")

    def test_activation_welcome_does_not_reset_password_or_resend_credentials(self):
        tenant = User.objects.create_user(
            email="activation.tenant@gmail.com",
            username="activationtenant",
            password="original-password",
            role=User.Role.TENANT,
        )
        profile = TenantProfile.objects.create(
            user=tenant,
            first_name="Activation",
            last_name="Tenant",
            has_seen_unit_welcome=True,
        )
        unit = Unit.objects.create(number="ACT-1", monthly_rent=Decimal("12000.00"), status="OCCUPIED")
        lease = Lease.objects.create(
            tenant=tenant,
            unit=unit,
            monthly_rent=Decimal("12000.00"),
            due_day=5,
            start_date=date(2026, 6, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        original_password_hash = tenant.password

        with patch("rentals.services.send_tenant_credentials_email") as credentials_email, patch(
            "rentals.services.send_email_via_resend", return_value=True
        ) as activation_email:
            LeaseActivationService._send_activation_welcome(lease)

        tenant.refresh_from_db()
        profile.refresh_from_db()
        self.assertEqual(tenant.password, original_password_hash)
        self.assertFalse(profile.has_seen_unit_welcome)
        credentials_email.assert_not_called()
        activation_email.assert_called_once()
