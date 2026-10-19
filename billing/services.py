from datetime import date
from decimal import Decimal
import calendar
import hashlib
import json

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.core.exceptions import ValidationError
from django.utils import timezone

from billing.models import BillingInvoice, BillLineItem, MonthlyBill
from water.models import WaterBill

# One-time 3% late fee on rent plus parking; water is excluded.
FLAT_LATE_FEE_RATE = Decimal("0.03")


def _money(value) -> str:
    return f"{Decimal(value or 0).quantize(Decimal('0.01'))}"


def _tenant_display_name(user) -> str:
    try:
        full_name = user.tenantprofile.full_name.strip()
        if full_name:
            return full_name
    except Exception:
        pass
    return user.email


def month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, 1)


def months_between(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield date(y, m, 1)
        m += 1
        if m == 13:
            m = 1
            y += 1


def due_date_for_month(year: int, month: int, due_day: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    day = min(max(due_day, 1), last_day)
    return date(year, month, day)


def normalized_monthly_rent(lease) -> Decimal:
    rent = Decimal(lease.monthly_rent or 0)
    if rent < Decimal("0.00"):
        raise ValueError("Lease monthly rent cannot be negative.")
    return rent.quantize(Decimal("0.01"))


def compute_weekly_interest(charge_base: Decimal, due_date: date, today: date) -> tuple[Decimal, bool, int]:
    """
    Legacy-named helper for a one-time flat 3% late fee after a 14-day grace period:
    - 0 to 13 days late => no penalty yet
    - 14+ days late => +3% once
    - penalty does not keep increasing after that
    """
    if today <= due_date:
        return Decimal("0.00"), False, 0

    days_late = (today - due_date).days
    if days_late < 14:
        return Decimal("0.00"), True, 0

    late_fee = (charge_base * FLAT_LATE_FEE_RATE).quantize(Decimal("0.01"))
    return late_fee, True, 2


def expected_flat_late_interest_for_bill(bill: MonthlyBill, today: date | None = None) -> Decimal:
    today = today or timezone.localdate()
    if not bill.due_date:
        return Decimal("0.00")
    charge_base = (Decimal(bill.base_rent or 0) + Decimal(bill.parking_fee or 0)).quantize(Decimal("0.01"))
    interest, _, _ = compute_weekly_interest(charge_base, bill.due_date, today)
    return interest


def _late_fee_repair_references():
    """Return exact bill IDs referenced by legacy payment/invoice bill_ids text."""
    from payments.models import ManualPayment

    payment_bill_ids = set()
    for raw_ids in ManualPayment.objects.exclude(bill_ids="").values_list("bill_ids", flat=True):
        payment_bill_ids.update(parse_bill_ids(raw_ids))

    invoice_bill_ids = set()
    for raw_ids in BillingInvoice.objects.exclude(bill_ids="").values_list("bill_ids", flat=True):
        invoice_bill_ids.update(parse_bill_ids(raw_ids))
    return payment_bill_ids, invoice_bill_ids


def _late_fee_repair_snapshot_token(bill, *, expected_interest, today):
    payload = {
        "id": bill.pk,
        "status": bill.status,
        "billing_month": bill.billing_month.isoformat() if bill.billing_month else None,
        "due_date": bill.due_date.isoformat() if bill.due_date else None,
        "base_rent": str(bill.base_rent),
        "water_amount": str(bill.water_amount),
        "parking_fee": str(bill.parking_fee),
        "interest": str(bill.interest),
        "total_due": str(bill.total_due),
        "expected_interest": str(expected_interest),
        "today": today.isoformat(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _legacy_late_fee_repair_candidate(
    bill, *, today, payment_bill_ids, invoice_bill_ids,
):
    """Return a preview row or a single explicit reason the legacy row is unsafe."""
    old_interest = Decimal(bill.interest or 0).quantize(Decimal("0.01"))
    expected_interest = expected_flat_late_interest_for_bill(bill, today=today)
    row = {
        "bill_id": bill.pk,
        "billing_month": bill.billing_month,
        "status": bill.status,
        "tenant_email": bill.lease.tenant.email if bill.lease and bill.lease.tenant else "",
        "unit": bill.lease.unit.number if bill.lease and bill.lease.unit else "",
        "old_interest": old_interest,
        "new_interest": expected_interest,
        "old_total_due": Decimal(bill.total_due or 0).quantize(Decimal("0.01")),
        "new_total_due": (
            Decimal(bill.base_rent or 0)
            + Decimal(bill.water_amount or 0)
            + Decimal(bill.parking_fee or 0)
            + expected_interest
        ).quantize(Decimal("0.01")),
        "reason": "Legacy summary-only bill exceeds the current one-time late fee.",
    }

    if bill.billing_month and bill.billing_month.replace(day=1) > today.replace(day=1):
        return None, "Future billing month."
    if bill.status == "PAID":
        return None, "Paid bills are never repaired."
    if bill.status == "PARTIALLY_PAID":
        return None, "Partially paid bills require payment-allocation review."
    if bill.status != "UNPAID":
        return None, "Bill status is not UNPAID."
    if bill.line_items.exists():
        return None, "Bill has BillLineItems; the line ledger is authoritative."
    if (
        Decimal(bill.rent_paid or 0) != 0
        or Decimal(bill.water_paid or 0) != 0
        or Decimal(bill.parking_paid or 0) != 0
        or bill.paid_at
        or bill.rent_paid_at
        or bill.water_paid_at
        or (bill.payment_reference or "").strip()
    ):
        return None, "Legacy payment indicators are present."
    if bill.pk in payment_bill_ids:
        return None, "A ManualPayment references this bill through bill_ids."
    if bill.pk in invoice_bill_ids:
        return None, "A BillingInvoice references this bill through bill_ids."
    if not bill.due_date:
        return None, "Due date is missing; the late-fee rule cannot be evaluated."
    if any(Decimal(value or 0) < 0 for value in (
        bill.base_rent, bill.water_amount, bill.parking_fee, bill.interest,
    )):
        return None, "Negative legacy charge values require manual review."

    legacy_total = (
        Decimal(bill.base_rent or 0)
        + Decimal(bill.water_amount or 0)
        + Decimal(bill.parking_fee or 0)
        + old_interest
    ).quantize(Decimal("0.01"))
    if row["old_total_due"] != legacy_total:
        return None, "Summary fields do not reconcile before repair."
    if Decimal(bill.total_balance).quantize(Decimal("0.01")) != row["old_total_due"]:
        return None, "Legacy balance does not match total_due."
    if row["old_total_due"] < 0 or row["new_total_due"] < 0:
        return None, "Bill summary would have a negative total."
    if bill.due_date.toordinal() + 14 > today.toordinal():
        return None, "The 14-day late-fee threshold has not been reached."
    if old_interest <= expected_interest:
        return None, "Stored interest does not exceed the current flat fee."

    row["reduction"] = (old_interest - expected_interest).quantize(Decimal("0.01"))
    row["snapshot_token"] = _late_fee_repair_snapshot_token(
        bill, expected_interest=expected_interest, today=today,
    )
    return row, None


def repair_inflated_unpaid_late_fees(
    *, today: date | None = None, dry_run: bool = True,
    bill_ids=None, preview_tokens=None, operator=None,
):
    """Preview or explicitly apply safe repairs to legacy summary-only bills.

    Line-backed, paid, allocated, invoiced, inconsistent, and otherwise
    ambiguous bills are reported as skipped. Apply mode requires selected IDs,
    the preview snapshot for each ID, and the authenticated operator.
    """
    from django.contrib.admin.models import CHANGE, LogEntry
    from django.contrib.contenttypes.models import ContentType

    today = today or timezone.localdate()
    eligible = []
    skipped = []
    repaired = []
    total_reduction = Decimal("0.00")

    if dry_run:
        payment_bill_ids, invoice_bill_ids = _late_fee_repair_references()
    else:
        if operator is None or not getattr(operator, "is_authenticated", False):
            raise ValueError("An authenticated operator is required to apply repairs.")
        selected_ids = sorted({int(value) for value in (bill_ids or [])})
        preview_tokens = preview_tokens or {}
        with transaction.atomic():
            queryset = list(
                MonthlyBill.objects.select_for_update().filter(pk__in=selected_ids)
                .select_related("lease", "lease__tenant", "lease__unit").order_by("pk")
            )
            # Recheck linkage only after locking the selected bill rows, rather
            # than relying on preview-time or pre-lock references.
            payment_bill_ids, invoice_bill_ids = _late_fee_repair_references()
            found_ids = {bill.pk for bill in queryset}
            for missing_id in sorted(set(selected_ids) - found_ids):
                skipped.append({"bill_id": missing_id, "reason": "Bill no longer exists."})

            content_type = ContentType.objects.get_for_model(MonthlyBill)
            for bill in queryset:
                row, reason = _legacy_late_fee_repair_candidate(
                    bill, today=today,
                    payment_bill_ids=payment_bill_ids,
                    invoice_bill_ids=invoice_bill_ids,
                )
                if reason:
                    skipped.append({"bill_id": bill.pk, "reason": reason})
                    continue
                if preview_tokens.get(str(bill.pk)) != row["snapshot_token"]:
                    skipped.append({"bill_id": bill.pk, "reason": "Bill changed since preview; refresh and review it."})
                    continue

                old_interest = row["old_interest"]
                old_total_due = row["old_total_due"]
                bill.interest = row["new_interest"]
                bill.total_due = row["new_total_due"]
                bill.save(update_fields=["interest", "total_due"])
                LogEntry.objects.create(
                    user=operator,
                    content_type=content_type,
                    object_id=str(bill.pk),
                    object_repr=str(bill)[:200],
                    action_flag=CHANGE,
                    change_message=(
                        "Legacy late-fee summary repair. "
                        f"Reason: {row['reason']} "
                        f"Interest: {old_interest} -> {row['new_interest']}. "
                        f"total_due: {old_total_due} -> {row['new_total_due']}."
                    ),
                )
                row["operator"] = operator.get_username()
                repaired.append(row)
                total_reduction += row["reduction"]

    if dry_run:
        queryset = MonthlyBill.objects.filter(interest__gt=0).select_related(
            "lease", "lease__tenant", "lease__unit",
        ).order_by("pk")
        for bill in queryset:
            row, reason = _legacy_late_fee_repair_candidate(
                bill, today=today,
                payment_bill_ids=payment_bill_ids,
                invoice_bill_ids=invoice_bill_ids,
            )
            if reason:
                skipped.append({
                    "bill_id": bill.pk,
                    "billing_month": bill.billing_month,
                    "status": bill.status,
                    "old_interest": Decimal(bill.interest or 0).quantize(Decimal("0.01")),
                    "old_total_due": Decimal(bill.total_due or 0).quantize(Decimal("0.01")),
                    "reason": reason,
                })
            else:
                eligible.append(row)
                total_reduction += row["reduction"]

    return {
        "dry_run": dry_run,
        "eligible": eligible,
        "skipped": skipped,
        "repaired": repaired,
        "eligible_count": len(eligible),
        "repaired_count": len(repaired),
        "skipped_count": len(skipped),
        "total_reduction": total_reduction.quantize(Decimal("0.01")),
    }


def get_water_amount_for_month(unit, billing_month: date) -> Decimal:
    """
    Pull the POSTED water bill for that month (if any).
    If none exists yet, return 0.00.
    """
    wb = WaterBill.objects.filter(
        unit=unit,
        period_start__year=billing_month.year,
        period_start__month=billing_month.month,
        status="POSTED",
    ).first()
    return wb.total_amount if wb else Decimal("0.00")


def _same_calendar_month_bill_queryset(lease, billing_month: date):
    return MonthlyBill.objects.filter(
        lease=lease,
        billing_month__year=billing_month.year,
        billing_month__month=billing_month.month,
    ).order_by("billing_month", "id")


def _preferred_monthly_bill(month_bills):
    return next(
        (
            candidate for candidate in month_bills
            if _bill_has_activity(candidate)
        ),
        month_bills[0] if month_bills else None,
    )


def _lease_is_billable_today(lease, today: date) -> bool:
    return (
        lease is not None
        and lease.status == lease.STATUS_ACTIVE
        and lease.start_date <= today
        and (lease.end_date is None or lease.end_date >= today)
    )


def lease_covers_billing_month(lease, billing_month: date) -> bool:
    billing_month = month_start(billing_month)
    next_month = add_months(billing_month, 1)
    return (
        lease is not None
        and lease.status == lease.STATUS_ACTIVE
        and lease.start_date < next_month
        and (lease.end_date is None or lease.end_date >= billing_month)
    )


def current_month_billable_leases(today: date | None = None):
    from django.db.models import Q
    from rentals.models import Lease

    today = today or timezone.localdate()
    current_month = month_start(today)
    next_month = add_months(current_month, 1)
    return Lease.objects.select_related("tenant", "tenant__tenantprofile", "unit").filter(
        status=Lease.STATUS_ACTIVE,
        start_date__lt=next_month,
    ).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=current_month)
    ).order_by("id")


def _current_month_bill_result(
    *,
    status: str,
    lease_id=None,
    bill_id=None,
    error_category: str = "",
):
    return {
        "status": status,
        "lease_id": lease_id,
        "bill_id": bill_id,
        "error_category": error_category,
    }


def _existing_bill_for_month(lease, billing_month: date):
    return _preferred_monthly_bill(list(_same_calendar_month_bill_queryset(lease, billing_month)))


def ensure_current_month_bill_for_lease(
    lease_or_id,
    *,
    target_month: date | None = None,
    today: date | None = None,
    dry_run: bool = False,
):
    from rentals.models import Lease

    today = today or timezone.localdate()
    current_month = month_start(target_month or today)
    lease_id = getattr(lease_or_id, "id", lease_or_id)

    try:
        if dry_run:
            lease = lease_or_id if hasattr(lease_or_id, "id") else Lease.objects.filter(pk=lease_id).first()
            if not lease_covers_billing_month(lease, current_month):
                return _current_month_bill_result(status="ineligible", lease_id=lease_id)
            bill = _existing_bill_for_month(lease, current_month)
            if bill:
                return _current_month_bill_result(status="existing", lease_id=lease.id, bill_id=bill.id)
            return _current_month_bill_result(status="would_create", lease_id=lease.id)

        with transaction.atomic():
            lease = Lease.objects.select_for_update().select_related("tenant", "unit").filter(pk=lease_id).first()
            if not lease_covers_billing_month(lease, current_month):
                return _current_month_bill_result(status="ineligible", lease_id=lease_id)

            bill = _existing_bill_for_month(lease, current_month)
            if bill:
                return _current_month_bill_result(status="existing", lease_id=lease.id, bill_id=bill.id)

            try:
                with transaction.atomic():
                    bill = get_or_update_monthly_bill(lease, current_month, today=today)
            except IntegrityError:
                bill = _existing_bill_for_month(lease, current_month)
                if not bill:
                    raise
                return _current_month_bill_result(status="existing", lease_id=lease.id, bill_id=bill.id)

            return _current_month_bill_result(status="created", lease_id=lease.id, bill_id=bill.id)
    except Exception as exc:
        return _current_month_bill_result(status="failed", lease_id=lease_id, error_category=exc.__class__.__name__)

def _bill_has_activity(bill: MonthlyBill) -> bool:
    return (
        bill.status in ("PAID", "PARTIALLY_PAID")
        or bill.rent_paid > 0
        or bill.water_paid > 0
        or bill.parking_paid > 0
        or bill.water_amount > 0
    )


def _is_safe_duplicate_candidate(bill: MonthlyBill) -> bool:
    return (
        bill.status == "UNPAID"
        and bill.rent_paid == 0
        and bill.water_paid == 0
        and bill.parking_paid == 0
    )


def cleanup_duplicate_monthly_bills_for_lease(lease) -> int:
    """
    Remove redundant unpaid duplicate rows that were created when older bills used
    non-normalized billing_month dates within the same calendar month.

    Safety rules:
    - never delete a PAID or PARTIALLY_PAID row
    - only delete UNPAID rows with zero paid amounts
    - only delete when another row already exists for the same lease+calendar month
    """
    removed = 0
    seen_months = set()
    for bill in MonthlyBill.objects.filter(lease=lease).order_by("billing_month", "id"):
        month_key = (bill.billing_month.year, bill.billing_month.month)
        if month_key in seen_months:
            continue
        seen_months.add(month_key)

        month_bills = list(_same_calendar_month_bill_queryset(lease, bill.billing_month))
        if len(month_bills) <= 1:
            continue

        keeper = _preferred_monthly_bill(month_bills)

        for candidate in month_bills:
            if candidate.pk == keeper.pk:
                continue
            if _is_safe_duplicate_candidate(candidate):
                candidate.delete()
                removed += 1

    return removed


def duplicate_monthly_bill_cleanup_preview():
    rows = []
    total_candidates = 0
    grouped = {}
    bills = MonthlyBill.objects.select_related("lease", "lease__tenant", "lease__unit").order_by(
        "lease_id",
        "billing_month",
        "id",
    )
    for bill in bills:
        grouped.setdefault((bill.lease_id, bill.billing_month.year, bill.billing_month.month), []).append(bill)

    for (_, _, _), month_bills in grouped.items():
        if len(month_bills) <= 1:
            continue

        keeper = _preferred_monthly_bill(month_bills)
        candidates = [bill for bill in month_bills if bill.pk != keeper.pk and _is_safe_duplicate_candidate(bill)]
        if not candidates:
            continue

        total_candidates += len(candidates)
        for candidate in candidates:
            rows.append({
                "bill_id": candidate.id,
                "tenant_email": candidate.lease.tenant.email if candidate.lease and candidate.lease.tenant else "",
                "unit": candidate.lease.unit.number if candidate.lease and candidate.lease.unit else "",
                "billing_month": candidate.billing_month,
                "status": candidate.status,
                "balance": candidate.total_balance,
                "keeper_id": keeper.id,
                "keeper_status": keeper.status,
            })

    return {
        "duplicate_count": total_candidates,
        "duplicates": rows,
    }


def _money_or_zero(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def _line_status(amount: Decimal, paid_amount: Decimal) -> str:
    if amount <= 0 or paid_amount >= amount:
        return BillLineItem.STATUS_PAID
    if paid_amount > 0:
        return BillLineItem.STATUS_PARTIAL
    return BillLineItem.STATUS_UNPAID


def _upsert_line_item(
    bill: MonthlyBill,
    line_type: str,
    *,
    amount,
    paid_amount=None,
    paid_at=None,
    payment_reference="",
    source_water_reading=None,
):
    amount = _money_or_zero(amount)
    paid_amount = _money_or_zero(paid_amount)
    if amount == 0 and paid_amount == 0:
        line = BillLineItem.objects.filter(monthly_bill=bill, line_type=line_type).first()
        if not line:
            return None
        line.amount = Decimal("0.00")
        line.paid_amount = Decimal("0.00")
        line.paid_at = None
        line.payment_reference = ""
        if line_type == BillLineItem.LINE_TYPE_WATER:
            line.source_water_reading = source_water_reading
        line.refresh_status()
        line.save(update_fields=[
            "amount",
            "paid_amount",
            "paid_at",
            "payment_reference",
            "source_water_reading",
            "status",
            "updated_at",
        ])
        return line

    line, _ = BillLineItem.objects.get_or_create(
        monthly_bill=bill,
        line_type=line_type,
        defaults={"amount": amount},
    )
    line.amount = amount
    line.paid_amount = min(paid_amount, amount) if amount > 0 else paid_amount
    line.paid_at = paid_at if line.paid_amount > 0 else None
    line.payment_reference = payment_reference if line.paid_amount > 0 else ""
    if line_type == BillLineItem.LINE_TYPE_WATER:
        line.source_water_reading = source_water_reading
    line.refresh_status()
    line.save(update_fields=[
        "amount",
        "paid_amount",
        "paid_at",
        "payment_reference",
        "source_water_reading",
        "status",
        "updated_at",
    ])
    return line


def ensure_bill_line_items_from_legacy(bill: MonthlyBill):
    _upsert_line_item(
        bill,
        BillLineItem.LINE_TYPE_RENT,
        amount=bill.base_rent,
        paid_amount=bill.rent_paid,
        paid_at=bill.rent_paid_at or bill.paid_at,
        payment_reference=bill.payment_reference,
    )
    _upsert_line_item(
        bill,
        BillLineItem.LINE_TYPE_PARKING,
        amount=bill.parking_fee,
        paid_amount=bill.parking_paid,
        paid_at=bill.rent_paid_at or bill.paid_at,
        payment_reference=bill.payment_reference,
    )
    _upsert_line_item(
        bill,
        BillLineItem.LINE_TYPE_WATER,
        amount=bill.water_amount,
        paid_amount=bill.water_paid,
        paid_at=bill.water_paid_at or bill.paid_at,
        payment_reference=bill.payment_reference,
        source_water_reading=bill.source_water_reading,
    )
    late_fee_line = bill.line_items.filter(
        line_type=BillLineItem.LINE_TYPE_LATE_FEE,
    ).first()
    # Once any part of a fee has been paid, the line is the durable charge and
    # allocation record. Do not reconstruct it from a legacy summary field
    # that may contain only the outstanding balance (or zero after payment).
    if late_fee_line is None or late_fee_line.paid_amount <= 0:
        _upsert_line_item(
            bill,
            BillLineItem.LINE_TYPE_LATE_FEE,
            amount=bill.interest,
            paid_amount=bill.interest if bill.status == "PAID" else Decimal("0.00"),
            paid_at=bill.paid_at,
            payment_reference=bill.payment_reference,
        )
    return list(bill.line_items.all())


def sync_monthly_bill_from_line_items(bill: MonthlyBill):
    lines = {
        line.line_type: line
        for line in bill.line_items.all()
    }
    rent = lines.get(BillLineItem.LINE_TYPE_RENT)
    parking = lines.get(BillLineItem.LINE_TYPE_PARKING)
    water = lines.get(BillLineItem.LINE_TYPE_WATER)
    late_fee = lines.get(BillLineItem.LINE_TYPE_LATE_FEE)

    bill.base_rent = rent.amount if rent else Decimal("0.00")
    bill.rent_paid = rent.paid_amount if rent else Decimal("0.00")
    bill.rent_paid_at = rent.paid_at if rent and rent.paid_amount > 0 else None
    bill.parking_fee = parking.amount if parking else Decimal("0.00")
    bill.parking_paid = parking.paid_amount if parking else Decimal("0.00")
    bill.water_amount = water.amount if water else Decimal("0.00")
    bill.water_paid = water.paid_amount if water else Decimal("0.00")
    bill.water_paid_at = water.paid_at if water and water.paid_amount > 0 else None
    bill.interest = late_fee.amount if late_fee else Decimal("0.00")
    bill.total_due = sum((line.amount for line in lines.values()), Decimal("0.00")).quantize(Decimal("0.01"))
    if water and water.source_water_reading:
        bill.source_water_reading = water.source_water_reading

    has_payment = any(line.paid_amount > 0 for line in lines.values())
    has_balance = any(line.balance > 0 for line in lines.values())
    paid_times = [line.paid_at for line in lines.values() if line.paid_at]
    if not has_balance and has_payment:
        bill.status = "PAID"
        bill.paid_at = max(paid_times) if paid_times else bill.paid_at
    elif has_payment:
        bill.status = "PARTIALLY_PAID"
        bill.paid_at = None
    else:
        bill.status = "UNPAID"
        bill.paid_at = None
    bill.save(update_fields=[
        "base_rent",
        "rent_paid",
        "rent_paid_at",
        "parking_fee",
        "parking_paid",
        "water_amount",
        "water_paid",
        "water_paid_at",
        "interest",
        "total_due",
        "status",
        "paid_at",
        "source_water_reading",
    ])
    return bill


def bill_line_items_for_payment_type(bill: MonthlyBill, payment_type: str):
    ensure_bill_line_items_from_legacy(bill)
    if payment_type == "rent_only":
        line_types = {
            BillLineItem.LINE_TYPE_RENT,
            BillLineItem.LINE_TYPE_PARKING,
            BillLineItem.LINE_TYPE_LATE_FEE,
        }
    elif payment_type == "water_only":
        line_types = {BillLineItem.LINE_TYPE_WATER}
    elif payment_type == "maintenance_only":
        line_types = {BillLineItem.LINE_TYPE_MAINTENANCE}
    else:
        line_types = {
            BillLineItem.LINE_TYPE_RENT,
            BillLineItem.LINE_TYPE_PARKING,
            BillLineItem.LINE_TYPE_WATER,
            BillLineItem.LINE_TYPE_LATE_FEE,
            BillLineItem.LINE_TYPE_MAINTENANCE,
        }
    return list(bill.line_items.filter(line_type__in=line_types))


def set_bill_line_item_amount(
    bill: MonthlyBill,
    line_type: str,
    *,
    amount,
    source_water_reading=None,
    protect_paid=True,
):
    ensure_bill_line_items_from_legacy(bill)
    amount = _money_or_zero(amount)
    line = bill.line_items.filter(line_type=line_type).first()
    paid_amount = line.paid_amount if line else Decimal("0.00")
    if protect_paid and line and line.paid_amount > 0 and line.amount != amount:
        raise ValidationError("Paid billing line items cannot be overwritten.")

    updated_line = _upsert_line_item(
        bill,
        line_type,
        amount=amount,
        paid_amount=paid_amount,
        paid_at=line.paid_at if line else None,
        payment_reference=line.payment_reference if line else "",
        source_water_reading=source_water_reading,
    )
    sync_monthly_bill_from_line_items(bill)
    return updated_line


def cleanup_duplicate_monthly_bills() -> int:
    preview = duplicate_monthly_bill_cleanup_preview()
    candidate_ids = [row["bill_id"] for row in preview["duplicates"]]
    if candidate_ids:
        MonthlyBill.objects.filter(pk__in=candidate_ids).delete()
    return len(candidate_ids)


def _resolve_monthly_bill_water_amount(lease, billing_month: date, same_month_bills) -> Decimal:
    existing_bill = next(
        (candidate for candidate in same_month_bills if candidate.water_computed_from_system),
        None,
    )
    if existing_bill:
        return existing_bill.water_amount
    return Decimal(get_water_amount_for_month(lease.unit, billing_month))


def _apply_monthly_bill_changes(bill, *, due_date, base_rent, water_amount, parking_fee, interest):
    changed = False
    if bill.due_date != due_date:
        bill.due_date = due_date
        changed = True
    if bill.base_rent != base_rent:
        bill.base_rent = base_rent
        changed = True
    if not bill.water_computed_from_system or bill.water_amount == 0:
        if bill.water_amount != water_amount:
            bill.water_amount = water_amount
            changed = True
    if bill.interest != interest:
        bill.interest = interest
        changed = True
    if bill.parking_fee != parking_fee:
        bill.parking_fee = parking_fee
        changed = True

    # MonthlyBill's legacy component fields do not represent every ledger
    # charge (for example, maintenance). Project the legacy lines at their
    # refreshed values while retaining every other existing line unchanged.
    # A paid late-fee line is durable history and is intentionally preserved
    # by ensure_bill_line_items_from_legacy(), even if the legacy interest
    # summary differs.
    existing_lines = list(bill.line_items.all())
    planned_line_amounts = {line.line_type: line.amount for line in existing_lines}
    planned_line_amounts.update({
        BillLineItem.LINE_TYPE_RENT: bill.base_rent,
        BillLineItem.LINE_TYPE_PARKING: bill.parking_fee,
        BillLineItem.LINE_TYPE_WATER: bill.water_amount,
    })
    late_fee_line = next(
        (
            line
            for line in existing_lines
            if line.line_type == BillLineItem.LINE_TYPE_LATE_FEE
        ),
        None,
    )
    planned_line_amounts[BillLineItem.LINE_TYPE_LATE_FEE] = (
        late_fee_line.amount
        if late_fee_line and late_fee_line.paid_amount > 0
        else bill.interest
    )
    new_total = sum(planned_line_amounts.values(), Decimal("0.00")).quantize(Decimal("0.01"))
    if bill.total_due != new_total:
        bill.total_due = new_total
        changed = True
    return changed


def _create_monthly_bill(lease, billing_month, due_date, base_rent, water_amount, parking_fee, interest, total_due):
    bill = MonthlyBill.objects.create(
        lease=lease,
        billing_month=billing_month,
        due_date=due_date,
        base_rent=base_rent,
        water_amount=water_amount,
        parking_fee=parking_fee,
        interest=interest,
        total_due=total_due,
        status="UNPAID",
        bill_type="RENT",
    )
    ensure_bill_line_items_from_legacy(bill)
    return bill


def _monthly_bill_values(lease, billing_month: date, today: date, water_amount: Decimal | None = None):
    billing_month = month_start(billing_month)
    due_date = due_date_for_month(billing_month.year, billing_month.month, lease.due_day)
    base_rent = normalized_monthly_rent(lease)
    parking_fee = Decimal(getattr(lease, 'parking_fee', 0)).quantize(Decimal("0.01"))
    interest_base = (base_rent + parking_fee).quantize(Decimal("0.01"))
    interest, is_late, weeks_late = compute_weekly_interest(interest_base, due_date, today)
    water_amount = Decimal(water_amount or 0).quantize(Decimal("0.01"))
    total_due = (base_rent + water_amount + parking_fee + interest).quantize(Decimal("0.01"))
    return {
        "due_date": due_date,
        "base_rent": base_rent,
        "water_amount": water_amount,
        "parking_fee": parking_fee,
        "interest": interest,
        "total_due": total_due,
        "is_late": is_late,
        "weeks_late": weeks_late,
    }


def _legacy_water_totals_by_month(unit, start: date, end: date) -> dict[tuple[int, int], Decimal]:
    totals = {}
    water_bills = WaterBill.objects.filter(
        unit=unit,
        period_start__gte=start,
        period_start__lt=add_months(end, 1),
        status="POSTED",
    ).values(
        "period_start",
        "prev_reading",
        "curr_reading",
        "rate_per_cu_m",
    ).annotate(
        charges_total=Sum("charges__amount"),
    )
    for water_bill in water_bills:
        month = water_bill["period_start"]
        consumption = max(
            Decimal(water_bill["curr_reading"] or 0) - Decimal(water_bill["prev_reading"] or 0),
            Decimal("0.00"),
        )
        consumption_amount = consumption * Decimal(water_bill["rate_per_cu_m"] or 0)
        charges_total = Decimal(water_bill["charges_total"] or 0)
        month_key = (month.year, month.month)
        totals[month_key] = (consumption_amount + charges_total).quantize(Decimal("0.01"))
    return totals


def _ensure_bills_for_range(
    lease,
    end_month: date,
    today: date,
    *,
    apply_move_in: bool = False,
    start_month: date | None = None,
):
    if lease is None or lease.status != lease.STATUS_ACTIVE:
        return

    lease_start = month_start(lease.start_date)
    start = month_start(start_month or lease.start_date)
    if start < lease_start:
        start = lease_start
    end = month_start(end_month)
    if lease.end_date:
        end = min(end, month_start(lease.end_date))
    if end < start:
        return

    months = list(months_between(start, end))
    existing_by_month = {}
    for bill in MonthlyBill.objects.filter(
        lease=lease,
        billing_month__gte=start,
        billing_month__lt=add_months(end, 1),
    ).order_by("billing_month", "id"):
        month_key = (bill.billing_month.year, bill.billing_month.month)
        if month_key not in existing_by_month or _bill_has_activity(bill):
            existing_by_month[month_key] = bill

    legacy_water_by_month = _legacy_water_totals_by_month(lease.unit, start, end)
    bills_to_create = []
    bills_to_update = []

    for billing_month in months:
        month_key = (billing_month.year, billing_month.month)
        bill = existing_by_month.get(month_key)
        values = _monthly_bill_values(
            lease,
            billing_month,
            today,
            water_amount=(bill.water_amount if bill and bill.water_computed_from_system else legacy_water_by_month.get(month_key, Decimal("0.00"))),
        )
        if bill is None:
            bills_to_create.append(MonthlyBill(
                lease=lease,
                billing_month=billing_month,
                due_date=values["due_date"],
                base_rent=values["base_rent"],
                water_amount=values["water_amount"],
                parking_fee=values["parking_fee"],
                interest=values["interest"],
                total_due=values["total_due"],
                status="UNPAID",
                bill_type="RENT",
            ))
            continue

        if bill.status == "PAID":
            continue

        changed = _apply_monthly_bill_changes(
            bill,
            due_date=values["due_date"],
            base_rent=values["base_rent"],
            water_amount=values["water_amount"],
            parking_fee=values["parking_fee"],
            interest=values["interest"],
        )
        if changed:
            bills_to_update.append(bill)

    if bills_to_create:
        MonthlyBill.objects.bulk_create(bills_to_create, ignore_conflicts=True)
    if bills_to_update:
        MonthlyBill.objects.bulk_update(
            bills_to_update,
            ["due_date", "base_rent", "water_amount", "parking_fee", "interest", "total_due"],
        )
    if bills_to_create or bills_to_update:
        for bill in MonthlyBill.objects.filter(
            lease=lease,
            billing_month__gte=start,
            billing_month__lt=add_months(end, 1),
        ):
            ensure_bill_line_items_from_legacy(bill)

    if apply_move_in:
        _apply_approved_move_in_payment_if_needed(lease)


def get_or_update_monthly_bill(lease, billing_month: date, today: date | None = None) -> MonthlyBill:
    """
    Creates/updates MonthlyBill totals for the month.
    - A one-time 3% late fee applies to rent plus parking after 14 days.
    - Water is included in total_due but excluded from the fee basis.
    """
    if today is None:
        today = timezone.localdate()

    billing_month = month_start(billing_month)
    due_date = due_date_for_month(billing_month.year, billing_month.month, lease.due_day)
    base_rent = normalized_monthly_rent(lease)
    same_month_bills = list(_same_calendar_month_bill_queryset(lease, billing_month))
    bill = _preferred_monthly_bill(same_month_bills)
    water_amount = _resolve_monthly_bill_water_amount(lease, billing_month, same_month_bills)
    parking_fee = Decimal(getattr(lease, 'parking_fee', 0)).quantize(Decimal("0.01"))
    interest_base = (base_rent + parking_fee).quantize(Decimal("0.01"))
    interest, is_late, weeks_late = compute_weekly_interest(interest_base, due_date, today)
    total_due = (base_rent + water_amount + parking_fee + interest).quantize(Decimal("0.01"))

    if bill is None:
        bill = _create_monthly_bill(
            lease,
            billing_month,
            due_date,
            base_rent,
            water_amount,
            parking_fee,
            interest,
            total_due,
        )

    # Never modify PAID bills - immutable for audit safety
    if bill.status == "PAID":
        bill._is_late = is_late
        bill._weeks_late = weeks_late
        return bill

    changed = _apply_monthly_bill_changes(
        bill,
        due_date=due_date,
        base_rent=base_rent,
        water_amount=water_amount,
        parking_fee=parking_fee,
        interest=interest,
    )

    if changed:
        bill.save()
        ensure_bill_line_items_from_legacy(bill)
    elif bill is not None:
        ensure_bill_line_items_from_legacy(bill)

    # extra values useful in UI
    bill._is_late = is_late
    bill._weeks_late = weeks_late
    return bill


def _late_fee_refresh_plan(bill: MonthlyBill, *, today: date) -> dict:
    """Build a read-only, conservative late-fee plan for one existing bill."""
    lines = list(bill.line_items.all())
    by_type = {}
    duplicate_line_type = None
    for line in lines:
        if line.line_type in by_type:
            duplicate_line_type = line.line_type
            break
        by_type[line.line_type] = line

    fee_line = by_type.get(BillLineItem.LINE_TYPE_LATE_FEE)
    fee_amount = fee_line.amount if fee_line else Decimal("0.00")
    paid_fee = fee_line.paid_amount if fee_line else Decimal("0.00")
    base = Decimal(bill.base_rent or 0).quantize(Decimal("0.01"))
    parking = Decimal(bill.parking_fee or 0).quantize(Decimal("0.01"))
    details = {
        "bill_id": bill.pk,
        "billing_month": bill.billing_month,
        "due_date": bill.due_date,
        "days_overdue": (today - bill.due_date).days if bill.due_date else None,
        "status": bill.status,
        "rent": base,
        "parking": parking,
        "current_interest": Decimal(bill.interest or 0),
        "existing_fee_amount": fee_amount,
        "expected_fee": Decimal("0.00"),
        "proposed_total_due": bill.total_due,
        "action": "skipped",
        "reason": "not eligible",
    }

    if duplicate_line_type:
        details["reason"] = f"duplicate {duplicate_line_type} lines"
        return details

    if bill.status not in {"UNPAID", "PARTIALLY_PAID"}:
        details["reason"] = "status is not UNPAID or PARTIALLY_PAID"
        return details
    if not bill.due_date:
        details["reason"] = "missing due date"
        return details
    if bill.billing_month.replace(day=1) > today.replace(day=1) or bill.due_date > today:
        details["reason"] = "future bill"
        return details
    if details["days_overdue"] < 14:
        details["reason"] = "less than 14 days past due"
        return details
    if base < 0 or parking < 0:
        details["reason"] = "negative rent or parking value"
        return details
    if not lines:
        details["reason"] = "bill has no line-item ledger"
        return details

    for line in lines:
        if line.amount < 0 or line.paid_amount < 0 or line.paid_amount > line.amount:
            details["reason"] = f"invalid amount/allocation on {line.line_type} line"
            return details

    rent_line = by_type.get(BillLineItem.LINE_TYPE_RENT)
    parking_line = by_type.get(BillLineItem.LINE_TYPE_PARKING)
    water_line = by_type.get(BillLineItem.LINE_TYPE_WATER)
    if (base > 0 and rent_line is None) or (rent_line and rent_line.amount != base):
        details["reason"] = "rent summary does not match its ledger line"
        return details
    if (parking > 0 and parking_line is None) or (parking_line and parking_line.amount != parking):
        details["reason"] = "parking summary does not match its ledger line"
        return details
    if Decimal(bill.water_amount or 0) != (water_line.amount if water_line else Decimal("0.00")):
        details["reason"] = "water summary does not match its ledger line"
        return details
    for summary_name, line, attribute in (
        ("rent payment summary", rent_line, "rent_paid"),
        ("parking payment summary", parking_line, "parking_paid"),
        ("water payment summary", water_line, "water_paid"),
    ):
        summary_value = Decimal(getattr(bill, attribute) or 0)
        line_value = line.paid_amount if line else Decimal("0.00")
        if summary_value != line_value:
            details["reason"] = f"{summary_name} does not match its ledger allocation"
            return details
    if rent_line and bill.rent_paid_at != (rent_line.paid_at if rent_line.paid_amount > 0 else None):
        details["reason"] = "rent payment timestamp does not match its ledger line"
        return details
    if water_line and bill.water_paid_at != (water_line.paid_at if water_line.paid_amount > 0 else None):
        details["reason"] = "water payment timestamp does not match its ledger line"
        return details
    if water_line and water_line.source_water_reading_id and bill.source_water_reading_id != water_line.source_water_reading_id:
        details["reason"] = "water-reading source does not match its ledger line"
        return details
    if fee_line and Decimal(bill.interest or 0) != fee_line.amount:
        details["reason"] = "interest summary does not match its late-fee line"
        return details
    if not fee_line and Decimal(bill.interest or 0) != 0:
        details["reason"] = "interest summary exists without a late-fee line"
        return details

    line_total = sum((line.amount for line in lines), Decimal("0.00"))
    line_balance = sum((line.balance for line in lines), Decimal("0.00"))
    if line_total != bill.total_due or line_balance != bill.total_balance:
        details["reason"] = "bill summary does not reconcile to its line-item ledger"
        return details
    if bill.total_balance <= 0:
        details["reason"] = "bill has no outstanding balance"
        return details
    has_allocations = any(line.paid_amount > 0 for line in lines)
    if (bill.status == "UNPAID" and has_allocations) or (bill.status == "PARTIALLY_PAID" and not has_allocations):
        details["reason"] = "payment allocations do not match bill status"
        return details
    if bill.paid_at is not None:
        details["reason"] = "unpaid/partially-paid bill has a paid timestamp"
        return details

    expected_fee, _, _ = compute_weekly_interest(base + parking, bill.due_date, today)
    details["expected_fee"] = expected_fee
    if expected_fee <= 0:
        details["reason"] = "late-fee basis is zero"
        return details
    if fee_line and paid_fee > 0 and fee_amount != expected_fee:
        details["reason"] = "allocated late-fee amount differs from the expected fee"
        return details

    target_fee = fee_amount if fee_line and paid_fee > 0 else expected_fee
    details["proposed_total_due"] = (bill.total_due + target_fee - fee_amount).quantize(Decimal("0.01"))
    if not fee_line:
        details.update(action="created", reason="eligible; late-fee line will be created")
    elif fee_amount != target_fee:
        details.update(action="updated", reason="eligible; unpaid late-fee line will be corrected")
    else:
        details.update(action="unchanged", reason="late-fee line already matches the one-time fee")
    return details


def refresh_late_fee_for_bill(bill_id: int, *, today: date | None = None, dry_run: bool = False) -> dict:
    """Safely add/update one eligible bill's late-fee line without recalculating other charges."""
    today = today or timezone.localdate()
    if dry_run:
        bill = (
            MonthlyBill.objects.filter(pk=bill_id)
            .prefetch_related("line_items")
            .first()
        )
        if bill is None:
            return {"bill_id": bill_id, "action": "skipped", "reason": "bill not found"}
        return _late_fee_refresh_plan(bill, today=today)

    with transaction.atomic():
        bill = (
            MonthlyBill.objects.select_for_update()
            .filter(pk=bill_id)
            .prefetch_related("line_items")
            .first()
        )
        if bill is None:
            return {"bill_id": bill_id, "action": "skipped", "reason": "bill not found"}

        plan = _late_fee_refresh_plan(bill, today=today)
        if plan["action"] not in {"created", "updated"}:
            return plan

        fee_line = bill.line_items.filter(line_type=BillLineItem.LINE_TYPE_LATE_FEE).first()
        if fee_line is None:
            fee_line = BillLineItem(
                monthly_bill=bill,
                line_type=BillLineItem.LINE_TYPE_LATE_FEE,
                amount=plan["expected_fee"],
                paid_amount=Decimal("0.00"),
            )
        else:
            # The plan only updates an unallocated line. Any existing payment
            # allocation is left untouched.
            fee_line.amount = plan["expected_fee"]
        fee_line.refresh_status()
        fee_line.save()

        # The locked bill was prefetched for validation. Invalidate that cache
        # so synchronization sees the inserted/updated fee line.
        bill._prefetched_objects_cache.pop("line_items", None)
        sync_monthly_bill_from_line_items(bill)
        bill.refresh_from_db()
        refreshed_lines = list(bill.line_items.all())
        gross_sum = sum((line.amount for line in refreshed_lines), Decimal("0.00"))
        balance_sum = sum((line.balance for line in refreshed_lines), Decimal("0.00"))
        if gross_sum != bill.total_due or balance_sum != bill.total_balance:
            raise ValidationError("Late-fee refresh failed bill ledger reconciliation.")

        plan["reason"] = "late-fee line created" if plan["action"] == "created" else "unpaid late-fee line updated"
        return plan


def ensure_bills_since_move_in(lease, today: date | None = None):
    if lease is None:
        return
    if today is None:
        today = timezone.localdate()
    _ensure_bills_for_range(lease, month_start(today), today, apply_move_in=True)


def ensure_current_month_bills(*, today: date | None = None, dry_run: bool = False):
    today = today or timezone.localdate()
    current_month = month_start(today)
    eligible_leases = list(current_month_billable_leases(today=today))
    existing_lease_ids = set(
        MonthlyBill.objects.filter(
            billing_month__year=current_month.year,
            billing_month__month=current_month.month,
            lease_id__in=[lease.id for lease in eligible_leases],
        ).values_list("lease_id", flat=True)
    )
    missing_leases = [lease for lease in eligible_leases if lease.id not in existing_lease_ids]

    if dry_run:
        results = [
            _current_month_bill_result(status="existing", lease_id=lease.id)
            if lease.id in existing_lease_ids
            else _current_month_bill_result(status="would_create", lease_id=lease.id)
            for lease in eligible_leases
        ]
    else:
        results = []
        for lease in eligible_leases:
            results.append(
                ensure_current_month_bill_for_lease(
                    lease.id,
                    target_month=current_month,
                    today=today,
                    dry_run=False,
                )
            )

    created_results = [result for result in results if result["status"] == "created"]
    existing_results = [result for result in results if result["status"] == "existing"]
    would_create_results = [result for result in results if result["status"] == "would_create"]
    ineligible_results = [result for result in results if result["status"] == "ineligible"]
    failed_results = [result for result in results if result["status"] == "failed"]

    return {
        "today": today,
        "current_month": current_month,
        "checked_count": len(eligible_leases),
        "created_count": len(created_results),
        "existing_count": len(existing_lease_ids),
        "skipped_count": len(existing_results) + len(would_create_results),
        "ineligible_count": len(ineligible_results),
        "failed_count": len(failed_results),
        "created_lease_ids": [result["lease_id"] for result in created_results],
        "created_bill_ids": [result["bill_id"] for result in created_results if result["bill_id"] is not None],
        "skipped_lease_ids": [result["lease_id"] for result in existing_results + would_create_results],
        "missing_lease_ids": [lease.id for lease in missing_leases],
        "failed": [
            {"lease_id": result["lease_id"], "error_category": result["error_category"]}
            for result in failed_results
        ],
        "results": results,
        "dry_run": dry_run,
    }

def _advance_generation_start_month(lease, today: date) -> date:
    lease_start = month_start(lease.start_date)
    current_month = month_start(today)
    earliest_open_bill_month = (
        MonthlyBill.objects.filter(lease=lease)
        .exclude(status="PAID")
        .order_by("billing_month")
        .values_list("billing_month", flat=True)
        .first()
    )

    if earliest_open_bill_month:
        current_month = min(current_month, month_start(earliest_open_bill_month))

    return max(lease_start, current_month)


def _apply_approved_move_in_payment_if_needed(lease):
    first_bill_month = month_start(lease.start_date)
    first_bill = MonthlyBill.objects.filter(lease=lease, billing_month=first_bill_month).first()
    if first_bill and first_bill.status != "PAID":
        from payments.models import ManualPayment
        has_approved_movein = ManualPayment.objects.filter(
            user=lease.tenant,
            payment_type="move_in",
            status="APPROVED",
        ).exists()
        if has_approved_movein:
            apply_move_in_payment_to_first_bill(lease, payment_reference="MOVE-IN-PAYMENT")


def apply_move_in_payment_to_first_bill(lease, payment_reference: str = "MOVE-IN-PAYMENT", paid_at=None):
    """
    Move-in payments cover first month rent + parking only.
    Water remains open if it was posted later for the same month.
    """
    from django.utils import timezone as tz

    first_bill_month = month_start(lease.start_date)
    first_bill = MonthlyBill.objects.filter(lease=lease, billing_month=first_bill_month).first()
    if not first_bill:
        return None

    paid_time = paid_at or tz.now()
    for line in bill_line_items_for_payment_type(first_bill, "rent_only"):
        if line.amount <= 0:
            continue
        line.paid_amount = line.amount
        line.paid_at = paid_time
        line.payment_reference = payment_reference
        line.refresh_status()
        line.save(update_fields=["paid_amount", "paid_at", "payment_reference", "status", "updated_at"])
    first_bill.payment_reference = payment_reference
    first_bill.save(update_fields=["payment_reference"])
    sync_monthly_bill_from_line_items(first_bill)
    return first_bill


def ensure_bills_up_to(lease, end_month: date, today: date | None = None):
    """
     For advance payment previews/payments (creates future MonthlyBill rows).
      Allows up to 12 months advance to match the tenant payment UI.
     """
    if lease is None:
        return
    if today is None:
        today = timezone.localdate()
    if not _lease_is_billable_today(lease, today):
        return

    end = month_start(end_month)
    if lease.end_date:
        end = min(end, month_start(lease.end_date))

    # Keep future generation bounded, but align it with the largest UI option.
    current_month = month_start(today)
    max_advance_months = 12
    max_date = add_months(current_month, max_advance_months)
    if end > max_date:
        end = max_date

    _ensure_bills_for_range(
        lease,
        end,
        today,
        apply_move_in=True,
        start_month=_advance_generation_start_month(lease, today),
    )


def badge_for_bill(bill: MonthlyBill, today: date | None = None) -> str:
    """
    For the "Ongoing Billing" table badge.
    Returns: OVERDUE, DUE_TODAY, NEAR_DUE, UPCOMING
    """
    if today is None:
        today = timezone.localdate()

    if bill.due_date < today:
        return "OVERDUE"
    if bill.due_date == today:
        return "DUE_TODAY"

    days_left = (bill.due_date - today).days
    if days_left <= 3:
        return "NEAR_DUE"
    return "UPCOMING"


def parse_bill_ids(raw_bill_ids: str) -> list[int]:
    seen = set()
    bill_ids = []

    for value in (raw_bill_ids or "").split(","):
        value = value.strip()
        if not value:
            continue
        try:
            bill_id = int(value)
        except ValueError:
            continue
        if bill_id in seen:
            continue
        seen.add(bill_id)
        bill_ids.append(bill_id)

    return bill_ids


def serialize_bill_ids(bill_ids: list[int]) -> str:
    return ",".join(str(bill_id) for bill_id in bill_ids)


def _is_payment_applied_to_bill(bill: MonthlyBill, payment) -> bool:
    payment_type = getattr(payment, "payment_type", "full")
    payment_reference = getattr(payment, "reference_code", "")
    payment_amount = Decimal(getattr(payment, "amount", 0) or 0).quantize(Decimal("0.01"))

    if payment_type == "rent_only":
        return all(
            line.amount <= 0 or line.paid_amount >= line.amount
            for line in bill_line_items_for_payment_type(bill, payment_type)
        )
    if payment_type == "water_only":
        if bill.water_paid <= 0:
            return False
        if bill.payment_reference == payment_reference:
            return True
        return payment_amount > 0 and bill.water_paid >= payment_amount

    if bill.payment_reference == payment_reference and (
        bill.rent_paid > 0 or bill.water_paid > 0 or bill.parking_paid > 0
    ):
        return True
    return bill.status == "PAID" and bill.total_balance == 0


def _payment_is_move_in(payment) -> bool:
    return getattr(payment, "payment_type", "full") == "move_in"


def _get_pending_move_in_lease(payment):
    from rentals.models import Lease

    lease_id = payment.lease_id
    if not lease_id and isinstance(payment.metadata, dict):
        lease_id = payment.metadata.get("lease_id")
    if not lease_id:
        return None

    try:
        lease_id = int(lease_id)
    except (TypeError, ValueError):
        return None

    return Lease.objects.filter(
        pk=lease_id,
        tenant=payment.user,
        status__in=(Lease.STATUS_PENDING_PAYMENT, Lease.STATUS_ACTIVE),
    ).select_related("unit").first()


def _approve_move_in_payment(payment, logger):
    from rentals.services import LeaseActivationService

    try:
        pending_lease = _get_pending_move_in_lease(payment)
        if not pending_lease:
            raise ValidationError(
                "Move-in payment requires an explicit, tenant-owned lease link before approval."
            )

        logger.info(f"Found explicit lease {pending_lease.id} for move-in payment {payment.id}")
        success, message = LeaseActivationService.activate_lease_after_payment(
            lease_id=pending_lease.id,
            payment_method=payment.payment_method,
            payment_reference=payment.reference_code,
            amount=payment.amount,
            existing_payment=payment,
        )
        if not success:
            logger.error(f"Lease activation failed: {message}")
            raise ValidationError(message)

        logger.info(f"Lease {pending_lease.id} activated via manual payment approval")
        payment.refresh_from_db()
        return payment
    except Exception as e:
        logger.exception(f"Error checking lease activation for payment {payment.id}: {e}")
        return None


def _validate_payment_type(payment_type: str):
    if payment_type not in {"full", "rent_only", "water_only", "maintenance_only"}:
        raise ValidationError("Invalid payment type.")


def _expected_amount_for_payment_type(bills, payment_type: str) -> Decimal:
    expected_amount = Decimal("0.00")
    for bill in bills:
        expected_amount += sum(
            (line.balance for line in bill_line_items_for_payment_type(bill, payment_type)),
            Decimal("0.00"),
        )
    return expected_amount.quantize(Decimal("0.01"))


def _payment_method_display(payment) -> str:
    if payment.payment_method == "GCASH":
        return "GCash"
    if payment.payment_method == "PAYMONGO":
        return "PayMongo"
    return "Face-to-Face Cash"


def _payment_type_display(payment_type: str) -> str:
    return {
        "full": "Full Payment",
        "rent_only": "Monthly Rent",
        "water_only": "Water Only",
        "maintenance_only": "Maintenance Charge Only",
        "move_in": "Move-in Payment",
    }.get(payment_type, "Payment")


def _invoice_number_for_payment(payment) -> str:
    return f"INV-PAY-{payment.id:06d}"


def _invoice_number_for_bill(bill) -> str:
    return f"INV-BILL-{bill.id:06d}"


def _build_invoice_line_for_bill(bill, payment_type: str):
    selected_lines = bill_line_items_for_payment_type(bill, payment_type)
    amounts = {
        line.line_type: line.amount
        for line in selected_lines
    }
    amount_paid = sum((line.balance for line in selected_lines), Decimal("0.00")).quantize(Decimal("0.01"))

    return {
        "bill_id": bill.id,
        "billing_month": bill.billing_month.strftime("%B %Y"),
        "unit": getattr(bill.lease.unit, "number", ""),
        "rent_charge": _money(amounts.get(BillLineItem.LINE_TYPE_RENT, Decimal("0.00"))),
        "water_charge": _money(amounts.get(BillLineItem.LINE_TYPE_WATER, Decimal("0.00"))),
        "parking_charge": _money(amounts.get(BillLineItem.LINE_TYPE_PARKING, Decimal("0.00"))),
        "maintenance_charge": _money(amounts.get(BillLineItem.LINE_TYPE_MAINTENANCE, Decimal("0.00"))),
        "late_fee": _money(amounts.get(BillLineItem.LINE_TYPE_LATE_FEE, Decimal("0.00"))),
        "total_due_before_payment": _money(amount_paid),
        "amount_paid": _money(amount_paid),
        "status_before_payment": bill.status,
    }


def _build_invoice_lines(bills, payment_type: str):
    return [_build_invoice_line_for_bill(bill, payment_type) for bill in bills]


def _invoice_lines_total(lines, key: str) -> Decimal:
    return sum((Decimal(line.get(key, "0.00")) for line in lines), Decimal("0.00")).quantize(Decimal("0.01"))


def _invoice_snapshot(*, tenant, payment, payment_type: str, method_display: str, lines, approved_at):
    totals = {
        "rent_charge": _money(_invoice_lines_total(lines, "rent_charge")),
        "water_charge": _money(_invoice_lines_total(lines, "water_charge")),
        "parking_charge": _money(_invoice_lines_total(lines, "parking_charge")),
        "maintenance_charge": _money(_invoice_lines_total(lines, "maintenance_charge")),
        "late_fee": _money(_invoice_lines_total(lines, "late_fee")),
        "total_due_before_payment": _money(_invoice_lines_total(lines, "total_due_before_payment")),
        "amount_paid": _money(_invoice_lines_total(lines, "amount_paid")),
    }
    return {
        "tenant_name": _tenant_display_name(tenant),
        "tenant_email": tenant.email,
        "reference_code": getattr(payment, "reference_code", "") if payment else "",
        "payment_method": method_display,
        "payment_type": _payment_type_display(payment_type),
        "paid_at": approved_at.isoformat() if approved_at else "",
        "lines": lines,
        "totals": totals,
    }


def _render_invoice_email(invoice: BillingInvoice) -> str:
    snapshot = invoice.snapshot or {}
    lines = snapshot.get("lines", [])
    totals = snapshot.get("totals", {})
    body = [
        f"Dear {snapshot.get('tenant_name') or invoice.tenant.email},",
        "",
        "Your payment has been marked as PAID. Below is your invoice computation.",
        "",
        f"Invoice No.: {invoice.invoice_number}",
        f"Reference No.: {invoice.reference_code or '-'}",
        f"Payment Method: {snapshot.get('payment_method') or invoice.payment_method}",
        f"Payment Type: {snapshot.get('payment_type') or invoice.payment_type}",
        f"Amount Paid: PHP {invoice.amount_paid:,.2f}",
        "",
        "Bill Computation:",
    ]
    for line in lines:
        body.extend([
            f"- {line.get('billing_month')} | Unit {line.get('unit')}",
            f"  Rent: PHP {Decimal(line.get('rent_charge', '0.00')):,.2f}",
            f"  Water: PHP {Decimal(line.get('water_charge', '0.00')):,.2f}",
            f"  Parking: PHP {Decimal(line.get('parking_charge', '0.00')):,.2f}",
            f"  Maintenance: PHP {Decimal(line.get('maintenance_charge', '0.00')):,.2f}",
            f"  Security Deposit: PHP {Decimal(line.get('security_deposit', '0.00')):,.2f}",
            f"  Contract Deposit: PHP {Decimal(line.get('contract_deposit', '0.00')):,.2f}",
            f"  Late Fee: PHP {Decimal(line.get('late_fee', '0.00')):,.2f}",
            f"  Total Before Payment: PHP {Decimal(line.get('total_due_before_payment', '0.00')):,.2f}",
            f"  Paid This Transaction: PHP {Decimal(line.get('amount_paid', '0.00')):,.2f}",
            "  Status: PAID",
        ])
    body.extend([
        "",
        "Thank you for your payment.",
        "",
        "REALESTATE360+ Administration",
    ])
    return "\n".join(body)


def _send_invoice_email(invoice: BillingInvoice, logger):
    if invoice.email_sent:
        return

    try:
        from rentals.services import send_email_via_resend

        sent = send_email_via_resend(
            to_email=invoice.tenant.email,
            subject=f"[REALESTATE360+] Invoice {invoice.invoice_number}",
            message=_render_invoice_email(invoice),
        )
        if sent:
            invoice.email_sent = True
            invoice.emailed_at = timezone.now()
            invoice.save(update_fields=["email_sent", "emailed_at"])
        else:
            logger.warning("Invoice email was not sent for invoice %s", invoice.invoice_number)
    except Exception as exc:
        logger.exception("Failed to send invoice email %s: %s", invoice.invoice_number, exc)


def create_and_send_invoice_for_payment(payment, bills, payment_type: str, approved_at, lines=None, logger=None):
    import logging

    logger = logger or logging.getLogger(__name__)
    if getattr(payment, "invoice", None):
        return payment.invoice

    lines = lines or _build_invoice_lines(bills, payment_type)
    method_display = _payment_method_display(payment)
    snapshot = _invoice_snapshot(
        tenant=payment.user,
        payment=payment,
        payment_type=payment_type,
        method_display=method_display,
        lines=lines,
        approved_at=approved_at,
    )
    invoice, created = BillingInvoice.objects.get_or_create(
        payment=payment,
        defaults={
            "invoice_number": _invoice_number_for_payment(payment),
            "tenant": payment.user,
            "bill_ids": payment.bill_ids,
            "reference_code": payment.reference_code,
            "payment_method": method_display,
            "payment_type": _payment_type_display(payment_type),
            "amount_paid": Decimal(payment.amount or 0).quantize(Decimal("0.01")),
            "snapshot": snapshot,
        },
    )
    if created:
        _send_invoice_email(invoice, logger)
    return invoice


def create_and_send_invoice_for_paid_bill(bill, *, paid_at=None, logger=None):
    import logging

    logger = logger or logging.getLogger(__name__)
    if BillingInvoice.objects.filter(payment__isnull=True, bill_ids=str(bill.id)).exists():
        return BillingInvoice.objects.filter(payment__isnull=True, bill_ids=str(bill.id)).first()

    paid_time = paid_at or bill.paid_at or timezone.now()
    line = _build_invoice_line_for_bill(bill, "full")
    line["status_before_payment"] = "MANUALLY_MARKED_PAID"
    line["amount_paid"] = _money(bill.base_rent + bill.water_amount + bill.parking_fee + bill.interest)
    snapshot = _invoice_snapshot(
        tenant=bill.lease.tenant,
        payment=None,
        payment_type="full",
        method_display="Admin Marked Paid",
        lines=[line],
        approved_at=paid_time,
    )
    invoice = BillingInvoice.objects.create(
        invoice_number=_invoice_number_for_bill(bill),
        tenant=bill.lease.tenant,
        bill_ids=str(bill.id),
        reference_code=bill.payment_reference,
        payment_method="Admin Marked Paid",
        payment_type="Full Payment",
        amount_paid=Decimal(line["amount_paid"]),
        snapshot=snapshot,
    )
    _send_invoice_email(invoice, logger)
    return invoice


def _apply_payment_to_bill(bill, payment, payment_type: str, approved_at):
    if bill.status == "PAID" and bill.payment_reference == payment.reference_code:
        ensure_bill_line_items_from_legacy(bill)
        return

    selected_lines = bill_line_items_for_payment_type(bill, payment_type)
    for line in selected_lines:
        if line.amount <= 0:
            continue
        line.paid_amount = line.amount
        line.paid_at = approved_at
        line.payment_reference = payment.reference_code
        line.refresh_status()
        line.save(update_fields=["paid_amount", "paid_at", "payment_reference", "status", "updated_at"])

    bill.payment_reference = payment.reference_code
    bill.save(update_fields=["payment_reference"])
    sync_monthly_bill_from_line_items(bill)


def _generate_next_month_bill_if_needed(bills, approved_at):
    if not bills or not all(b.status == "PAID" for b in bills):
        return

    latest_paid_bill = max(bills, key=lambda b: b.billing_month)
    next_month = add_months(latest_paid_bill.billing_month, 1)
    next_bill_exists = MonthlyBill.objects.filter(
        lease=latest_paid_bill.lease,
        billing_month=next_month,
    ).exists()
    if next_bill_exists:
        return

    lease = latest_paid_bill.lease
    get_or_update_monthly_bill(lease, next_month, today=approved_at.date())


def _load_bills_for_payment_approval(payment, logger):
    bill_ids = parse_bill_ids(payment.bill_ids)
    logger.info(f"Approving payment {payment.id} for bills: {bill_ids}, user: {payment.user.id}")
    if not bill_ids:
        logger.warning(f"No bill_ids found for payment {payment.id}")
        return bill_ids, []

    bills = list(
        MonthlyBill.objects.select_for_update().filter(
            pk__in=bill_ids,
            lease__tenant=payment.user,
        )
    )
    logger.info(f"Found {len(bills)} bills to update")
    if len(bills) != len(bill_ids):
        raise ValidationError("Some selected bills were not found or do not belong to this tenant.")
    return bill_ids, bills


def _payment_is_already_applied(payment, bills) -> bool:
    return all(_is_payment_applied_to_bill(bill, payment) for bill in bills)


def _approve_payment_record(payment, was_previously_approved: bool):
    if was_previously_approved:
        return False
    payment.status = "APPROVED"
    payment.save(update_fields=["status"])
    return True


def _notify_payment_approved(payment, method_display: str, was_previously_approved: bool, logger):
    from rentals.models import Notification
    from rentals.notification_copy import payment_approved_notification_copy

    if was_previously_approved:
        return

    try:
        title, message = payment_approved_notification_copy(
            payment_method=method_display,
            amount=payment.amount,
        )
        Notification.create_tenant_notification(
            title=title,
            message=message,
            notification_type="PAYMENT",
            tenant_user=payment.user,
        )
    except Exception as e:
        logger.exception(f"Failed to create payment approval notification: {e}")


def _apply_payment_to_bills(bills, payment, payment_type: str, approved_at, logger):
    for bill in bills:
        logger.info(f"Updating bill {bill.id}: rent={bill.base_rent}, water={bill.water_amount}, type={payment_type}")
        _apply_payment_to_bill(bill, payment, payment_type, approved_at)
        logger.info(f"Bill {bill.id} updated successfully: status={bill.status}, balance={bill.total_balance}")


def _refresh_future_water_carryovers(bills, payment_type: str, logger):
    if payment_type not in {"full", "water_only"}:
        return

    from water.models import WaterReading
    from water.services import (
        compute_water_reading,
        create_or_update_monthly_bill_from_reading,
        get_water_billing_settings_for_month,
        previous_unpaid_water_balance,
    )

    paid_water_bills = [bill for bill in bills if bill.water_paid > 0]
    for paid_bill in paid_water_bills:
        future_readings = WaterReading.objects.select_related("lease__unit").filter(
            lease=paid_bill.lease,
            reading_month__gt=paid_bill.billing_month,
        ).order_by("reading_month")

        for reading in future_readings:
            linked_bill = MonthlyBill.objects.filter(source_water_reading=reading).first()
            if linked_bill and linked_bill.water_paid > 0:
                continue

            billing_settings = get_water_billing_settings_for_month(reading.reading_month)
            month_readings = WaterReading.objects.filter(reading_month=reading.reading_month)
            total_month_consumption = sum((row.consumption for row in month_readings), Decimal("0.00"))
            compute_water_reading(
                reading,
                total_month_consumption=total_month_consumption,
                shared_pump_total=billing_settings.shared_pump_total,
                vat_percent=billing_settings.vat_percent,
                previous_unpaid_water_amount=previous_unpaid_water_balance(reading.lease, reading.reading_month),
            )
            reading.save()
            create_or_update_monthly_bill_from_reading(reading, force_update=True)
            logger.info(
                "Refreshed future water carry-over for bill %s reading %s: amount=%s",
                paid_bill.id,
                reading.id,
                reading.computed_amount,
            )


def reconcile_approved_payments_for_tenant(user):
    from payments.models import ManualPayment

    approved_payments = ManualPayment.objects.filter(
        user=user,
        status="APPROVED",
    ).exclude(
        payment_type="move_in",
    ).exclude(
        bill_ids="",
    ).only(
        "id",
        "user_id",
        "status",
        "payment_type",
        "reference_code",
        "amount",
        "bill_ids",
        "created_at",
    ).order_by("created_at")

    for payment in approved_payments:
        bill_ids = parse_bill_ids(payment.bill_ids)
        if not bill_ids:
            continue

        bills = MonthlyBill.objects.filter(
            pk__in=bill_ids,
            lease__tenant=user,
        )
        if bills and not all(_is_payment_applied_to_bill(bill, payment) for bill in bills):
            approve_manual_payment(payment)


@transaction.atomic
def set_bill_status(bill: MonthlyBill, *, status: str, payment_reference: str = "", paid_at=None) -> MonthlyBill:
    bill = MonthlyBill.objects.select_for_update().get(pk=bill.pk)
    ensure_bill_line_items_from_legacy(bill)

    if status == "PAID":
        paid_time = paid_at or timezone.now()
        for line in bill.line_items.all():
            line.paid_amount = line.amount
            line.paid_at = paid_time
            line.payment_reference = payment_reference
            line.refresh_status()
            line.save(update_fields=["paid_amount", "paid_at", "payment_reference", "status", "updated_at"])
    else:
        for line in bill.line_items.all():
            line.paid_amount = Decimal("0.00")
            line.paid_at = None
            line.payment_reference = ""
            line.refresh_status()
            line.save(update_fields=["paid_amount", "paid_at", "payment_reference", "status", "updated_at"])

    bill.payment_reference = payment_reference if status == "PAID" else ""
    bill.save(update_fields=["payment_reference"])
    return sync_monthly_bill_from_line_items(bill)


@transaction.atomic
def approve_manual_payment(payment):
    from payments.models import ManualPayment
    import logging

    logger = logging.getLogger(__name__)

    payment = ManualPayment.objects.select_for_update().select_related("user").get(pk=payment.pk)
    was_previously_approved = payment.status == "APPROVED"

    if _payment_is_move_in(payment):
        move_in_result = _approve_move_in_payment(payment, logger)
        if move_in_result is not None:
            return move_in_result

    bill_ids, bills = _load_bills_for_payment_approval(payment, logger)
    if not bill_ids:
        return payment

    if was_previously_approved and _payment_is_already_applied(payment, bills):
        logger.info(f"Payment {payment.id} already approved and applied")
        return payment

    approved_at = timezone.now()
    payment_type = getattr(payment, "payment_type", "full")
    _validate_payment_type(payment_type)

    payment_amount = Decimal(payment.amount or 0).quantize(Decimal("0.01"))
    if payment_amount <= 0:
        raise ValidationError("Payment amount must be greater than zero.")

    expected_amount = _expected_amount_for_payment_type(bills, payment_type)
    if not was_previously_approved and payment_amount != expected_amount:
        raise ValidationError(
            f"Payment amount â‚±{payment_amount:,.2f} does not match the selected "
            f"{payment_type.replace('_', ' ')} balance of â‚±{expected_amount:,.2f}."
        )

    invoice_lines = _build_invoice_lines(bills, payment_type)
    _approve_payment_record(payment, was_previously_approved)

    method_display = _payment_method_display(payment)
    _notify_payment_approved(payment, method_display, was_previously_approved, logger)
    _apply_payment_to_bills(bills, payment, payment_type, approved_at, logger)
    _refresh_future_water_carryovers(bills, payment_type, logger)
    create_and_send_invoice_for_payment(payment, bills, payment_type, approved_at, lines=invoice_lines, logger=logger)

    try:
        _generate_next_month_bill_if_needed(bills, approved_at)
    except Exception as e:
        logger.error(f"Failed to generate next month bill: {e}")

    return payment
@transaction.atomic
def reject_manual_payment(payment):
    from payments.models import ManualPayment
    from rentals.models import Notification
    from rentals.notification_copy import payment_declined_notification_copy
    import logging

    logger = logging.getLogger(__name__)
    payment = ManualPayment.objects.select_for_update().get(pk=payment.pk)
    if payment.status != "REJECTED":
        payment.status = "REJECTED"
        payment.save(update_fields=["status"])
        method_display = "GCash" if payment.payment_method == "GCASH" else "cash"
        title, message = payment_declined_notification_copy(
            payment_method=method_display,
            amount=payment.amount,
        )
        try:
            Notification.create_tenant_notification(
                title=title,
                message=message,
                notification_type="PAYMENT",
                tenant_user=payment.user,
            )
        except Exception as e:
            logger.exception(f"Failed to create payment rejection notification: {e}")
    return payment


@transaction.atomic
def remove_bill_references_from_payment_history(bill_id: int):
    from payments.models import ManualPayment

    for payment in ManualPayment.objects.select_for_update().exclude(bill_ids=""):
        current_ids = parse_bill_ids(payment.bill_ids)
        if bill_id not in current_ids:
            continue

        remaining_ids = [current_id for current_id in current_ids if current_id != bill_id]
        payment.bill_ids = serialize_bill_ids(remaining_ids)
        payment.save(update_fields=["bill_ids"])

