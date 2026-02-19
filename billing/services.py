from datetime import date
from decimal import Decimal
import calendar

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
    day = min(due_day, last_day)
    return date(year, month, day)


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
    base_rent = Decimal(lease.monthly_rent)
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
