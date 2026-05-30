from datetime import date
from decimal import Decimal
import calendar

from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from billing.models import MonthlyBill
from water.models import WaterBill

# 3% flat late interest (BASE RENT ONLY for now)
WEEKLY_LATE_INTEREST_RATE = Decimal("0.03")


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
    if not _lease_is_billable_today(lease, today):
        return

    start = month_start(lease.start_date)
    end = month_start(today)

    for m in months_between(start, end):
        get_or_update_monthly_bill(lease, m, today=today)

    # Mark first month's bill as settled for rent + parking if move-in payment was approved.
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

    start = month_start(lease.start_date)
    end = month_start(end_month)

    # Keep future generation bounded, but align it with the largest UI option.
    current_month = month_start(today)
    max_advance_months = 12
    max_date = add_months(current_month, max_advance_months)
    if end > max_date:
        end = max_date

    for m in months_between(start, end):
        get_or_update_monthly_bill(lease, m, today=today)


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

    if payment_type == "rent_only":
        return (
            bill.payment_reference == payment_reference
            and bill.rent_paid >= bill.base_rent
            and bill.parking_paid >= bill.parking_fee
        )
    if payment_type == "water_only":
        return (
            bill.payment_reference == payment_reference
            and bill.water_paid >= bill.water_amount
        )
    return (
        bill.payment_reference == payment_reference
        and bill.status == "PAID"
    )


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
            expected_amount += bill.rent_balance + bill.parking_balance
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


def _apply_payment_to_bill(bill, payment, payment_type: str, approved_at):
    if payment_type == "rent_only":
        bill.rent_paid = max(bill.rent_paid, bill.base_rent)
        bill.parking_paid = max(bill.parking_paid, bill.parking_fee)
        bill.rent_paid_at = approved_at
        bill.payment_reference = payment.reference_code
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
    if payment_type == "full":
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


@transaction.atomic
def reconcile_approved_payments_for_tenant(user):
    from payments.models import ManualPayment

    approved_payments = ManualPayment.objects.select_for_update().filter(
        user=user,
        status="APPROVED",
    ).exclude(payment_type="move_in").order_by("created_at")

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

    _approve_payment_record(payment, was_previously_approved)

    method_display = _payment_method_display(payment)
    _notify_payment_approved(payment, method_display, was_previously_approved, logger)
    _apply_payment_to_bills(bills, payment, payment_type, approved_at, logger)

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
