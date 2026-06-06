from datetime import date

import pandas as pd
from django.utils import timezone

from billing.models import MonthlyBill
from rentals.models import Lease

FEATURE_COLUMNS = [
    "monthly_rent",
    "water_amount",
    "total_due",
    "due_day",
    "lease_age_months",
    "previous_late_count_3m",
    "previous_late_count_6m",
    "previous_unpaid_count_3m",
    "previous_unpaid_count_6m",
    "avg_delay_3m",
    "avg_delay_6m",
    "max_delay_6m",
    "partial_payment_count_6m",
    "payment_rate_6m",
    "on_time_rate_6m",
    "months_with_bill_history",
    "unit_floor_level",
    "unit_size_sqm",
    "unit_type_STUDIO",
    "unit_type_1BR",
    "unit_type_2BR",
    "unit_type_3BR",
    "unit_type_PENTHOUSE",
]

UNIT_TYPES = ["STUDIO", "1BR", "2BR", "3BR", "PENTHOUSE"]


def month_diff(start, end):
    return max(0, (end.year - start.year) * 12 + (end.month - start.month))


def risk_probability_to_level(probability):
    if probability is None:
        return ""
    if probability < 0.30:
        return "LOW"
    if probability < 0.66:
        return "MEDIUM"
    return "HIGH"


def bill_late_or_unpaid(bill, as_of=None):
    as_of = as_of or timezone.now().date()
    if bill.status == "PAID" and bill.paid_at and bill.due_date:
        return bill.paid_at.date() > bill.due_date
    if bill.status != "PAID" and bill.due_date:
        return as_of > bill.due_date
    return False


def bill_delay_days(bill, as_of=None):
    as_of = as_of or timezone.now().date()
    if not bill.due_date:
        return 0
    if bill.status == "PAID" and bill.paid_at:
        return max(0, (bill.paid_at.date() - bill.due_date).days)
    if bill.status != "PAID":
        return max(0, (as_of - bill.due_date).days)
    return 0


def build_features_for_bill(lease, bill):
    historical_bills = list(
        MonthlyBill.objects.filter(
            lease=lease,
            billing_month__lt=bill.billing_month,
        ).order_by("-billing_month")[:6]
    )
    recent3 = historical_bills[:3]
    recent6 = historical_bills[:6]

    delays3 = [bill_delay_days(b, as_of=bill.billing_month) for b in recent3]
    delays6 = [bill_delay_days(b, as_of=bill.billing_month) for b in recent6]
    late3 = sum(1 for b in recent3 if bill_late_or_unpaid(b, as_of=bill.billing_month))
    late6 = sum(1 for b in recent6 if bill_late_or_unpaid(b, as_of=bill.billing_month))
    unpaid3 = sum(1 for b in recent3 if b.status != "PAID")
    unpaid6 = sum(1 for b in recent6 if b.status != "PAID")
    partial6 = sum(1 for b in recent6 if b.status == "PARTIALLY_PAID" or b.rent_paid > 0 or b.water_paid > 0)
    paid6 = sum(1 for b in recent6 if b.status == "PAID")
    on_time6 = sum(1 for b in recent6 if b.status == "PAID" and b.paid_at and b.due_date and b.paid_at.date() <= b.due_date)
    hist_count = len(recent6)
    unit = lease.unit

    row = {
        "monthly_rent": float(bill.base_rent or lease.monthly_rent or 0),
        "water_amount": float(bill.water_amount or 0),
        "total_due": float(bill.total_due or 0),
        "due_day": int(lease.due_day or 0),
        "lease_age_months": month_diff(lease.start_date, bill.billing_month),
        "previous_late_count_3m": late3,
        "previous_late_count_6m": late6,
        "previous_unpaid_count_3m": unpaid3,
        "previous_unpaid_count_6m": unpaid6,
        "avg_delay_3m": round(sum(delays3) / len(delays3), 2) if delays3 else 0,
        "avg_delay_6m": round(sum(delays6) / len(delays6), 2) if delays6 else 0,
        "max_delay_6m": max(delays6) if delays6 else 0,
        "partial_payment_count_6m": partial6,
        "payment_rate_6m": round(paid6 / hist_count, 3) if hist_count else 0,
        "on_time_rate_6m": round(on_time6 / hist_count, 3) if hist_count else 0,
        "months_with_bill_history": hist_count,
        "unit_floor_level": int(unit.floor_level or 0),
        "unit_size_sqm": float(unit.size_sqm or 0),
    }
    for unit_type in UNIT_TYPES:
        row[f"unit_type_{unit_type}"] = 1 if unit.unit_type == unit_type else 0
    return row


def build_training_dataset(min_history_months=2):
    rows = []
    labels = []
    meta = []
    current_month = timezone.now().date().replace(day=1)
    bills = MonthlyBill.objects.select_related(
        "lease", "lease__tenant", "lease__unit"
    ).filter(billing_month__lte=current_month).order_by("billing_month")
    for bill in bills:
        lease = bill.lease
        prior_count = MonthlyBill.objects.filter(lease=lease, billing_month__lt=bill.billing_month).count()
        if prior_count < min_history_months:
            continue
        rows.append(build_features_for_bill(lease, bill))
        labels.append(1 if bill_late_or_unpaid(bill) else 0)
        meta.append({
            "tenant_id": lease.tenant_id,
            "bill_id": bill.id,
            "billing_month": bill.billing_month.isoformat(),
        })
    X = pd.DataFrame(rows, columns=FEATURE_COLUMNS).fillna(0)
    y = pd.Series(labels, name="late_or_unpaid")
    return X, y, meta


def build_prediction_features_for_tenant(tenant):
    lease = Lease.objects.filter(tenant=tenant, is_active=True).select_related("unit").first()
    if not lease:
        return None
    current_month = timezone.now().date().replace(day=1)
    latest_bill = MonthlyBill.objects.filter(
        lease=lease,
        billing_month__lte=current_month,
    ).order_by("-billing_month").first()
    if latest_bill:
        row = build_features_for_bill(lease, latest_bill)
        row["monthly_rent"] = float(latest_bill.base_rent or lease.monthly_rent or 0)
        row["water_amount"] = float(latest_bill.water_amount or 0)
        row["total_due"] = float(latest_bill.total_due or 0)
    else:
        current_month = timezone.now().date().replace(day=1)
        dummy = MonthlyBill(
            lease=lease,
            billing_month=current_month,
            due_date=date(current_month.year, current_month.month, min(lease.due_day, 28)),
            base_rent=lease.monthly_rent,
            water_amount=0,
            total_due=lease.monthly_rent,
        )
        row = build_features_for_bill(lease, dummy)
    return pd.DataFrame([row], columns=FEATURE_COLUMNS).fillna(0)
