from datetime import date
from decimal import Decimal
import calendar

LATE_INTEREST_RATE = Decimal("0.03")

def month_start(d: date) -> date:
    return date(d.year, d.month, 1)

def due_date_for_month(year: int, month: int, due_day: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    day = min(due_day, last_day)
    return date(year, month, day)

def compute_balance_for_lease(lease, payment_for_month=None, today=None):
    """
    Returns dict:
      base_rent, is_late, interest, total_due, amount_paid, balance
    """
    if today is None:
        today = date.today()

    base_rent = lease.monthly_rent
    due_date = due_date_for_month(today.year, today.month, lease.due_day)

    amount_paid = Decimal("0.00")
    status = "PENDING"
    if payment_for_month:
        amount_paid = payment_for_month.amount_paid
        status = payment_for_month.status

    # late if past due and not paid fully
    is_late = (today > due_date) and (status != "PAID")
    interest = (base_rent * LATE_INTEREST_RATE).quantize(Decimal("0.01")) if is_late else Decimal("0.00")

    total_due = (base_rent + interest).quantize(Decimal("0.01"))
    balance = (total_due - amount_paid).quantize(Decimal("0.01"))

    return {
        "base_rent": base_rent,
        "due_date": due_date,
        "is_late": is_late,
        "interest": interest,
        "total_due": total_due,
        "amount_paid": amount_paid,
        "balance": balance,
    }
