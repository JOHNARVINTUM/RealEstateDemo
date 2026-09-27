from datetime import date
import importlib
from decimal import Decimal

from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from accounts.models import User
from billing.models import MonthlyBill
from rentals.models import Lease, Unit
from water.models import WaterBillingSettings, WaterRate, WaterReading
from water.services import (
    compute_water_reading,
    create_or_update_monthly_bill_from_reading,
    get_active_rate_for_date,
)


class WaterRateConstraintTests(TransactionTestCase):
    def test_database_allows_one_active_rate_per_effective_date(self):
        effective_date = date(2026, 7, 1)
        WaterRate.objects.create(
            effective_date=effective_date,
            rate_per_cu_m=Decimal("45.00"),
            is_active=True,
        )

        with self.assertRaises(IntegrityError):
            WaterRate.objects.create(
                effective_date=effective_date,
                rate_per_cu_m=Decimal("55.00"),
                is_active=True,
            )

        WaterRate.objects.create(
            effective_date=effective_date,
            rate_per_cu_m=Decimal("40.00"),
            is_active=False,
        )
        WaterRate.objects.create(
            effective_date=effective_date,
            rate_per_cu_m=Decimal("35.00"),
            is_active=False,
        )
        WaterRate.objects.create(
            effective_date=date(2026, 8, 1),
            rate_per_cu_m=Decimal("60.00"),
            is_active=True,
        )

        self.assertEqual(
            WaterRate.objects.filter(effective_date=effective_date, is_active=True).count(),
            1,
        )
        self.assertEqual(
            WaterRate.objects.filter(effective_date=effective_date, is_active=False).count(),
            2,
        )

    def test_rate_selection_uses_latest_applicable_effective_date(self):
        WaterRate.objects.create(
            effective_date=date(2026, 6, 1),
            rate_per_cu_m=Decimal("40.00"),
        )
        latest_rate = WaterRate.objects.create(
            effective_date=date(2026, 7, 1),
            rate_per_cu_m=Decimal("50.00"),
        )

        self.assertEqual(
            get_active_rate_for_date(date(2026, 7, 31)).pk,
            latest_rate.pk,
        )


class WaterRateMigrationGuardTests(SimpleTestCase):
    def test_guard_reports_conflicting_effective_date_and_rate_ids(self):
        migration_module = importlib.import_module(
            "water.migrations.0005_unique_active_water_rate_per_effective_date"
        )

        class DuplicateQuery:
            def values(self, *args):
                return self

            def annotate(self, **kwargs):
                return self

            def filter(self, **kwargs):
                return self

            def order_by(self, *args):
                return [
                    {
                        "effective_date": date(2026, 7, 1),
                        "active_rate_count": 2,
                    }
                ]

        class RateIdQuery:
            def order_by(self, *args):
                return self

            def values_list(self, *args, **kwargs):
                return [41, 42]

        class FakeManager:
            def filter(self, **kwargs):
                if "effective_date" in kwargs:
                    return RateIdQuery()
                return DuplicateQuery()

        class FakeWaterRate:
            objects = FakeManager()

        class FakeApps:
            def get_model(self, app_label, model_name):
                return FakeWaterRate

        with self.assertRaisesRegex(
            RuntimeError,
            r"effective_date=2026-07-01 rate_ids=\[41, 42\]",
        ):
            migration_module.reject_existing_active_water_rate_duplicates(
                FakeApps(),
                None,
            )


class WaterComputationTests(TestCase):
    def setUp(self):
        self.tenant_a = User.objects.create_user(
            email="water-a@example.com",
            username="watera",
            password="password123",
            role=User.Role.TENANT,
        )
        self.tenant_b = User.objects.create_user(
            email="water-b@example.com",
            username="waterb",
            password="password123",
            role=User.Role.TENANT,
        )
        self.unit_a = Unit.objects.create(number="WA-1", status="OCCUPIED")
        self.unit_b = Unit.objects.create(number="WB-1", status="OCCUPIED")
        self.lease_a = Lease.objects.create(
            tenant=self.tenant_a,
            unit=self.unit_a,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 1, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        self.lease_b = Lease.objects.create(
            tenant=self.tenant_b,
            unit=self.unit_b,
            monthly_rent=Decimal("10000.00"),
            due_day=5,
            start_date=date(2026, 1, 1),
            status=Lease.STATUS_ACTIVE,
            is_active=True,
        )
        WaterRate.objects.create(
            effective_date=date(2026, 6, 1),
            rate_per_cu_m=Decimal("10.00"),
        )
        WaterBillingSettings.objects.create(
            reading_month=date(2026, 6, 1),
            shared_pump_total=Decimal("580.00"),
            vat_percent=Decimal("12.00"),
        )

    def test_shared_pump_vat_and_previous_unpaid_water_only(self):
        MonthlyBill.objects.create(
            lease=self.lease_a,
            billing_month=date(2026, 5, 1),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("100.00"),
            water_paid=Decimal("40.00"),
            parking_fee=Decimal("500.00"),
            total_due=Decimal("10600.00"),
            status="PARTIALLY_PAID",
        )
        reading_a = WaterReading(
            lease=self.lease_a,
            reading_month=date(2026, 6, 1),
            previous_reading=Decimal("0.00"),
            current_reading=Decimal("8.00"),
        )
        reading_b = WaterReading(
            lease=self.lease_b,
            reading_month=date(2026, 6, 1),
            previous_reading=Decimal("0.00"),
            current_reading=Decimal("50.00"),
        )

        compute_water_reading(
            reading_a,
            total_month_consumption=Decimal("58.00"),
            shared_pump_total=Decimal("580.00"),
            vat_percent=Decimal("12.00"),
        )
        compute_water_reading(
            reading_b,
            total_month_consumption=Decimal("58.00"),
            shared_pump_total=Decimal("580.00"),
            vat_percent=Decimal("12.00"),
        )

        self.assertEqual(reading_a.consumption, Decimal("8.00"))
        self.assertEqual(reading_a.base_water_amount, Decimal("80.00"))
        self.assertEqual(reading_a.shared_pump_amount, Decimal("80.00"))
        self.assertEqual(reading_a.vat_amount, Decimal("19.20"))
        self.assertEqual(reading_a.previous_unpaid_water_amount, Decimal("60.00"))
        self.assertEqual(reading_a.computed_amount, Decimal("239.20"))

        self.assertEqual(reading_b.consumption, Decimal("50.00"))
        self.assertEqual(reading_b.base_water_amount, Decimal("500.00"))
        self.assertEqual(reading_b.shared_pump_amount, Decimal("500.00"))
        self.assertEqual(reading_b.vat_amount, Decimal("120.00"))
        self.assertEqual(reading_b.previous_unpaid_water_amount, Decimal("0.00"))
        self.assertEqual(reading_b.computed_amount, Decimal("1120.00"))

    def test_rent_paid_bill_can_receive_unpaid_water_charge(self):
        bill = MonthlyBill.objects.create(
            lease=self.lease_a,
            billing_month=date(2026, 6, 1),
            base_rent=Decimal("10000.00"),
            rent_paid=Decimal("10000.00"),
            parking_fee=Decimal("350.00"),
            parking_paid=Decimal("350.00"),
            water_amount=Decimal("0.00"),
            water_paid=Decimal("0.00"),
            total_due=Decimal("10350.00"),
            status="PAID",
        )
        reading = WaterReading.objects.create(
            lease=self.lease_a,
            reading_month=date(2026, 6, 1),
            previous_reading=Decimal("0.00"),
            current_reading=Decimal("10.00"),
        )
        compute_water_reading(
            reading,
            total_month_consumption=Decimal("10.00"),
            shared_pump_total=Decimal("0.00"),
            vat_percent=Decimal("12.00"),
        )
        reading.save()

        updated_bill, created = create_or_update_monthly_bill_from_reading(
            reading,
            force_update=True,
        )
        bill.refresh_from_db()

        self.assertFalse(created)
        self.assertEqual(updated_bill.id, bill.id)
        self.assertEqual(bill.water_amount, Decimal("112.00"))
        self.assertEqual(bill.water_paid, Decimal("0.00"))
        self.assertEqual(bill.rent_paid, Decimal("10000.00"))
        self.assertEqual(bill.parking_paid, Decimal("350.00"))
        self.assertEqual(bill.status, "PARTIALLY_PAID")
