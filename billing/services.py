from datetime import date
from decimal import Decimal
import calendar

from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from billing.models import MonthlyBill
from water.models import WaterBill

# 3% interest PER WEEK late (BASE RENT ONLY for now)
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


def compute_weekly_interest(base_rent: Decimal, due_date: date, today: date) -> tuple[Decimal, bool, int]:
    """
    Weekly 3% strategy (base rent only):
    - day after due_date => week 1 => +3%
    - 7 days late => week 2 => +6%
    - 14 days late => week 3 => +9%
    """
    if today <= due_date:
        return Decimal("0.00"), False, 0

    days_late = (today - due_date).days
    weeks_late = (days_late // 7) + 1
    interest = (base_rent * WEEKLY_LATE_INTEREST_RATE * weeks_late).quantize(Decimal("0.01"))
    return interest, True, weeks_late


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
    
    # Check if bill exists with system-computed water (from WaterReading)
    existing_bill = MonthlyBill.objects.filter(
        lease=lease, 
        billing_month=billing_month,
        water_computed_from_system=True
    ).first()
    
    if existing_bill:
        # Preserve system-computed water amount
        water_amount = existing_bill.water_amount
    else:
        # Get water from legacy system or 0
        water_amount = Decimal(get_water_amount_for_month(lease.unit, billing_month))

    parking_fee = Decimal(getattr(lease, 'parking_fee', 0)).quantize(Decimal("0.01"))
    interest, is_late, weeks_late = compute_weekly_interest(base_rent, due_date, today)
    total_due = (base_rent + water_amount + parking_fee + interest).quantize(Decimal("0.01"))

    bill, _ = MonthlyBill.objects.get_or_create(
        lease=lease,
        billing_month=billing_month,
        defaults={
            "due_date": due_date,
            "base_rent": base_rent,
            "water_amount": water_amount,
            "parking_fee": parking_fee,
            "interest": interest,
            "total_due": total_due,
            "status": "UNPAID",
            "bill_type": "RENT",
        },
    )

    # Never modify PAID bills - immutable for audit safety
    if bill.status == "PAID":
        bill._is_late = is_late
        bill._weeks_late = weeks_late
        return bill

    # keep totals fresh (water/interest can change)
    # BUT: don't overwrite water if it was computed from WaterReading system
    changed = False
    if bill.due_date != due_date:
        bill.due_date = due_date
        changed = True
    if bill.base_rent != base_rent:
        bill.base_rent = base_rent
        changed = True
    
    # Only update water_amount if NOT computed from WaterReading system
    # or if the bill's current water is 0 (fresh bill)
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

    # Recalculate total_due based on current values (respecting system-computed water)
    new_total = (bill.base_rent + bill.water_amount + bill.parking_fee + bill.interest).quantize(Decimal("0.01"))
    if bill.total_due != new_total:
        bill.total_due = new_total
        changed = True

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
    # Use date-based check: lease is active if start_date <= today and not ended
    if lease.start_date > today:
        return
    if lease.end_date and lease.end_date < today:
        return

    start = month_start(lease.start_date)
    end = month_start(today)

    for m in months_between(start, end):
        get_or_update_monthly_bill(lease, m, today=today)

    # Mark first month's bill as PAID if move-in payment was approved
    # (Move-in payment covers first month rent + parking; security deposit is held separately)
    first_bill = MonthlyBill.objects.filter(lease=lease, billing_month=start).first()
    if first_bill and first_bill.status != "PAID":
        from payments.models import ManualPayment
        has_approved_movein = ManualPayment.objects.filter(
            user=lease.tenant,
            payment_type="move_in",
            status="APPROVED",
        ).exists()
        if has_approved_movein:
            from django.utils import timezone as tz
            first_bill.rent_paid = first_bill.base_rent
            first_bill.parking_paid = first_bill.parking_fee
            first_bill.rent_paid_at = tz.now()
            first_bill.interest = Decimal("0.00")
            first_bill.total_due = (first_bill.base_rent + first_bill.water_amount + first_bill.parking_fee).quantize(Decimal("0.01"))
            first_bill.status = "PAID" if first_bill.water_balance == 0 else "PARTIALLY_PAID"
            first_bill.paid_at = tz.now() if first_bill.status == "PAID" else None
            first_bill.payment_reference = "MOVE-IN-PAYMENT"
            first_bill.save()


def ensure_bills_up_to(lease, end_month: date, today: date | None = None):
    """
    For advance payment previews/payments (creates future MonthlyBill rows).
    Allows up to 3 months advance to support thesis advance payment feature.
    """
    if lease is None:
        return
    if today is None:
        today = date.today()
    # Use date-based check: lease must have started
    if lease.start_date > today:
        return
    if lease.end_date and lease.end_date < today:
        return

    start = month_start(lease.start_date)
    end = month_start(end_month)

    # Limit to 3 months advance to prevent unlimited future generation
    current_month = month_start(today)
    max_advance_months = 3
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
    from rentals.models import Notification, Lease
    from rentals.services import LeaseActivationService
    import logging
    logger = logging.getLogger(__name__)

    payment = ManualPayment.objects.select_for_update().select_related("user").get(pk=payment.pk)
    was_previously_approved = payment.status == "APPROVED"

    # Check if this is a move-in payment with a pending lease
    # If so, use centralized activation service instead of normal approval
    if payment.payment_type == "move_in":
        try:
            # Find pending lease for this tenant
            pending_lease = Lease.objects.filter(
                tenant=payment.user,
                status=Lease.STATUS_PENDING_PAYMENT
            ).select_related('unit').first()
            
            if pending_lease:
                logger.info(f"Found pending lease {pending_lease.id} for move-in payment {payment.id}")
                
                # Use centralized activation service
                success, message = LeaseActivationService.activate_lease_after_payment(
                    lease_id=pending_lease.id,
                    payment_method=payment.payment_method,
                    payment_reference=payment.reference_code,
                    amount=payment.amount,
                )
                
                if success:
                    # Update payment status to approved
                    payment.status = "APPROVED"
                    payment.save(update_fields=["status"])
                    logger.info(f"Lease {pending_lease.id} activated via manual payment approval")
                    return payment
                else:
                    logger.error(f"Lease activation failed: {message}")
                    # Continue with normal approval as fallback
        except Exception as e:
            logger.exception(f"Error checking lease activation for payment {payment.id}: {e}")
            # Continue with normal approval

    bill_ids = parse_bill_ids(payment.bill_ids)
    logger.info(f"Approving payment {payment.id} for bills: {bill_ids}, user: {payment.user.id}")
    
    if not bill_ids:
        logger.warning(f"No bill_ids found for payment {payment.id}")
        return payment

    bills = MonthlyBill.objects.select_for_update().filter(
        pk__in=bill_ids,
        lease__tenant=payment.user,
    )
    
    logger.info(f"Found {bills.count()} bills to update")
    if bills.count() != len(bill_ids):
        raise ValidationError("Some selected bills were not found or do not belong to this tenant.")
    if was_previously_approved and all(_is_payment_applied_to_bill(bill, payment) for bill in bills):
        logger.info(f"Payment {payment.id} already approved and applied")
        return payment

    approved_at = timezone.now()
    payment_type = getattr(payment, 'payment_type', 'full')  # Default to full if not set
    if payment_type not in {"full", "rent_only", "water_only"}:
        raise ValidationError("Invalid payment type.")
    
    payment_amount = Decimal(payment.amount or 0).quantize(Decimal("0.01"))
    if payment_amount <= 0:
        raise ValidationError("Payment amount must be greater than zero.")
    
    expected_amount = Decimal("0.00")
    for bill in bills:
        if payment_type == "rent_only":
            expected_amount += bill.rent_balance + bill.parking_balance
        elif payment_type == "water_only":
            expected_amount += bill.water_balance
        else:
            expected_amount += bill.total_balance
    expected_amount = expected_amount.quantize(Decimal("0.01"))
    
    if not was_previously_approved and payment_amount != expected_amount:
        raise ValidationError(
            f"Payment amount ₱{payment_amount:,.2f} does not match the selected "
            f"{payment_type.replace('_', ' ')} balance of ₱{expected_amount:,.2f}."
        )
    
    if not was_previously_approved:
        payment.status = "APPROVED"
        payment.save(update_fields=["status"])
    
    # Determine correct payment method display
    if payment.payment_method == "GCASH":
        method_display = "GCash"
    elif payment.payment_method == "PAYMONGO":
        method_display = "PayMongo"
    else:
        method_display = "Face-to-Face Cash"
    
    try:
        (Notification.create_tenant_notification if not was_previously_approved else (lambda **kwargs: None))(
            title="Payment Approved",
            message=f"Your {method_display} payment of ₱{payment.amount:,.2f} has been approved and your bills have been updated.",
            notification_type='PAYMENT',
            tenant_user=payment.user
        )
    except Exception as e:
        logger.exception(f"Failed to create payment approval notification: {e}")
    
    for bill in bills:
        logger.info(f"Updating bill {bill.id}: rent={bill.base_rent}, water={bill.water_amount}, type={payment_type}")

        # Allocate payment based on payment_type
        # Use max() to preserve existing partial payments safely
        if payment_type == "rent_only":
            bill.rent_paid = max(bill.rent_paid, bill.base_rent)
            bill.parking_paid = max(bill.parking_paid, bill.parking_fee)  # Parking included in rent
            bill.rent_paid_at = approved_at
            bill.payment_reference = payment.reference_code

        elif payment_type == "water_only":
            bill.water_paid = max(bill.water_paid, bill.water_amount)
            bill.water_paid_at = approved_at
            bill.payment_reference = payment.reference_code

        else:
            # Full payment
            if bill.status == "PAID" and bill.payment_reference == payment.reference_code:
                logger.info(f"Bill {bill.id} already paid with same reference, skipping")
                continue
            bill.rent_paid = max(bill.rent_paid, bill.base_rent)
            bill.water_paid = max(bill.water_paid, bill.water_amount)
            bill.parking_paid = max(bill.parking_paid, bill.parking_fee)  # Include parking
            bill.rent_paid_at = approved_at
            bill.water_paid_at = approved_at
            bill.payment_reference = payment.reference_code
            # Zero out interest - it is included in the full payment amount
            bill.interest = Decimal("0.00")
            bill.total_due = (bill.base_rent + bill.water_amount + bill.parking_fee).quantize(Decimal("0.01"))

        # Determine status using total_balance as source of truth
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
        logger.info(f"Bill {bill.id} updated successfully: status={bill.status}, balance={bill.total_balance}")
    
    # Generate next month's bill if current bill is fully paid
    # This ensures tenant always has a bill to pay for the upcoming month
    if bills and all(b.status == "PAID" for b in bills):
        try:
            # Get the latest paid bill to determine next month
            latest_paid_bill = max(bills, key=lambda b: b.billing_month)
            next_month = add_months(latest_paid_bill.billing_month, 1)
            
            # Create next month's bill if it doesn't exist
            next_bill_exists = MonthlyBill.objects.filter(
                lease=latest_paid_bill.lease,
                billing_month=next_month
            ).exists()
            
            if not next_bill_exists:
                from rentals.models import Lease
                lease = latest_paid_bill.lease
                get_or_update_monthly_bill(lease, next_month, today=approved_at.date())
                logger.info(f"Generated next month bill for {next_month} after payment approval")
        except Exception as e:
            logger.error(f"Failed to generate next month bill: {e}")
            # Don't fail the payment approval if bill generation fails

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
