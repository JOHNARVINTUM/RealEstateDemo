from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import connection, models
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from announcements.models import Announcement
from billing.models import MonthlyBill
from billing.services import (
    add_months,
    due_date_for_month,
    reconcile_approved_payments_for_tenant,
    ensure_bills_since_move_in,
    ensure_bills_up_to,
    get_or_update_monthly_bill,
    month_start,
    parse_bill_ids,
)
from payments.models import ManualPayment
from payments.views import manual_gcash_payment
from accounts.decorators import tenant_required

from .models import Lease, Notification, TenantProfile, Unit

MAX_ADVANCE_PAYMENT_MONTHS = 6


def _unpaid_paymongo_checkout_filter():
    return Q(payment_method="PAYMONGO", status="PENDING", paymongo_payment_id="")


def _remove_cancelled_paymongo_checkouts(user):
    return ManualPayment.objects.filter(user=user).filter(
        _unpaid_paymongo_checkout_filter()
    ).delete()[0]


# Temporary inline form to resolve import issue
class UnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        fields = [
            'number', 'unit_type', 'floor_level', 'size_sqm', 
            'monthly_rent', 'status', 'description', 'amenities'
        ]
        widgets = {
            'number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 101, A-201'
            }),
            'unit_type': forms.Select(attrs={
                'class': 'form-control'
            }),
            'floor_level': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '50'
            }),
            'size_sqm': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '10'
            }),
            'monthly_rent': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '1000'
            }),
            'status': forms.Select(attrs={
                'class': 'form-control'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': '3',
                'placeholder': 'Describe unit features, location, etc.'
            }),
            'amenities': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': '2',
                'placeholder': 'e.g., Air Conditioning, WiFi, Parking, Swimming Pool'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': field.widget.attrs.get('class', '') + ' tenant-form-input'})
            if field.required:
                field.widget.attrs.update({'required': 'required'})

    def clean_number(self):
        number = self.cleaned_data.get('number')
        if number:
            return number.upper().strip()
        return number

    def clean_monthly_rent(self):
        rent = self.cleaned_data.get('monthly_rent')
        if rent and rent < 1000:
            raise forms.ValidationError('Monthly rent must be at least ₱1,000')
        return rent

    def clean_size_sqm(self):
        size = self.cleaned_data.get('size_sqm')
        if size and size < 10:
            raise forms.ValidationError('Unit size must be at least 10 sqm')
        return size

    def clean_amenities(self):
        amenities = self.cleaned_data.get('amenities')
        if amenities:
            # Clean up the amenities string
            amenities_list = [item.strip() for item in amenities.split(',') if item.strip()]
            return ', '.join(amenities_list)
        return amenities


def _tenant_lease_options(user, today):
    return Lease.objects.filter(
        tenant=user,
    ).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=today)
    ).filter(
        Q(status=Lease.STATUS_ACTIVE) | Q(status=Lease.STATUS_PENDING_PAYMENT)
    ).select_related("unit").order_by('-start_date')


def _selected_dashboard_lease(request, all_active_leases, today):
    selected_lease_id = request.GET.get('lease_id')
    if selected_lease_id:
        return all_active_leases.filter(pk=selected_lease_id).first()

    lease = all_active_leases.filter(start_date__lte=today).first()
    return lease or all_active_leases.first()


def _empty_dashboard_billing_context():
    return {
        "current_balance": None,
        "show_paid_hero": False,
        "paid_hero_month": None,
        "total_balance_due": None,
        "next_due_date": None,
        "next_billing_month": None,
        "next_bill_preview": None,
        "partial_bill_alert": None,
    }


def _bill_balance_summary(all_bills):
    total_unpaid_rent = Decimal("0.00")
    total_unpaid_water = Decimal("0.00")
    actual_balance_candidate = None
    actual_balance_index = None

    for index, bill in enumerate(all_bills):
        if bill.rent_balance > 0:
            total_unpaid_rent += bill.rent_balance
        if bill.water_balance > 0:
            total_unpaid_water += bill.water_balance
        if actual_balance_candidate is None and bill.total_balance > 0:
            actual_balance_candidate = bill
            actual_balance_index = index

    return {
        "total_balance_due": total_unpaid_rent + total_unpaid_water,
        "actual_balance_candidate": actual_balance_candidate,
        "actual_balance_index": actual_balance_index,
    }


def _should_show_due_card(actual_balance, today, today_start):
    if not actual_balance:
        return False

    return actual_balance.billing_month <= today_start


def _next_bill_after_current(lease, all_bills, current_balance, actual_balance_index):
    next_bill = (
        all_bills[actual_balance_index + 1]
        if actual_balance_index is not None and actual_balance_index + 1 < len(all_bills)
        else None
    )
    if next_bill:
        return next_bill

    next_month_date = add_months(current_balance.billing_month, 1)
    return get_or_update_monthly_bill(lease, next_month_date)


def _next_generated_bill_preview(lease, today_start):
    next_month = add_months(today_start, 1)
    ensure_bills_up_to(lease, next_month)
    return MonthlyBill.objects.filter(lease=lease, billing_month=next_month).first()


def _dashboard_billing_context(user, lease, today):
    context = _empty_dashboard_billing_context()
    if not lease or lease.status != Lease.STATUS_ACTIVE:
        return context

    reconcile_approved_payments_for_tenant(user)
    ensure_bills_since_move_in(lease)

    all_bills = list(MonthlyBill.objects.filter(lease=lease).order_by("billing_month"))
    context["partial_bill_alert"] = next(
        (
            bill
            for bill in all_bills
            if bill.status == "PARTIALLY_PAID" and bill.total_balance > 0
        ),
        None,
    )
    summary = _bill_balance_summary(all_bills)
    actual_balance_candidate = summary["actual_balance_candidate"]
    actual_balance_index = summary["actual_balance_index"]
    actual_balance = actual_balance_candidate

    today_start = month_start(today)
    context["total_balance_due"] = summary["total_balance_due"]

    if actual_balance and _should_show_due_card(actual_balance, today, today_start):
        context["current_balance"] = actual_balance
        next_bill = _next_bill_after_current(lease, all_bills, actual_balance, actual_balance_index)
    elif actual_balance:
        context["show_paid_hero"] = True
        context["paid_hero_month"] = today_start
        next_bill = actual_balance
    else:
        context["show_paid_hero"] = True
        context["paid_hero_month"] = today_start
        next_bill = _next_generated_bill_preview(lease, today_start)

    if next_bill:
        context["next_bill_preview"] = next_bill
        context["next_billing_month"] = next_bill.billing_month
        context["next_due_date"] = next_bill.due_date
        next_due_in_days = (next_bill.due_date - today).days if next_bill.due_date else None
        context["next_due_in_days"] = next_due_in_days
        if next_due_in_days is None:
            context["next_due_label"] = "Due Date"
        elif next_due_in_days > 1:
            context["next_due_label"] = f"Due in {next_due_in_days} days"
        elif next_due_in_days == 1:
            context["next_due_label"] = "Due in 1 day"
        elif next_due_in_days == 0:
            context["next_due_label"] = "Due today"
        else:
            context["next_due_label"] = "Due Date"

    return context


def _recent_payment_context(user):
    recent_payments = ManualPayment.objects.filter(user=user).exclude(
        _unpaid_paymongo_checkout_filter()
    ).order_by("-created_at")[:5]
    approved_move_in_payment = (
        ManualPayment.objects.filter(user=user, payment_type="move_in", status="APPROVED")
        .order_by("-created_at")
        .first()
    )
    move_in_payment = approved_move_in_payment or (
        ManualPayment.objects.filter(user=user, payment_type="move_in")
        .order_by("-created_at")
        .first()
    )
    return {
        "recent_payments": recent_payments,
        "move_in_payment": move_in_payment,
        "has_pending_payment": ManualPayment.objects.filter(user=user, status="PENDING").exclude(
            _unpaid_paymongo_checkout_filter()
        ).exists(),
    }


def _current_tenant_lease(user, today):
    return Lease.objects.filter(
        tenant=user,
        start_date__lte=today,
    ).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=today)
    ).select_related("unit").order_by('-start_date').first()


def _tenant_billing_filters(request):
    return request.GET.get("billing_month", "").strip()


def _filtered_bills_for_statement(lease, billing_month_filter):
    bills_query = MonthlyBill.objects.filter(
        lease=lease
    ).exclude(status="PAID").select_related("source_water_reading").order_by("-billing_month")
    if lease.end_date:
        bills_query = bills_query.filter(billing_month__lte=month_start(lease.end_date))

    if billing_month_filter:
        try:
            selected_month = date.fromisoformat(billing_month_filter)
        except ValueError:
            selected_month = None
        if selected_month:
            bills_query = bills_query.filter(
                billing_month__year=selected_month.year,
                billing_month__month=selected_month.month,
            )

    filtered_bills = list(
        bills_query.filter(status__in=["UNPAID", "PARTIALLY_PAID"]).order_by("billing_month")
    )
    return filtered_bills


def _selected_contract_bill(lease, billing_month_filter):
    if not billing_month_filter:
        return None

    try:
        selected_month = date.fromisoformat(billing_month_filter)
    except ValueError:
        return None

    bill = MonthlyBill.objects.filter(
        lease=lease,
        billing_month__year=selected_month.year,
        billing_month__month=selected_month.month,
    ).select_related("source_water_reading").first()
    if bill and lease.end_date and month_start(bill.billing_month) > month_start(lease.end_date):
        return None

    return bill


def _bill_display_status(bill, today):
    if bill.due_date < today:
        return "OVERDUE"
    if bill.due_date == today:
        return "DUE_TODAY"
    return "UPCOMING"


def _ongoing_billing_rows(refreshed_bills, today):
    rows = []
    for bill in refreshed_bills:
        display_status = _bill_display_status(bill, today)
        if display_status == "UPCOMING":
            continue

        rows.append({
            "month_label": bill.billing_month.strftime("%B %Y"),
            "rent": bill.base_rent,
            "water": bill.water_amount,
            "parking": bill.parking_fee,
            "maintenance": bill.maintenance_amount,
            "water_reading": bill.source_water_reading if bill.source_water_reading else None,
            "penalty": bill.interest,
            "total": bill.total_due,
            "due_date": bill.due_date,
            "status": display_status,
        })
    return rows


def _approved_payment_transactions(user, lease=None):
    approved_payments = ManualPayment.objects.filter(
        user=user,
        status="APPROVED",
    ).only(
        "id",
        "amount",
        "bill_ids",
        "reference_code",
        "created_at",
        "payment_method",
        "payment_type",
        "paid_via",
    ).order_by("-created_at")

    payment_bill_ids = set()
    payment_bill_map = {}
    for payment in approved_payments:
        bill_id_list = parse_bill_ids(payment.bill_ids)
        if not bill_id_list:
            continue
        payment_bill_ids.update(bill_id_list)
        payment_bill_map[payment.id] = bill_id_list

    bills_query = MonthlyBill.objects.filter(id__in=payment_bill_ids)
    if lease:
        bills_query = bills_query.filter(lease=lease)
        if lease.end_date:
            bills_query = bills_query.filter(billing_month__lte=month_start(lease.end_date))
    bills_by_id = {bill.id: bill for bill in bills_query}

    transactions = []
    for payment in approved_payments:
        bill_id_list = payment_bill_map.get(payment.id)
        if not bill_id_list:
            continue

        bills_paid = [bills_by_id[bill_id] for bill_id in bill_id_list if bill_id in bills_by_id]
        if not bills_paid:
            continue
        total_amount = payment.amount if payment.amount and payment.amount > 0 else sum(
            (bill.total_due or Decimal("0.00")) for bill in bills_paid
        )
        bill_month_labels = [
            bill.billing_month.strftime("%B %Y")
            for bill in sorted(bills_paid, key=lambda item: item.billing_month)
        ]
        transactions.append({
            "paid_at": payment.created_at,
            "reference": payment.reference_code,
            "payment_method": payment.get_payment_method_display(),
            "payment_type": payment.get_payment_type_display(),
            "paid_via": (payment.paid_via or "").replace("_", " ").title(),
            "months_paid": len(bills_paid),
            "bill_months": bill_month_labels,
            "bill_months_label": ", ".join(bill_month_labels),
            "total_amount": total_amount,
        })
    return transactions


def _monthly_status_rows(lease, today=None):
    if today is None:
        today = timezone.localdate()

    rows = []
    today_month = month_start(today)
    contract_end = month_start(lease.end_date or today)
    bills_query = MonthlyBill.objects.filter(lease=lease)
    if lease.end_date:
        bills_query = bills_query.filter(billing_month__lte=month_start(lease.end_date))
    bills = list(bills_query.order_by("billing_month"))
    bills_by_month = {
        month_start(bill.billing_month): bill
        for bill in bills
    }

    current_month = month_start(lease.start_date)
    while current_month <= contract_end:
        bill = bills_by_month.get(current_month)
        due_date = bill.due_date if bill else due_date_for_month(current_month.year, current_month.month, lease.due_day)

        if not bill:
            projected_total = (lease.monthly_rent + lease.parking_fee).quantize(Decimal("0.01"))
            if current_month > today_month:
                rows.append({
                    "month_label": current_month.strftime("%B %Y"),
                    "due_date": due_date,
                    "status_label": "Upcoming",
                    "status_class": "bg-amber-100 text-amber-700",
                    "total_due": projected_total,
                    "balance": projected_total,
                    "paid_amount": Decimal("0.00"),
                })
            else:
                rows.append({
                    "month_label": current_month.strftime("%B %Y"),
                    "due_date": due_date,
                    "status_label": "Unpaid",
                    "status_class": "bg-rose-100 text-rose-700",
                    "total_due": projected_total,
                    "balance": projected_total,
                    "paid_amount": Decimal("0.00"),
                })
            current_month = add_months(current_month, 1)
            continue

        if bill.status == "PAID":
            status_label = "Paid"
            status_class = "bg-emerald-100 text-emerald-700"
        elif bill.status == "PARTIALLY_PAID":
            status_label = "Partially Paid"
            status_class = "bg-amber-100 text-amber-700"
        elif bill.billing_state == "UPCOMING":
            status_label = "Upcoming"
            status_class = "bg-amber-100 text-amber-700"
        elif bill.billing_state == "OVERDUE":
            status_label = "Unpaid"
            status_class = "bg-rose-100 text-rose-700"
        else:
            status_label = "Unpaid"
            status_class = "bg-rose-100 text-rose-700"

        display_balance = bill.total_balance
        rows.append({
            "month_label": bill.billing_month.strftime("%B %Y"),
            "due_date": bill.due_date,
            "status_label": status_label,
            "status_class": status_class,
            "total_due": bill.total_due,
            "balance": display_balance,
            "paid_amount": (bill.total_due - display_balance) if bill.total_due is not None else Decimal("0.00"),
        })
        current_month = add_months(current_month, 1)
    return rows


def _contract_month_choices(lease, today=None):
    if not lease:
        return []

    if today is None:
        today = timezone.localdate()

    end_date = lease.end_date or today
    current = month_start(lease.start_date)
    end = month_start(end_date)

    months = []
    while current <= end:
        months.append((current.isoformat(), current.strftime("%B %Y")))
        current = add_months(current, 1)
    return months


def _parse_months_to_pay(request):
    try:
        return int(request.GET.get("months_to_pay", 1))
    except ValueError:
        return 1


def _contract_advance_month_cap(lease, today_start):
    if not lease.end_date:
        return MAX_ADVANCE_PAYMENT_MONTHS

    contract_end = month_start(lease.end_date)
    if contract_end < today_start:
        return 1

    month_diff = (contract_end.year - today_start.year) * 12 + (contract_end.month - today_start.month)
    return min(max(month_diff + 1, 1), MAX_ADVANCE_PAYMENT_MONTHS)


def _clamp_months_to_contract(months_to_pay, lease, today_start):
    contract_cap = _contract_advance_month_cap(lease, today_start)
    return min(max(months_to_pay, 1), contract_cap)


def _advance_month_options(contract_cap):
    return list(range(1, max(contract_cap, 0) + 1))


def _advance_generation_end_month(lease, today_start, months_to_pay):
    requested_end = add_months(today_start, months_to_pay + 1)
    if not lease.end_date:
        return requested_end
    contract_end = month_start(lease.end_date)
    return min(requested_end, contract_end)


def _contract_bounded_bills(lease):
    bills_query = MonthlyBill.objects.filter(lease=lease)
    if lease.end_date:
        bills_query = bills_query.filter(billing_month__lte=month_start(lease.end_date))
    return list(bills_query.order_by("billing_month"))


def _water_only_locked(existing_bills):
    oldest_outstanding_bill = next(
        (candidate_bill for candidate_bill in existing_bills if candidate_bill.total_balance > 0),
        existing_bills[0] if existing_bills else None,
    )
    return bool(
        oldest_outstanding_bill
        and oldest_outstanding_bill.total_balance > 0
        and oldest_outstanding_bill.water_balance > 0
        and oldest_outstanding_bill.rent_balance == 0
        and oldest_outstanding_bill.parking_balance == 0
    )


def _bill_has_rent_due(bill):
    return (bill.rent_balance + bill.parking_balance + bill.interest) > 0


def _bill_has_water_due(bill):
    return bill.water_balance > 0


def _bill_has_maintenance_due(bill):
    return bill.maintenance_balance > 0


def _full_bill_available(all_bills):
    return any(_bill_has_rent_due(bill) and _bill_has_water_due(bill) for bill in all_bills)


def _maintenance_only_available(all_bills):
    return any(_bill_has_maintenance_due(bill) for bill in all_bills if bill.status != "PAID")


def _automatic_payment_type(all_bills):
    oldest_due_bill = next(
        (bill for bill in all_bills if bill.total_balance > 0),
        None,
    )
    if not oldest_due_bill:
        return "rent_only"

    rent_due = _bill_has_rent_due(oldest_due_bill)
    water_due = _bill_has_water_due(oldest_due_bill)
    maintenance_due = _bill_has_maintenance_due(oldest_due_bill)
    if rent_due and water_due:
        return "full"
    if maintenance_due and not rent_due and not water_due:
        return "maintenance_only"
    if water_due:
        return "water_only"
    return "rent_only"


def _selected_payment_type(request, water_only_locked, full_bill_available, maintenance_only_available, all_bills):
    requested_payment_type = request.GET.get("payment_type", "").strip()
    if water_only_locked:
        return "water_only"
    if not requested_payment_type:
        return _automatic_payment_type(all_bills)
    if requested_payment_type == "water_only":
        return "water_only"
    if requested_payment_type == "maintenance_only" and maintenance_only_available:
        return "maintenance_only"
    if requested_payment_type == "full" and full_bill_available:
        return "full"
    return "rent_only"


def _bills_for_payment_type(all_bills, payment_type, months_to_pay, today_start):
    if months_to_pay <= 0:
        return []

    payable_bills = [bill for bill in all_bills if bill.status != "PAID"]

    if payment_type == "rent_only":
        bills_to_process = [bill for bill in payable_bills if _bill_has_rent_due(bill)][:months_to_pay]
        return bills_to_process or [
            bill for bill in payable_bills if _bill_has_rent_due(bill) or bill.status == "UPCOMING"
        ][:months_to_pay]

    if payment_type == "water_only":
        bills_to_process = [bill for bill in payable_bills if bill.water_balance > 0][:months_to_pay]
        return bills_to_process or [
            bill for bill in payable_bills if bill.water_balance > 0 or bill.status == "UPCOMING"
        ][:months_to_pay]

    if payment_type == "maintenance_only":
        bills_to_process = [bill for bill in payable_bills if bill.maintenance_balance > 0][:months_to_pay]
        return bills_to_process or [
            bill for bill in payable_bills if bill.maintenance_balance > 0
        ][:months_to_pay]

    bills_to_process = [
        bill for bill in payable_bills
        if bill.status in ["UNPAID", "PARTIALLY_PAID"]
    ][:months_to_pay]
    return bills_to_process or [
        bill for bill in payable_bills
        if bill.status in ["UNPAID", "UPCOMING"] or bill.billing_month > today_start
    ][:months_to_pay]


def _advanceable_bill_count(all_bills, payment_type, today_start):
    return len(_bills_for_payment_type(all_bills, payment_type, len(all_bills), today_start))


def _payment_amounts_for_bill(bill, payment_type):
    if payment_type == "rent_only":
        pay_rent = bill.rent_balance
        pay_water = Decimal("0.00")
        pay_parking = bill.parking_balance
        pay_maintenance = Decimal("0.00")
        pay_penalty = bill.interest
        display_rent = float(pay_rent)
        display_water = 0
        display_parking = float(pay_parking)
        display_maintenance = 0
    elif payment_type == "water_only":
        pay_rent = Decimal("0.00")
        pay_water = bill.water_balance
        pay_parking = Decimal("0.00")
        pay_maintenance = Decimal("0.00")
        pay_penalty = Decimal("0.00")
        display_rent = 0
        display_water = float(pay_water)
        display_parking = 0
        display_maintenance = 0
    elif payment_type == "maintenance_only":
        pay_rent = Decimal("0.00")
        pay_water = Decimal("0.00")
        pay_parking = Decimal("0.00")
        pay_maintenance = bill.maintenance_balance
        pay_penalty = Decimal("0.00")
        display_rent = 0
        display_water = 0
        display_parking = 0
        display_maintenance = float(pay_maintenance)
    else:
        pay_rent = bill.rent_balance
        pay_water = bill.water_balance
        pay_parking = bill.parking_balance
        pay_maintenance = bill.maintenance_balance
        pay_penalty = bill.interest
        display_rent = float(bill.base_rent)
        display_water = float(bill.water_amount or 0)
        display_parking = float(bill.parking_fee or 0)
        display_maintenance = float(bill.maintenance_amount or 0)

    return {
        "pay_rent": pay_rent,
        "pay_water": pay_water,
        "pay_parking": pay_parking,
        "pay_maintenance": pay_maintenance,
        "pay_penalty": pay_penalty,
        "display_rent": display_rent,
        "display_water": display_water,
        "display_parking": display_parking,
        "display_maintenance": display_maintenance,
    }


def _payment_row_total(amounts, payment_type):
    if payment_type == "rent_only":
        return amounts["pay_rent"] + amounts["pay_parking"] + amounts["pay_penalty"]
    if payment_type == "water_only":
        return amounts["pay_water"]
    if payment_type == "maintenance_only":
        return amounts["pay_maintenance"]
    return (
        amounts["pay_rent"]
        + amounts["pay_water"]
        + amounts["pay_parking"]
        + amounts["pay_maintenance"]
        + amounts["pay_penalty"]
    )


def _payment_preview_rows(lease, bills_to_process, payment_type):
    preview_rows = []
    for bill in bills_to_process:
        amounts = _payment_amounts_for_bill(bill, payment_type)
        pay_total = _payment_row_total(amounts, payment_type)

        preview_rows.append({
            "bill_id": bill.id,
            "month_label": bill.billing_month.strftime("%B %Y"),
            "rent": float(bill.base_rent),
            "water": float(bill.water_amount or 0),
            "parking": float(bill.parking_fee or 0),
            "maintenance": float(bill.maintenance_amount or 0),
            "penalty": float(bill.interest or 0),
            "pay_rent": float(amounts["pay_rent"]),
            "pay_water": float(amounts["pay_water"]),
            "pay_parking": float(amounts["pay_parking"]),
            "pay_maintenance": float(amounts["pay_maintenance"]),
            "pay_penalty": float(amounts["pay_penalty"]),
            "pay_total": float(pay_total),
            "display_rent": amounts["display_rent"],
            "display_water": amounts["display_water"],
            "display_parking": amounts["display_parking"],
            "display_maintenance": amounts["display_maintenance"],
            "due_date": bill.due_date,
        })
    return preview_rows


def _payment_totals(preview_rows, payment_type):
    return {
        "total_rent": sum(row["display_rent"] if payment_type == "full" else row["pay_rent"] for row in preview_rows),
        "total_water": sum(row["display_water"] if payment_type == "full" else row["pay_water"] for row in preview_rows),
        "total_parking": sum(row["display_parking"] if payment_type == "full" else row["pay_parking"] for row in preview_rows),
        "total_maintenance": sum(row["display_maintenance"] if payment_type == "full" else row["pay_maintenance"] for row in preview_rows),
        "total_penalty": sum(row["pay_penalty"] for row in preview_rows),
        "total_amount": sum(row["pay_total"] for row in preview_rows),
    }


def _payment_preview_context(request, lease, months_to_pay):
    reconcile_approved_payments_for_tenant(request.user)

    today = timezone.localdate()
    today_start = month_start(today)
    ensure_bills_up_to(lease, _advance_generation_end_month(lease, today_start, _contract_advance_month_cap(lease, today_start)))

    all_bills = _contract_bounded_bills(lease)
    water_only_locked = _water_only_locked(all_bills)
    full_bill_available = _full_bill_available(all_bills)
    maintenance_only_available = _maintenance_only_available(all_bills)
    can_pay_full_bill = full_bill_available and not water_only_locked
    payment_type = _selected_payment_type(request, water_only_locked, full_bill_available, maintenance_only_available, all_bills)
    advanceable_count = _advanceable_bill_count(all_bills, payment_type, today_start)
    capped_advanceable_count = min(advanceable_count, MAX_ADVANCE_PAYMENT_MONTHS)
    months_to_pay = min(max(months_to_pay, 1), capped_advanceable_count) if capped_advanceable_count else 0
    bills_to_process = _bills_for_payment_type(all_bills, payment_type, months_to_pay, today_start)
    preview_rows = _payment_preview_rows(lease, bills_to_process, payment_type)
    totals = _payment_totals(preview_rows, payment_type)
    show_detailed_breakdown = len(preview_rows) > 1 or any(
        (row["pay_penalty"] or 0) > 0
        or (row["pay_rent"] or 0) < (row["rent"] or 0)
        or (row["pay_water"] or 0) < (row["water"] or 0)
        or (row["pay_parking"] or 0) < (row["parking"] or 0)
        or (row["pay_maintenance"] or 0) < (row["maintenance"] or 0)
        or (row["maintenance"] or 0) > 0
        for row in preview_rows
    )

    unpaid_count = sum(
        1 for bill in all_bills
        if bill.status == "UNPAID" and bill.due_date <= today
    )
    water_available = any(
        bill.billing_month >= today_start and bill.water_amount > 0
        for bill in all_bills
    )

    return {
        "lease": lease,
        "months_options": _advance_month_options(capped_advanceable_count),
        "months_to_pay": months_to_pay,
        "max_months_to_pay": capped_advanceable_count,
        "no_advance_available": capped_advanceable_count == 0,
        "payment_type": payment_type,
        "water_only_locked": water_only_locked,
        "full_bill_available": full_bill_available,
        "can_pay_full_bill": can_pay_full_bill,
        "maintenance_only_available": maintenance_only_available,
        "has_pending": unpaid_count > 0,
        "unpaid_count": unpaid_count,
        "water_available": water_available,
        "preview_rows": preview_rows,
        "show_detailed_breakdown": show_detailed_breakdown,
        **totals,
    }


@tenant_required
def tenant_dashboard(request):
    """
    Main landing page for tenants. Synchronizes all billing and displays
    the current status, rent, and announcements.
    """
    user = request.user
    profile = TenantProfile.objects.filter(user=user).first()
    today = timezone.localdate()
    all_active_leases = _tenant_lease_options(user, today)
    lease = _selected_dashboard_lease(request, all_active_leases, today)
    announcements = Announcement.objects.filter(is_active=True).order_by("-created_at")[:5]
    billing_context = _dashboard_billing_context(user, lease, today)
    payment_context = _recent_payment_context(user)
    total_monthly_rent = lease.monthly_rent + lease.parking_fee if lease else None
    
    context = {
        "profile": profile,
        "lease": lease,
        "total_monthly_rent": total_monthly_rent,
        "all_active_leases": all_active_leases,
        "announcements": announcements,
        **billing_context,
        **payment_context,
    }
    return render(request, "rentals/tenant_dashboard.html", context)


@tenant_required
def tenant_billing(request):
    """
    Detailed billing statement showing breakdown of rent, water utility, and penalties.
    """
    user = request.user
    today = timezone.localdate()
    lease = _current_tenant_lease(user, today)

    if not lease:
        messages.warning(request, "An active lease is required to view billing.")
        return redirect("tenant_dashboard")

    reconcile_approved_payments_for_tenant(user)
    ensure_bills_since_move_in(lease)

    billing_month_filter = _tenant_billing_filters(request)
    selected_bill = _selected_contract_bill(lease, billing_month_filter)
    if selected_bill:
        current_bill = selected_bill
        refreshed_bills = [selected_bill]
    else:
        refreshed_bills = _filtered_bills_for_statement(lease, billing_month_filter)
        current_bill = refreshed_bills[0] if refreshed_bills else None
    water_reading = current_bill.source_water_reading if current_bill and current_bill.source_water_reading else None
    ongoing_rows = _ongoing_billing_rows(refreshed_bills, today)
    monthly_status_rows = _monthly_status_rows(lease, today)
    transactions = _approved_payment_transactions(user, lease)
    contract_month_choices = _contract_month_choices(lease, today)

    has_pending_payment = ManualPayment.objects.filter(
        user=request.user, status="PENDING"
    ).exclude(_unpaid_paymongo_checkout_filter()).exists()

    return render(request, "billing/tenant_billing.html", {
        "lease": lease,
        "current_bill": current_bill,
        "water_reading": water_reading,
        "ongoing_rows": ongoing_rows,
        "monthly_status_rows": monthly_status_rows,
        "transactions": transactions,
        "billing_month_filter": billing_month_filter,
        "contract_month_choices": contract_month_choices,
        "has_pending_payment": has_pending_payment,
    })


@tenant_required
def tenant_pay_advance(request):
    """
    View to handle the Make Payment page.
    Supports partial payments: rent only, water only, or full payment.
    """
    # Check if user just returned from a cancelled PayMongo payment
    # PayMongo redirects back to cancel_url when user clicks back arrow or closes checkout
    referrer = request.META.get('HTTP_REFERER', '')
    cancelled_param = request.GET.get('cancelled')
    
    if 'paymongo' in referrer.lower() or cancelled_param == '1':
        _remove_cancelled_paymongo_checkouts(request.user)
        messages.info(request, "Payment cancelled. You can try again or choose a different payment method.")
    
    today = timezone.localdate()
    lease = Lease.objects.filter(
        tenant=request.user,
        start_date__lte=today,
    ).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=today)
    ).order_by('-start_date').first()

    if not lease:
        messages.warning(request, "An active lease is required to make a payment.")
        return redirect("tenant_dashboard")

    months_to_pay = _parse_months_to_pay(request)
    context = _payment_preview_context(request, lease, months_to_pay)

    if request.method == "POST":
        url = reverse("manual_gcash_payment")
        # Pass payment type to payment processor
        bill_ids = ",".join(str(row["bill_id"]) for row in context["preview_rows"])
        return redirect(f"{url}?amount={context['total_amount']}&bill_ids={bill_ids}&payment_type={context['payment_type']}")

    return render(request, "billing/tenant_pay_advance.html", context)


@tenant_required
def mark_unit_welcome_seen(request):
    """Mark the unit welcome popup as seen for the current tenant"""
    if request.method == "POST":
        try:
            # Get the tenant's profile
            tenant_profile = get_object_or_404(TenantProfile, user=request.user)
            tenant_profile.has_seen_unit_welcome = True
            tenant_profile.save()
            
            from django.http import JsonResponse
            return JsonResponse({"success": True, "message": "Welcome popup marked as seen"})
        except Exception as e:
            from django.http import JsonResponse
            return JsonResponse({"success": False, "message": str(e)})
    
    # Only accept POST requests
    from django.http import JsonResponse
    return JsonResponse({"success": False, "message": "Method not allowed"})


@tenant_required
def tenant_notifications(request):
    """
    Display all notifications for the current tenant.
    Unread notifications are shown first, sorted by creation date.
    """
    purge_read_notifications_for_tenant(request.user)

    # Get notifications for this tenant
    base_notifications = Notification.objects.filter(
        recipient_type='TENANT',
        user=request.user
    )
    notifications = base_notifications
    
    # Handle filtering
    status_filter = request.GET.get('status', 'all')
    if status_filter == 'unread':
        notifications = notifications.filter(is_read=False)
    elif status_filter == 'read':
        notifications = notifications.filter(is_read=True)
        
    notifications = notifications.order_by('is_read', '-created_at')
    
    # Calculate unread count (unfiltered)
    unread_count = base_notifications.filter(is_read=False).count()
    read_count = base_notifications.filter(is_read=True).count()
    
    context = {
        "notifications": notifications,
        "unread_count": unread_count,
        "read_count": read_count,
        "status_filter": status_filter,
    }
    return render(request, "rentals/tenant_notifications.html", context)


@lru_cache(maxsize=1)
def notification_has_read_at_column() -> bool:
    """Return True when the notifications table already has the read_at column."""
    with connection.cursor() as cursor:
        columns = connection.introspection.get_table_description(cursor, Notification._meta.db_table)
    return any(column.name == "read_at" for column in columns)


@tenant_required
@require_POST
def mark_notification_read(request, notification_id):
    """
    Mark a specific notification as read.
    Supports both POST (AJAX) and regular form submit requests.
    """
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        recipient_type='TENANT',
        user=request.user
    )

    notification.is_read = True
    if notification_has_read_at_column():
        notification.read_at = timezone.now()
        notification.save(update_fields=["is_read", "read_at"])
    else:
        notification.save(update_fields=["is_read"])

    # Check if this is an AJAX request (fetch/XHR)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if is_ajax:
        from django.http import JsonResponse
        return JsonResponse({"success": True, "message": "Notification marked as read"})
    else:
        # Regular form submit - redirect back to notifications page
        messages.success(request, "Notification marked as read.")
        return redirect('tenant_notifications')


@tenant_required
@require_POST
def mark_all_notifications_read(request):
    """Mark all tenant notifications as read for the current user."""

    read_time = timezone.now()
    unread_notifications = Notification.objects.filter(
        recipient_type='TENANT',
        user=request.user,
        is_read=False,
    )
    if notification_has_read_at_column():
        updated_count = unread_notifications.update(is_read=True, read_at=read_time)
    else:
        updated_count = unread_notifications.update(is_read=True)

    messages.success(
        request,
        f"Marked {updated_count} notification{'' if updated_count == 1 else 's'} as read."
    )
    return redirect("tenant_notifications")


@tenant_required
def delete_all_read_notifications(request):
    """Delete all read tenant notifications for the current user."""
    if request.method != "POST":
        return redirect("tenant_notifications")

    deleted_count, _ = Notification.objects.filter(
        recipient_type="TENANT",
        user=request.user,
        is_read=True,
    ).delete()
    messages.success(request, f"Deleted {deleted_count} read notification{'s' if deleted_count != 1 else ''}.")
    return redirect("tenant_notifications")


@tenant_required
def delete_notification(request, notification_id):
    """Delete a read tenant notification owned by the current user."""
    if request.method != "POST":
        return redirect("tenant_notifications")

    notification = get_object_or_404(
        Notification,
        id=notification_id,
        recipient_type="TENANT",
        user=request.user,
    )

    if not notification.is_read:
        messages.warning(request, "Only notifications already marked as read can be deleted.")
        return redirect("tenant_notifications")

    notification.delete()
    messages.success(request, "Notification deleted.")
    return redirect("tenant_notifications")


def purge_read_notifications_for_tenant(user):
    """Delete tenant notifications that have been read for over 24 hours."""
    if not notification_has_read_at_column():
        return

    cutoff = timezone.now() - timedelta(days=1)
    Notification.objects.filter(
        recipient_type='TENANT',
        user=user,
        is_read=True,
        read_at__lte=cutoff,
    ).delete()



