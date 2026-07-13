from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.utils import timezone

from billing.models import BillLineItem, MonthlyBill
from billing.services import add_months, get_or_update_monthly_bill, month_start, sync_monthly_bill_from_line_items
from .models import MaintenanceCharge


@dataclass
class MaintenanceChargePostingResult:
    success: bool
    charge: MaintenanceCharge
    bill: MonthlyBill | None = None
    bill_line_item: BillLineItem | None = None
    warning: str = ""


def _charge_reference_date(charge: MaintenanceCharge) -> date:
    req = charge.maintenance_request
    if req.resolved_at:
        return timezone.localtime(req.resolved_at).date()
    if charge.approved_at:
        return timezone.localtime(charge.approved_at).date()
    if req.requested_schedule_at:
        return timezone.localtime(req.requested_schedule_at).date()
    return req.created_at.date()


def _lease_is_billable_for_charge(lease, reference_date: date) -> bool:
    if lease is None:
        return False
    if getattr(lease, "status", "") != getattr(lease, "STATUS_ACTIVE", "ACTIVE"):
        return False
    if lease.start_date and reference_date < lease.start_date:
        return False
    if lease.end_date and reference_date > lease.end_date:
        return False
    return True


def _billable_month_limit(lease) -> date | None:
    if lease and lease.end_date:
        return month_start(lease.end_date)
    return None


def select_target_bill_for_maintenance_charge(charge: MaintenanceCharge, *, today: date | None = None) -> MonthlyBill | None:
    lease = getattr(charge.maintenance_request, "lease", None)
    if lease is None:
        return None

    if today is None:
        today = timezone.localdate()

    reference_date = _charge_reference_date(charge)
    if not _lease_is_billable_for_charge(lease, reference_date):
        return None

    base_month = month_start(reference_date)
    if lease.start_date:
        base_month = max(base_month, month_start(lease.start_date))

    end_month = _billable_month_limit(lease)
    if end_month and base_month > end_month:
        return None

    existing_unpaid = (
        MonthlyBill.objects.filter(lease=lease)
        .exclude(status="PAID")
        .filter(billing_month__gte=base_month)
        .order_by("billing_month", "id")
        .first()
    )
    if existing_unpaid:
        return get_or_update_monthly_bill(lease, existing_unpaid.billing_month, today=today)

    candidate_month = base_month
    for _ in range(13):
        if end_month and candidate_month > end_month:
            break
        bill = get_or_update_monthly_bill(lease, candidate_month, today=today)
        if bill.status != "PAID":
            return bill
        candidate_month = add_months(candidate_month, 1)
    return None


def post_maintenance_charge_to_billing(charge: MaintenanceCharge, *, today: date | None = None) -> MaintenanceChargePostingResult:
    if today is None:
        today = timezone.localdate()

    if charge.status != MaintenanceCharge.STATUS_READY_FOR_BILLING:
        return MaintenanceChargePostingResult(
            success=False,
            charge=charge,
            warning="Only charges marked ready for billing can be posted.",
        )

    if charge.admin_approved_total is None or charge.admin_approved_total <= Decimal("0.00"):
        return MaintenanceChargePostingResult(
            success=False,
            charge=charge,
            warning="This repair charge has no approved billable amount.",
        )

    bill = select_target_bill_for_maintenance_charge(charge, today=today)
    if bill is None:
        return MaintenanceChargePostingResult(
            success=False,
            charge=charge,
            warning="No active billable lease or valid unpaid/upcoming bill is available for this repair charge yet.",
        )

    if bill.status == "PAID":
        return MaintenanceChargePostingResult(
            success=False,
            charge=charge,
            bill=bill,
            warning="Paid bills are immutable. No valid unpaid/upcoming bill is available for this repair charge yet.",
        )

    maintenance_line = bill.line_items.filter(line_type=BillLineItem.LINE_TYPE_MAINTENANCE).first()
    if maintenance_line is None:
        maintenance_line = BillLineItem.objects.create(
            monthly_bill=bill,
            line_type=BillLineItem.LINE_TYPE_MAINTENANCE,
            amount=Decimal("0.00"),
            paid_amount=Decimal("0.00"),
            status=BillLineItem.STATUS_UNPAID,
        )

    sibling_total = (
        MaintenanceCharge.objects.filter(bill_line_item=maintenance_line, status=MaintenanceCharge.STATUS_ADDED_TO_BILL)
        .exclude(pk=charge.pk)
        .values_list("admin_approved_total", flat=True)
    )
    aggregate_amount = sum((amount or Decimal("0.00") for amount in sibling_total), Decimal("0.00"))
    aggregate_amount = (aggregate_amount + charge.admin_approved_total).quantize(Decimal("0.01"))

    maintenance_line.amount = aggregate_amount
    maintenance_line.refresh_status()
    maintenance_line.save(update_fields=["amount", "status", "updated_at"])
    sync_monthly_bill_from_line_items(bill)

    charge.bill_line_item = maintenance_line
    charge.status = MaintenanceCharge.STATUS_ADDED_TO_BILL
    charge.save(update_fields=["bill_line_item", "status", "updated_at"])

    return MaintenanceChargePostingResult(
        success=True,
        charge=charge,
        bill=bill,
        bill_line_item=maintenance_line,
    )
