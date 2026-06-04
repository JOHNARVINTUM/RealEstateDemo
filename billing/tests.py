from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User
from billing.models import BillingInvoice, MonthlyBill
from billing.services import (
    approve_manual_payment,
    compute_weekly_interest,
    ensure_bills_since_move_in,
    ensure_bills_up_to,
    parse_bill_ids,
    reconcile_approved_payments_for_tenant,
)
from payments.models import ManualPayment
from rentals.models import Lease, Notification, Unit
from water.models import WaterBill, WaterBillingSettings, WaterRate, WaterReading


class BillingWorkflowTests(TestCase):
    def setUp(self):
        self.tenant = User.objects.create_user(
            email="tenant@example.com",
            username="tenant",
            password="password123",
            role=User.Role.TENANT,
        )
        self.other_tenant = User.objects.create_user(
            email="other@example.com",
            username="other",
            password="password123",
            role=User.Role.TENANT,
        )
        self.unit = Unit.objects.create(number="A-101")
        self.other_unit = Unit.objects.create(number="A-102")
        self.lease = Lease.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            monthly_rent=Decimal("10000.00"),
            due_day=31,
            start_date=date(2026, 1, 15),
            is_active=True,
        )
        self.other_lease = Lease.objects.create(
            tenant=self.other_tenant,
            unit=self.other_unit,
            monthly_rent=Decimal("8000.00"),
            due_day=5,
            start_date=date(2026, 1, 1),
            is_active=True,
        )

    def test_ensure_bills_since_move_in_creates_one_bill_per_month(self):
        WaterBill.objects.create(
            unit=self.unit,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
            rate_per_cu_m=Decimal("10.00"),
            prev_reading=Decimal("1.00"),
            curr_reading=Decimal("6.00"),
            status="POSTED",
        )

        ensure_bills_since_move_in(self.lease, today=date(2026, 3, 3))
        ensure_bills_since_move_in(self.lease, today=date(2026, 3, 3))

        bills = list(MonthlyBill.objects.filter(lease=self.lease).order_by("billing_month"))
        self.assertEqual([bill.billing_month for bill in bills], [
            date(2026, 1, 1),
            date(2026, 2, 1),
            date(2026, 3, 1),
        ])
        self.assertEqual(len(bills), 3)
        self.assertEqual(bills[0].due_date, date(2026, 1, 31))
        self.assertEqual(bills[1].water_amount, Decimal("50.00"))

    def test_ensure_bills_up_to_uses_bulk_path_instead_of_per_month_updates(self):
        with patch("billing.services.get_or_update_monthly_bill") as mocked_get_or_update:
            ensure_bills_up_to(self.lease, date(2026, 12, 1), today=date(2026, 6, 1))

        self.assertFalse(mocked_get_or_update.called)
        self.assertEqual(MonthlyBill.objects.filter(lease=self.lease).count(), 12)

    def test_approve_manual_payment_rejects_bills_outside_payment_owner(self):
        tenant_bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 2, 1),
            due_date=date(2026, 2, 28),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10000.00"),
        )
        other_bill = MonthlyBill.objects.create(
            lease=self.other_lease,
            billing_month=date(2026, 2, 1),
            due_date=date(2026, 2, 5),
            base_rent=Decimal("8000.00"),
            water_amount=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("8000.00"),
        )
        payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-123",
            bill_ids=f"{tenant_bill.id},{tenant_bill.id},{other_bill.id},invalid",
            amount=Decimal("10000.00"),
        )

        with self.assertRaises(ValidationError):
            approve_manual_payment(payment)

        tenant_bill.refresh_from_db()
        other_bill.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(payment.status, "PENDING")
        self.assertEqual(tenant_bill.status, "UNPAID")
        self.assertEqual(other_bill.status, "UNPAID")
        self.assertEqual(parse_bill_ids(payment.bill_ids), [tenant_bill.id, other_bill.id])

    def test_approve_manual_payment_is_idempotent_for_payment_owner_bill(self):
        tenant_bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 2, 1),
            due_date=date(2026, 2, 28),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10000.00"),
        )
        payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-123",
            bill_ids=f"{tenant_bill.id},{tenant_bill.id},invalid",
            amount=Decimal("10000.00"),
        )

        approve_manual_payment(payment)
        approve_manual_payment(payment)

        tenant_bill.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(payment.status, "APPROVED")
        self.assertEqual(tenant_bill.status, "PAID")
        self.assertEqual(tenant_bill.payment_reference, "REF-123")
        self.assertIsNotNone(tenant_bill.paid_at)
        self.assertEqual(parse_bill_ids(payment.bill_ids), [tenant_bill.id])
        self.assertEqual(BillingInvoice.objects.filter(payment=payment).count(), 1)

    def test_approve_rent_payment_creates_invoice_email_with_interest_snapshot(self):
        bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 6, 1),
            due_date=date(2026, 6, 30),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("500.00"),
            parking_fee=Decimal("0.00"),
            interest=Decimal("300.00"),
            total_due=Decimal("10800.00"),
            status="UNPAID",
        )
        payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-INV-1",
            bill_ids=str(bill.id),
            payment_type="rent_only",
            payment_method="GCASH",
            amount=Decimal("10300.00"),
        )

        with patch("rentals.services.send_email_via_resend", return_value=True) as send_email:
            approve_manual_payment(payment)

        invoice = BillingInvoice.objects.get(payment=payment)
        bill.refresh_from_db()

        self.assertTrue(invoice.email_sent)
        self.assertEqual(invoice.reference_code, "REF-INV-1")
        self.assertEqual(invoice.amount_paid, Decimal("10300.00"))
        self.assertEqual(invoice.snapshot["lines"][0]["rent_charge"], "10000.00")
        self.assertEqual(invoice.snapshot["lines"][0]["late_fee"], "300.00")
        self.assertEqual(invoice.snapshot["lines"][0]["amount_paid"], "10300.00")
        self.assertEqual(bill.interest, Decimal("0.00"))
        send_email.assert_called_once()

    def test_deleting_bill_removes_payment_history_reference(self):
        bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 4, 1),
            due_date=date(2026, 4, 30),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("0.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("10000.00"),
        )
        payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-DELETE",
            bill_ids=f"{bill.id},9999",
            status="APPROVED",
        )

        bill.delete()
        payment.refresh_from_db()

        self.assertEqual(payment.bill_ids, "9999")

    def test_rent_only_payment_settles_rent_and_parking_but_leaves_water(self):
        bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 2, 1),
            due_date=date(2026, 2, 28),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("1200.00"),
            parking_fee=Decimal("500.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("11700.00"),
            status="UNPAID",
        )
        payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-RENT-PARKING",
            bill_ids=str(bill.id),
            payment_type="rent_only",
            amount=Decimal("10500.00"),
            status="PENDING",
        )

        approve_manual_payment(payment)

        bill.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(payment.status, "APPROVED")
        self.assertEqual(bill.rent_paid, Decimal("10000.00"))
        self.assertEqual(bill.parking_paid, Decimal("500.00"))
        self.assertEqual(bill.water_paid, Decimal("0.00"))
        self.assertEqual(bill.water_balance, Decimal("1200.00"))
        self.assertEqual(bill.total_balance, Decimal("1200.00"))
        self.assertEqual(bill.status, "PARTIALLY_PAID")

    def test_rent_only_payment_includes_interest_and_leaves_water(self):
        bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 2, 1),
            due_date=date(2026, 2, 28),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("1200.00"),
            parking_fee=Decimal("500.00"),
            interest=Decimal("315.00"),
            total_due=Decimal("12015.00"),
            status="UNPAID",
        )
        payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-RENT-PARKING-INTEREST",
            bill_ids=str(bill.id),
            payment_type="rent_only",
            amount=Decimal("10815.00"),
            status="PENDING",
        )

        approve_manual_payment(payment)

        bill.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(payment.status, "APPROVED")
        self.assertEqual(bill.rent_paid, Decimal("10000.00"))
        self.assertEqual(bill.parking_paid, Decimal("500.00"))
        self.assertEqual(bill.interest, Decimal("0.00"))
        self.assertEqual(bill.total_due, Decimal("11700.00"))
        self.assertEqual(bill.water_paid, Decimal("0.00"))
        self.assertEqual(bill.water_balance, Decimal("1200.00"))
        self.assertEqual(bill.total_balance, Decimal("1200.00"))
        self.assertEqual(bill.status, "PARTIALLY_PAID")

    def test_water_payment_refreshes_future_unpaid_carryover(self):
        WaterRate.objects.create(
            effective_date=date(2026, 5, 1),
            rate_per_cu_m=Decimal("45.00"),
        )
        WaterBillingSettings.objects.create(
            reading_month=date(2026, 6, 1),
            shared_pump_total=Decimal("1110.08"),
            vat_percent=Decimal("12.00"),
        )
        may_reading = WaterReading.objects.create(
            lease=self.lease,
            reading_month=date(2026, 5, 1),
            previous_reading=Decimal("1795.33"),
            current_reading=Decimal("1848.87"),
            consumption=Decimal("53.54"),
            rate_used=Decimal("45.00"),
            computed_amount=Decimal("2409.30"),
        )
        june_reading = WaterReading.objects.create(
            lease=self.lease,
            reading_month=date(2026, 6, 1),
            previous_reading=Decimal("1848.87"),
            current_reading=Decimal("1900.87"),
            consumption=Decimal("52.00"),
            rate_used=Decimal("45.00"),
            base_water_amount=Decimal("2340.00"),
            shared_pump_amount=Decimal("1110.08"),
            vat_percent=Decimal("12.00"),
            vat_amount=Decimal("414.01"),
            previous_unpaid_water_amount=Decimal("2409.30"),
            computed_amount=Decimal("6273.39"),
        )
        may_bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 5, 1),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("2409.30"),
            total_due=Decimal("12409.30"),
            status="UNPAID",
            source_water_reading=may_reading,
        )
        june_bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 6, 1),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("6273.39"),
            total_due=Decimal("16273.39"),
            status="UNPAID",
            source_water_reading=june_reading,
        )
        payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-WATER-MAY",
            bill_ids=str(may_bill.id),
            payment_type="water_only",
            amount=Decimal("2409.30"),
            status="PENDING",
        )

        approve_manual_payment(payment)

        may_bill.refresh_from_db()
        june_bill.refresh_from_db()
        june_reading.refresh_from_db()
        self.assertEqual(may_bill.water_paid, Decimal("2409.30"))
        self.assertEqual(june_reading.previous_unpaid_water_amount, Decimal("0.00"))
        self.assertEqual(june_reading.computed_amount, Decimal("3864.09"))
        self.assertEqual(june_bill.water_amount, Decimal("3864.09"))
        self.assertEqual(june_bill.status, "UNPAID")

    def test_penalty_starts_only_after_two_weeks_late(self):
        interest, is_late, weeks_late = compute_weekly_interest(
            Decimal("10000.00"),
            due_date=date(2026, 7, 5),
            today=date(2026, 7, 18),
        )

        self.assertTrue(is_late)
        self.assertEqual(weeks_late, 0)
        self.assertEqual(interest, Decimal("0.00"))

    def test_penalty_becomes_flat_three_percent_after_two_weeks(self):
        interest, is_late, weeks_late = compute_weekly_interest(
            Decimal("10000.00"),
            due_date=date(2026, 7, 5),
            today=date(2026, 7, 19),
        )

        self.assertTrue(is_late)
        self.assertEqual(weeks_late, 2)
        self.assertEqual(interest, Decimal("300.00"))

    def test_penalty_does_not_continue_progressing_after_two_weeks(self):
        interest, is_late, weeks_late = compute_weekly_interest(
            Decimal("10000.00"),
            due_date=date(2026, 7, 5),
            today=date(2026, 8, 20),
        )

        self.assertTrue(is_late)
        self.assertEqual(weeks_late, 2)
        self.assertEqual(interest, Decimal("300.00"))

    def test_late_penalty_uses_rent_and_parking_base(self):
        bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 7, 1),
            due_date=date(2026, 7, 31),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("900.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("11250.00"),
            status="UNPAID",
        )
        self.lease.motorcycle_slots = 1
        self.lease.save(update_fields=["motorcycle_slots"])

        from billing.services import get_or_update_monthly_bill

        updated_bill = get_or_update_monthly_bill(
            self.lease,
            billing_month=date(2026, 7, 1),
            today=date(2026, 8, 14),
        )

        bill.refresh_from_db()
        self.assertEqual(updated_bill.interest, Decimal("310.50"))
        self.assertEqual(bill.interest, Decimal("310.50"))

    def test_reconcile_approved_payment_repairs_unapplied_online_payment(self):
        bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 3, 1),
            due_date=date(2026, 3, 31),
            base_rent=Decimal("10000.00"),
            water_amount=Decimal("900.00"),
            parking_fee=Decimal("350.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("11250.00"),
            status="UNPAID",
        )
        payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-REPAIR",
            bill_ids=str(bill.id),
            payment_type="rent_only",
            amount=Decimal("10350.00"),
            status="APPROVED",
        )

        reconcile_approved_payments_for_tenant(self.tenant)

        bill.refresh_from_db()
        self.assertEqual(Notification.objects.filter(user=self.tenant, title="Payment Approved").count(), 0)
        self.assertEqual(bill.rent_paid, Decimal("10000.00"))
        self.assertEqual(bill.parking_paid, Decimal("350.00"))
        self.assertEqual(bill.water_balance, Decimal("900.00"))
        self.assertEqual(bill.total_balance, Decimal("900.00"))
        self.assertEqual(bill.status, "PARTIALLY_PAID")
        self.assertEqual(bill.payment_reference, payment.reference_code)

    def test_reconcile_does_not_reapply_old_water_payment_after_water_bill_edit(self):
        bill = MonthlyBill.objects.create(
            lease=self.lease,
            billing_month=date(2026, 6, 1),
            due_date=date(2026, 6, 30),
            base_rent=Decimal("0.00"),
            water_amount=Decimal("150.00"),
            water_paid=Decimal("100.00"),
            interest=Decimal("0.00"),
            total_due=Decimal("150.00"),
            status="PARTIALLY_PAID",
            payment_reference="REF-WATER-OLD",
        )
        payment = ManualPayment.objects.create(
            user=self.tenant,
            reference_code="REF-WATER-OLD",
            bill_ids=str(bill.id),
            payment_type="water_only",
            amount=Decimal("100.00"),
            status="APPROVED",
        )

        reconcile_approved_payments_for_tenant(self.tenant)

        bill.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(payment.status, "APPROVED")
        self.assertEqual(bill.water_paid, Decimal("100.00"))
        self.assertEqual(bill.water_balance, Decimal("50.00"))
        self.assertEqual(bill.status, "PARTIALLY_PAID")


class LeaseActivationTimezoneTests(TestCase):
    """
    Ensure Lease.save() uses timezone.localdate() (Asia/Manila)
    so leases starting "today" in PH time are always marked active,
    even when UTC date is still yesterday.
    """

    def setUp(self):
        self.tenant = User.objects.create_user(
            email="tz_tenant@example.com",
            username="tz_tenant",
            password="password123",
            role=User.Role.TENANT,
        )
        self.unit = Unit.objects.create(number="TZ-001")

    def test_lease_active_when_start_date_is_today_local(self):
        from django.utils import timezone
        today_local = timezone.localdate()
        lease = Lease.objects.create(
            tenant=self.tenant, unit=self.unit,
            monthly_rent=Decimal("10000.00"), due_day=5, start_date=today_local,
        )
        self.assertEqual(lease.status, Lease.STATUS_PENDING_PAYMENT)
        self.assertFalse(lease.is_active)

    def test_lease_active_when_start_date_is_in_past(self):
        lease = Lease.objects.create(
            tenant=self.tenant, unit=self.unit,
            monthly_rent=Decimal("10000.00"), due_day=5, start_date=date(2025, 1, 1),
        )
        self.assertEqual(lease.status, Lease.STATUS_PENDING_PAYMENT)
        self.assertFalse(lease.is_active)

    def test_lease_inactive_when_start_date_is_future(self):
        from django.utils import timezone
        from datetime import timedelta
        tomorrow = timezone.localdate() + timedelta(days=1)
        lease = Lease.objects.create(
            tenant=self.tenant, unit=self.unit,
            monthly_rent=Decimal("10000.00"), due_day=5, start_date=tomorrow,
        )
        self.assertFalse(lease.is_active)

    def test_lease_uses_localdate_not_utc(self):
        """Simulate 1 AM Manila (May 25) = 5 PM UTC (May 24). Lease starting May 25 must be active."""
        from unittest.mock import patch
        from django.utils import timezone
        from datetime import datetime
        import zoneinfo

        fake_now = datetime(2026, 5, 24, 17, 0, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))
        with patch("django.utils.timezone.now", return_value=fake_now):
            local_date = timezone.localdate()
            lease = Lease.objects.create(
                tenant=self.tenant, unit=self.unit,
                monthly_rent=Decimal("10000.00"), due_day=5, start_date=date(2026, 5, 25),
            )
            self.assertEqual(local_date, date(2026, 5, 25))
            self.assertEqual(lease.status, Lease.STATUS_PENDING_PAYMENT)
            self.assertFalse(lease.is_active)


class MoveInFirstMonthPaidTests(TestCase):
    """
    Ensure the move-in flow marks the first month bill as PAID.
    """

    def setUp(self):
        self.tenant = User.objects.create_user(
            email="movein_tenant@example.com",
            username="movein_tenant",
            password="password123",
            role=User.Role.TENANT,
        )
        self.unit = Unit.objects.create(number="MI-001")

    def test_first_month_bill_marked_paid_after_move_in(self):
        from billing.services import month_start, get_or_update_monthly_bill, set_bill_status, ensure_bills_since_move_in
        from django.utils import timezone

        today_local = timezone.localdate()
        lease = Lease.objects.create(
            tenant=self.tenant, unit=self.unit,
            monthly_rent=Decimal("11666.00"), due_day=5, start_date=today_local,
        )
        ensure_bills_since_move_in(lease)

        first_bill_month = month_start(lease.start_date)
        first_bill = MonthlyBill.objects.filter(lease=lease, billing_month=first_bill_month).first()
        if not first_bill:
            first_bill = get_or_update_monthly_bill(lease, first_bill_month)

        self.assertIsNotNone(first_bill)

        set_bill_status(first_bill, status="PAID", payment_reference="REF-MOVEIN-TEST", paid_at=timezone.now())
        move_in_payment = ManualPayment.objects.create(
            user=self.tenant, payment_type="move_in", payment_method="GCASH",
            amount=lease.total_move_in_cost, reference_code="REF-MOVEIN-TEST",
            bill_ids=str(first_bill.id), status="APPROVED",
        )

        first_bill.refresh_from_db()
        self.assertEqual(first_bill.status, "PAID")
        self.assertEqual(first_bill.rent_paid, lease.monthly_rent)
        self.assertEqual(first_bill.total_balance, 0)
        self.assertEqual(move_in_payment.bill_ids, str(first_bill.id))

    def test_fallback_creates_first_bill_when_ensure_bills_skipped(self):
        from billing.services import month_start, get_or_update_monthly_bill

        lease = Lease.objects.create(
            tenant=self.tenant, unit=self.unit,
            monthly_rent=Decimal("10000.00"), due_day=5, start_date=date(2026, 5, 25),
        )
        first_bill_month = month_start(lease.start_date)
        self.assertEqual(MonthlyBill.objects.filter(lease=lease, billing_month=first_bill_month).count(), 0)

        first_bill = get_or_update_monthly_bill(lease, first_bill_month)
        self.assertIsNotNone(first_bill)
        self.assertEqual(first_bill.base_rent, Decimal("10000.00"))
        self.assertEqual(first_bill.status, "UNPAID")
