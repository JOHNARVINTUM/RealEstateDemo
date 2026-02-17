from datetime import date
from decimal import Decimal
import calendar

from billing.models import Payment

# 3% interest PER WEEK late
WEEKLY_LATE_INTEREST_RATE = Decimal("0.03")


def month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def add_months(d: date, months: int) -> date:
    """Return first-day-of-month advanced by N months."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, 1)


def months_between(start: date, end: date):
    """Yield first-day-of-month dates from start..end inclusive."""
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield date(y, m, 1)
        m += 1
        if m == 13:
            m = 1
            y += 1


def due_date_for_month(year: int, month: int, due_day: int) -> date:
    """Clamp due day to the last day of the month."""
    last_day = calendar.monthrange(year, month)[1]
    day = min(due_day, last_day)
    return date(year, month, day)


def compute_balance_for_month(lease, payment: Payment, today=None):
    """
    Weekly 3% interest strategy:
    - As soon as it's past due date: +3% (week 1)
    - After 7 days late: +3% again (week 2) -> total 6%
    - After 14 days: +3% again (week 3) -> total 9%
    etc.
    """

    if today is None:
        today = date.today()

    base_rent = lease.monthly_rent
    due_date = due_date_for_month(
        payment.billing_month.year,
        payment.billing_month.month,
        lease.due_day
    )

    amount_paid = payment.amount_paid
    status = payment.status

    is_late = False
    weeks_late = 0
    interest = Decimal("0.00")

    # late only if unpaid and today > due_date
    if status != "PAID" and today > due_date:
        is_late = True
        days_late = (today - due_date).days

        # week 1 starts immediately after due date
        weeks_late = (days_late // 7) + 1

        interest = (base_rent * WEEKLY_LATE_INTEREST_RATE * weeks_late).quantize(Decimal("0.01"))

    total_due = (base_rent + interest).quantize(Decimal("0.01"))
    balance = (total_due - amount_paid).quantize(Decimal("0.01"))

    return {
        "base_rent": base_rent,
        "due_date": due_date,
        "is_late": is_late,
        "weeks_late": weeks_late,
        "interest": interest,
        "total_due": total_due,
        "amount_paid": amount_paid,
        "balance": balance,
    }


def ensure_payments_since_move_in(lease, today=None):
    """
    Create Payment rows from lease.start_date month up to current month.
    """
    if lease is None:
        return
    if today is None:
        today = date.today()

    start = month_start(lease.start_date)
    end = month_start(today)

    for d in months_between(start, end):
        Payment.objects.get_or_create(
            lease=lease,
            billing_month=d,
            defaults={"status": "PENDING", "amount_paid": 0}
        )


def ensure_payments_up_to(lease, end_month: date):
    """
    Ensure Payment rows exist up to end_month inclusive (for advance pay preview/payment).
    """
    if lease is None:
        return

    start = month_start(lease.start_date)
    end = month_start(end_month)

    for d in months_between(start, end):
        Payment.objects.get_or_create(
            lease=lease,
            billing_month=d,
            defaults={"status": "PENDING", "amount_paid": 0}
        )
