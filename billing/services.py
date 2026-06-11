from datetime import date
from decimal import Decimal
import calendar

from django.db import transaction
from django.db.models import Sum
from django.core.exceptions import ValidationError
from django.utils import timezone

from billing.models import BillingInvoice, MonthlyBill
from water.models import WaterBill

# 3% flat late interest (BASE RENT ONLY for now)
WEEKLY_LATE_INTEREST_RATE = Decimal("0.03")


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
    Flat 3% strategy after a 2-week grace period:
    - 0 to 13 days late => no penalty yet
    - 14+ days late => +3% once
    - penalty does not keep increasing after that
    """
    if today <= due_date:
        return Decimal("0.00"), False, 0

    days_late = (today - due_date).days
    if days_late < 14:
        return Decimal("0.00"), True, 0

    interest = (charge_base * WEEKLY_LATE_INTEREST_RATE).quantize(Decimal("0.01"))
    return interest, True, 2


def expected_flat_late_interest_for_bill(bill: MonthlyBill, today: date | None = None) -> Decimal:
    today = today or timezone.localdate()
    if not bill.due_date:
        return Decimal("0.00")
    charge_base = (Decimal(bill.base_rent or 0) + Decimal(bill.parking_fee or 0)).quantize(Decimal("0.01"))
    interest, _, _ = compute_weekly_interest(charge_base, bill.due_date, today)
    return interest


def repair_inflated_unpaid_late_fees(*, today: date | None = None, dry_run: bool = False):
    """
    Correct legacy compounded late fees to the current flat 3% rule.

    Safety rules:
    - paid bills are never touched
    - only UNPAID / PARTIALLY_PAID bills are considered
    - only reduces interest when the stored value is higher than the expected flat value
    """
    today = today or timezone.localdate()
    current_month = today.replace(day=1)
    queryset = MonthlyBill.objects.filter(
        status__in=("UNPAID", "PARTIALLY_PAID"),
        billing_month__lte=current_month,
    ).select_related("lease", "lease__tenant", "lease__unit")

    repaired = []
    skipped = 0
    total_reduction = Decimal("0.00")

    for bill in queryset:
        old_interest = Decimal(bill.interest or 0).quantize(Decimal("0.01"))
        expected_interest = expected_flat_late_interest_for_bill(bill, today=today)
        if old_interest <= expected_interest:
            skipped += 1
            continue

        reduction = (old_interest - expected_interest).quantize(Decimal("0.01"))
        repaired.append({
            "bill_id": bill.id,
            "tenant_email": bill.lease.tenant.email if bill.lease and bill.lease.tenant else "",
            "unit": bill.lease.unit.number if bill.lease and bill.lease.unit else "",
            "billing_month": bill.billing_month,
            "old_interest": old_interest,
            "new_interest": expected_interest,
            "reduction": reduction,
        })
        total_reduction += reduction

        if not dry_run:
            bill.interest = expected_interest
            bill.total_due = (
                Decimal(bill.base_rent or 0)
                + Decimal(bill.water_amount or 0)
                + Decimal(bill.parking_fee or 0)
                + expected_interest
            ).quantize(Decimal("0.01"))
            bill.save(update_fields=["interest", "total_due"])

    return {
        "repaired_count": len(repaired),
        "skipped_count": skipped,
        "total_reduction": total_reduction.quantize(Decimal("0.01")),
        "repaired": repaired,
        "dry_run": dry_run,
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
        and lease.start_date <= today
        and (lease.end_date is None or lease.end_date >= today)
    )


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

    new_total = (bill.base_rent + bill.water_amount + bill.parking_fee + bill.interest).quantize(Decimal("0.01"))
    if bill.total_due != new_total:
        bill.total_due = new_total
        changed = True
    return changed


def _create_monthly_bill(lease, billing_month, due_date, base_rent, water_amount, parking_fee, interest, total_due):
    return MonthlyBill.objects.create(
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


def _ensure_bills_for_range(lease, end_month: date, today: date, *, apply_move_in: bool = False):
    if lease is None:
        return
    if not _lease_is_billable_today(lease, today):
        return

    start = month_start(lease.start_date)
    end = month_start(end_month)
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

    if apply_move_in:
        _apply_approved_move_in_payment_if_needed(lease, start)


def get_or_update_monthly_bill(lease, billing_month: date, today: date | None = None) -> MonthlyBill:
    """
    Creates/updates MonthlyBill totals for the month.
    - Interest applies to BASE RENT only (as requested).
    - Water is included in total_due (but no interest yet).
    """
    if today is None:
        today = date.today()

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

    # extra values useful in UI
    bill._is_late = is_late
    bill._weeks_late = weeks_late
    return bill


def ensure_bills_since_move_in(lease, today: date | None = None):
    if lease is None:
        return
    if today is None:
        today = date.today()
    _ensure_bills_for_range(lease, month_start(today), today, apply_move_in=True)


def _apply_approved_move_in_payment_if_needed(lease, start: date):
    first_bill = MonthlyBill.objects.filter(lease=lease, billing_month=start).first()
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
    first_bill.rent_paid = first_bill.base_rent
    first_bill.parking_paid = first_bill.parking_fee
    first_bill.rent_paid_at = paid_time
    first_bill.interest = Decimal("0.00")
    first_bill.total_due = (
        first_bill.base_rent + first_bill.water_amount + first_bill.parking_fee
    ).quantize(Decimal("0.01"))
    first_bill.status = "PAID" if first_bill.water_balance == 0 else "PARTIALLY_PAID"
    first_bill.paid_at = paid_time if first_bill.status == "PAID" else None
    first_bill.payment_reference = payment_reference
    first_bill.save(update_fields=[
        "rent_paid",
        "parking_paid",
        "rent_paid_at",
        "interest",
        "total_due",
        "status",
        "paid_at",
        "payment_reference",
    ])
    return first_bill


def ensure_bills_up_to(lease, end_month: date, today: date | None = None):
    """
     For advance payment previews/payments (creates future MonthlyBill rows).
      Allows up to 12 months advance to match the tenant payment UI.
     """
    if lease is None:
        return
    if today is None:
        today = date.today()
    if not _lease_is_billable_today(lease, today):
        return

    end = month_start(end_month)

    # Keep future generation bounded, but align it with the largest UI option.
    current_month = month_start(today)
    max_advance_months = 12
    max_date = add_months(current_month, max_advance_months)
    if end > max_date:
        end = max_date

    _ensure_bills_for_range(lease, end, today, apply_move_in=True)


def badge_for_bill(bill: MonthlyBill, today: date | None = None) -> str:
    """
    For the "Ongoing Billing" table badge.
    Returns: OVERDUE, DUE_TODAY, NEAR_DUE, UPCOMING
    """
    if today is None:
        today = date.today()

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
        return (
            bill.rent_paid >= bill.base_rent
            and bill.parking_paid >= bill.parking_fee
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

    return Lease.objects.filter(
        tenant=payment.user,
        status=Lease.STATUS_PENDING_PAYMENT,
    ).select_related("unit").first()


def _approve_move_in_payment(payment, logger):
    from rentals.services import LeaseActivationService

    try:
        pending_lease = _get_pending_move_in_lease(payment)
        if not pending_lease:
            return None

        logger.info(f"Found pending lease {pending_lease.id} for move-in payment {payment.id}")
        success, message = LeaseActivationService.activate_lease_after_payment(
            lease_id=pending_lease.id,
            payment_method=payment.payment_method,
            payment_reference=payment.reference_code,
            amount=payment.amount,
            existing_payment=payment,
        )
        if not success:
            logger.error(f"Lease activation failed: {message}")
            return None

        payment.status = "APPROVED"
        payment.save(update_fields=["status"])
        logger.info(f"Lease {pending_lease.id} activated via manual payment approval")
        return payment
    except Exception as e:
        logger.exception(f"Error checking lease activation for payment {payment.id}: {e}")
        return None


def _validate_payment_type(payment_type: str):
    if payment_type not in {"full", "rent_only", "water_only"}:
        raise ValidationError("Invalid payment type.")


def _expected_amount_for_payment_type(bills, payment_type: str) -> Decimal:
    expected_amount = Decimal("0.00")
    for bill in bills:
        if payment_type == "rent_only":
            expected_amount += bill.rent_balance + bill.parking_balance + bill.interest
        elif payment_type == "water_only":
            expected_amount += bill.water_balance
        else:
            expected_amount += bill.total_balance
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
        "rent_only": "Rent Only",
        "water_only": "Water Only",
        "move_in": "Move-in Payment",
    }.get(payment_type, "Payment")


def _invoice_number_for_payment(payment) -> str:
    return f"INV-PAY-{payment.id:06d}"


def _invoice_number_for_bill(bill) -> str:
    return f"INV-BILL-{bill.id:06d}"


def _build_invoice_line_for_bill(bill, payment_type: str):
    if payment_type == "rent_only":
        amount_paid = bill.rent_balance + bill.parking_balance + bill.interest
    elif payment_type == "water_only":
        amount_paid = bill.water_balance
    else:
        amount_paid = bill.total_balance

    return {
        "bill_id": bill.id,
        "billing_month": bill.billing_month.strftime("%B %Y"),
        "unit": getattr(bill.lease.unit, "number", ""),
        "rent_charge": _money(bill.base_rent),
        "water_charge": _money(bill.water_amount),
        "parking_charge": _money(bill.parking_fee),
        "late_fee": _money(bill.interest),
        "total_due_before_payment": _money(bill.total_balance),
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
    if payment_type == "rent_only":
        bill.rent_paid = max(bill.rent_paid, bill.base_rent)
        bill.parking_paid = max(bill.parking_paid, bill.parking_fee)
        bill.rent_paid_at = approved_at
        bill.payment_reference = payment.reference_code
        bill.interest = Decimal("0.00")
        bill.total_due = (bill.base_rent + bill.water_amount + bill.parking_fee).quantize(Decimal("0.01"))
    elif payment_type == "water_only":
        bill.water_paid = max(bill.water_paid, bill.water_amount)
        bill.water_paid_at = approved_at
        bill.payment_reference = payment.reference_code
    else:
        if bill.status == "PAID" and bill.payment_reference == payment.reference_code:
            return
        bill.rent_paid = max(bill.rent_paid, bill.base_rent)
        bill.water_paid = max(bill.water_paid, bill.water_amount)
        bill.parking_paid = max(bill.parking_paid, bill.parking_fee)
        bill.rent_paid_at = approved_at
        bill.water_paid_at = approved_at
        bill.payment_reference = payment.reference_code
        bill.interest = Decimal("0.00")
        bill.total_due = (bill.base_rent + bill.water_amount + bill.parking_fee).quantize(Decimal("0.01"))

    if bill.total_balance == 0:
        bill.status = "PAID"
        bill.paid_at = approved_at
    elif bill.rent_paid > 0 or bill.water_paid > 0:
        bill.status = "PARTIALLY_PAID"
        bill.paid_at = None
    else:
        bill.status = "UNPAID"
        bill.paid_at = None

    update_fields = [
        "rent_paid", "water_paid", "parking_paid", "rent_paid_at", "water_paid_at",
        "status", "paid_at", "payment_reference"
    ]
    if payment_type in {"full", "rent_only"}:
        update_fields += ["interest", "total_due"]
    bill.save(update_fields=update_fields)


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

    try:
        (Notification.create_tenant_notification if not was_previously_approved else (lambda **kwargs: None))(
            title="Payment Approved",
            message=f"Your {method_display} payment of ₱{payment.amount:,.2f} has been approved and your bills have been updated.",
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

    if status == "PAID":
        paid_time = paid_at or timezone.now()
        bill.rent_paid = bill.base_rent
        bill.water_paid = bill.water_amount
        bill.parking_paid = bill.parking_fee  # Set parking paid
        bill.rent_paid_at = paid_time
        bill.water_paid_at = paid_time
        bill.interest = Decimal("0.00")
        bill.total_due = (bill.base_rent + bill.water_amount + bill.parking_fee).quantize(Decimal("0.01"))
        bill.status = "PAID"
        bill.paid_at = paid_time
        bill.payment_reference = payment_reference
    else:
        bill.rent_paid = Decimal("0.00")
        bill.water_paid = Decimal("0.00")
        bill.parking_paid = Decimal("0.00")  # Reset parking paid
        bill.rent_paid_at = None
        bill.water_paid_at = None
        bill.status = "UNPAID"
        bill.paid_at = None
        bill.payment_reference = ""

    bill.save(update_fields=[
        "rent_paid", "water_paid", "parking_paid", "rent_paid_at", "water_paid_at",
        "interest", "total_due", "status", "paid_at", "payment_reference"
    ])
    return bill


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
            f"Payment amount ₱{payment_amount:,.2f} does not match the selected "
            f"{payment_type.replace('_', ' ')} balance of ₱{expected_amount:,.2f}."
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
    import logging
    logger = logging.getLogger(__name__)

    payment = ManualPayment.objects.select_for_update().get(pk=payment.pk)
    if payment.status != "REJECTED":
        payment.status = "REJECTED"
        payment.save(update_fields=["status"])
        
        # Notify tenant that payment was rejected
        try:
            method_display = "GCash" if payment.payment_method == "GCASH" else "Face-to-Face Cash"
            Notification.create_tenant_notification(
                title="Payment Declined",
                message=f"Your {method_display} payment request of ₱{payment.amount:,.2f} was declined. Please contact the admin for more information or submit a new payment.",
                notification_type='PAYMENT',
                tenant_user=payment.user
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
