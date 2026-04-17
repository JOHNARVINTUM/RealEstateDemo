from datetime import date
from decimal import Decimal
import calendar

from django.db import transaction
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
    water_amount = Decimal(get_water_amount_for_month(lease.unit, billing_month))

    interest, is_late, weeks_late = compute_weekly_interest(base_rent, due_date, today)
    total_due = (base_rent + water_amount + interest).quantize(Decimal("0.01"))

    bill, _ = MonthlyBill.objects.get_or_create(
        lease=lease,
        billing_month=billing_month,
        defaults={
            "due_date": due_date,
            "base_rent": base_rent,
            "water_amount": water_amount,
            "interest": interest,
            "total_due": total_due,
            "status": "UNPAID",
        },
    )

    # keep totals fresh (water/interest can change)
    changed = False
    if bill.due_date != due_date:
        bill.due_date = due_date
        changed = True
    if bill.base_rent != base_rent:
        bill.base_rent = base_rent
        changed = True
    if bill.water_amount != water_amount:
        bill.water_amount = water_amount
        changed = True
    if bill.interest != interest:
        bill.interest = interest
        changed = True
    if bill.total_due != total_due:
        bill.total_due = total_due
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
    if not getattr(lease, "is_active", True):
        return
    if today is None:
        today = date.today()

    start = month_start(lease.start_date)
    end = month_start(today)

    for m in months_between(start, end):
        get_or_update_monthly_bill(lease, m, today=today)


def ensure_bills_up_to(lease, end_month: date, today: date | None = None):
    """
    For advance payment previews/payments (creates future MonthlyBill rows).
    """
    if lease is None:
        return
    if not getattr(lease, "is_active", True):
        return
    if today is None:
        today = date.today()

    start = month_start(lease.start_date)
    end = month_start(end_month)

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


@transaction.atomic
def set_bill_status(bill: MonthlyBill, *, status: str, payment_reference: str = "", paid_at=None) -> MonthlyBill:
    bill = MonthlyBill.objects.select_for_update().get(pk=bill.pk)

    if status == "PAID":
        bill.status = "PAID"
        bill.paid_at = paid_at or timezone.now()
        bill.payment_reference = payment_reference
    else:
        bill.status = "UNPAID"
        bill.paid_at = None
        bill.payment_reference = ""

    bill.save(update_fields=["status", "paid_at", "payment_reference"])
    return bill


@transaction.atomic
def approve_manual_payment(payment):
    from payments.models import ManualPayment

    payment = ManualPayment.objects.select_for_update().select_related("user").get(pk=payment.pk)
    if payment.status == "APPROVED":
        return payment

    payment.status = "APPROVED"
    payment.save(update_fields=["status"])

    bill_ids = parse_bill_ids(payment.bill_ids)
    if not bill_ids:
        return payment

    bills = MonthlyBill.objects.select_for_update().filter(
        pk__in=bill_ids,
        lease__tenant=payment.user,
    )

    approved_at = timezone.now()
    for bill in bills:
        if bill.status == "PAID" and bill.payment_reference == payment.reference_code:
            continue
        bill.status = "PAID"
        bill.paid_at = approved_at
        bill.payment_reference = payment.reference_code
        bill.save(update_fields=["status", "paid_at", "payment_reference"])

    return payment


@transaction.atomic
def reject_manual_payment(payment):
    from payments.models import ManualPayment

    payment = ManualPayment.objects.select_for_update().get(pk=payment.pk)
    if payment.status != "REJECTED":
        payment.status = "REJECTED"
        payment.save(update_fields=["status"])
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
