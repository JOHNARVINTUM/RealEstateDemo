from decimal import Decimal

from billing.models import MonthlyBill
from billing.services import parse_bill_ids


def _money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def rent_and_parking_total_for_payment(payment) -> Decimal | None:
    """
    Return the amount that would have been charged for a rent-only advance
    payment across the bills referenced by the payment.

    This intentionally excludes water and interest so we can identify old
    advance-payment records that were mislabeled as full payments.
    """
    bill_ids = parse_bill_ids(payment.bill_ids)
    if not bill_ids:
        return None

    bills = list(
        MonthlyBill.objects.filter(
            pk__in=bill_ids,
            lease__tenant=payment.user,
        )
    )
    if len(bills) != len(bill_ids):
        return None

    total = sum(
        (_money(bill.base_rent) + _money(bill.parking_fee))
        for bill in bills
    )
    return _money(total)


def should_relabel_full_payment_as_rent_only(payment) -> bool:
    """
    Identify historical advance payments that were stored as full payments.

    The safest signal available in the current schema is that the stored amount
    matches rent plus parking for the referenced bills, which means water and
    interest were not part of the payment.
    """
    if getattr(payment, "payment_type", "") != "full":
        return False
    if getattr(payment, "payment_type", "") == "move_in":
        return False

    expected = rent_and_parking_total_for_payment(payment)
    if expected is None:
        return False

    return _money(payment.amount) == expected

