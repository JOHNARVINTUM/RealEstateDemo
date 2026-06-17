import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from billing.models import MonthlyBill
from billing.services import approve_manual_payment, reject_manual_payment
from payments.models import ManualPayment
from payments.scheduling import OFFICE_HOURS_LABEL, f2f_time_slots, is_office_schedule
from rentals.models import Lease, Notification
from rentals.services import repair_historical_move_in_payment, send_email_via_resend

from .admin_portal_views import admin_required, admin_password_verified, render_admin_password_confirm

logger = logging.getLogger(__name__)


def _tenant_display_name(user):
    if hasattr(user, "tenantprofile"):
        full_name = getattr(user.tenantprofile, "full_name", "").strip()
        if full_name:
            return full_name
    return user.email


def _admin_payment_queryset():
    return ManualPayment.objects.select_related("user", "user__tenantprofile").filter(
        user__role="TENANT",
        user__is_staff=False,
        user__is_superuser=False,
    ).exclude(
        payment_method="PAYMONGO",
        status="PENDING",
        paymongo_payment_id="",
    )


def _decorate_admin_payment_rows(payment_rows):
    page_user_ids = {payment.user_id for payment in payment_rows}
    tenant_leases = (
        Lease.objects.filter(tenant_id__in=page_user_ids)
        .select_related("unit")
        .order_by("tenant_id", "-start_date")
    )
    latest_lease_by_user_id = {}
    for tenant_lease in tenant_leases:
        latest_lease_by_user_id.setdefault(tenant_lease.tenant_id, tenant_lease)

    page_bill_ids = set()
    payment_bill_ids = {}
    for payment in payment_rows:
        bid_list = [int(x.strip()) for x in payment.bill_ids.split(',') if x.strip().isdigit()]
        payment_bill_ids[payment.id] = bid_list
        page_bill_ids.update(bid_list)

    bills_by_id = {}
    if page_bill_ids:
        bills_by_id = {
            bill.id: bill
            for bill in MonthlyBill.objects.filter(pk__in=page_bill_ids).only(
                "id",
                "billing_month",
                "base_rent",
                "water_amount",
                "parking_fee",
            )
        }

    for p in payment_rows:
        tenant_lease = latest_lease_by_user_id.get(p.user_id)
        p.unit_number = tenant_lease.unit.number if tenant_lease and tenant_lease.unit else None
        p.tenant_display_name = _tenant_display_name(p.user)
        p.bill_type_label = p.get_payment_type_display() if hasattr(p, 'get_payment_type_display') else p.payment_type
        try:
            bid_list = payment_bill_ids.get(p.id, [])
            if bid_list:
                bills = [bills_by_id[bill_id] for bill_id in bid_list if bill_id in bills_by_id]
                parts = []
                has_rent = any(b.base_rent > 0 for b in bills)
                has_water = any(b.water_amount > 0 for b in bills)
                has_parking = any(b.parking_fee > 0 for b in bills)
                if has_rent:
                    parts.append('Rent')
                if has_water:
                    parts.append('Water')
                if has_parking:
                    parts.append('Parking')
                p.bill_components = ', '.join(parts) if parts else 'Rent'
                months = sorted({bill.billing_month for bill in bills})
                p.affected_months = ", ".join(month.strftime("%b %Y") for month in months) if months else "-"
            else:
                p.bill_components = '-'
                p.affected_months = '-'
        except Exception:
            p.bill_components = '-'
            p.affected_months = '-'

    return payment_rows


def _parse_calendar_date(value, fallback):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return fallback


def _parse_reschedule_time(value):
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError):
        return None


def _format_schedule(date_value, time_value):
    if not date_value:
        return "No date selected"
    schedule = date_value.strftime("%B %d, %Y")
    if time_value:
        schedule += f" at {time_value.strftime('%I:%M %p')}"
    return schedule


def _build_cash_calendar_context(request, calendar_url):
    today = timezone.localdate()
    week_anchor = _parse_calendar_date(request.GET.get("week"), today)
    week_start = week_anchor - timedelta(days=week_anchor.weekday())
    week_end = week_start + timedelta(days=6)

    default_selected_day = today if week_start <= today <= week_end else week_start
    selected_day = _parse_calendar_date(request.GET.get("day"), default_selected_day)
    if selected_day < week_start or selected_day > week_end:
        selected_day = default_selected_day

    payments = list(
        _admin_payment_queryset()
        .filter(
            payment_method="CASH",
            preferred_date__gte=week_start,
            preferred_date__lte=week_end,
        )
        .exclude(status="REJECTED")
        .order_by("preferred_date", "preferred_time", "created_at")
    )
    _decorate_admin_payment_rows(payments)

    payments_by_day = {week_start + timedelta(days=offset): [] for offset in range(7)}
    for payment in payments:
        if payment.preferred_date in payments_by_day:
            payments_by_day[payment.preferred_date].append(payment)

    calendar_days = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        day_payments = payments_by_day[day]
        calendar_days.append({
            "date": day,
            "payments": day_payments,
            "count": len(day_payments),
            "total_amount": sum((payment.amount for payment in day_payments), Decimal("0.00")),
            "is_today": day == today,
            "is_selected": day == selected_day,
        })

    calendar_query_prefix = f"{calendar_url}&" if "?" in calendar_url else f"{calendar_url}?"

    return {
        "calendar_days": calendar_days,
        "selected_day": selected_day,
        "selected_payments": payments_by_day.get(selected_day, []),
        "week_start": week_start,
        "week_end": week_end,
        "previous_week": week_start - timedelta(days=7),
        "next_week": week_start + timedelta(days=7),
        "week_total_count": len(payments),
        "week_total_amount": sum((payment.amount for payment in payments), Decimal("0.00")),
        "calendar_query_prefix": calendar_query_prefix,
    }


def _payment_record_fallback_amounts(payment, bill, remaining_amount):
    remaining_amount = Decimal(remaining_amount or 0)
    if remaining_amount <= 0:
        return Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")

    pay_rent = pay_water = pay_parking = pay_penalty = Decimal("0.00")

    def take(amount):
        nonlocal remaining_amount
        amount = min(Decimal(amount or 0), remaining_amount)
        remaining_amount -= amount
        return amount

    if payment.payment_type == "rent_only":
        pay_rent = take(bill.base_rent)
        pay_parking = take(bill.parking_fee)
        pay_penalty = take(bill.interest)
    elif payment.payment_type == "water_only":
        pay_water = take(bill.water_amount)
    else:
        pay_rent = take(bill.base_rent)
        pay_water = take(bill.water_amount)
        pay_parking = take(bill.parking_fee)
        pay_penalty = take(bill.interest)

    if pay_rent + pay_water + pay_parking + pay_penalty == 0:
        if payment.payment_type == "water_only":
            pay_water = remaining_amount
        else:
            pay_rent = remaining_amount

    return pay_rent, pay_water, pay_parking, pay_penalty


@admin_required
def admin_approve_payment(request, payment_id: int):
    p = get_object_or_404(ManualPayment.objects.select_related("user", "user__tenantprofile"), pk=payment_id)
    if request.method == "POST":
        try:
            approve_manual_payment(p)
            messages.success(request, f"Payment {p.reference_code} approved successfully.")


        except Exception as e:
            messages.error(request, f"Error approving payment: {e}")
        return redirect("admin_payments")
    return render(request, "admin_portal/confirm.html", {
        "title": "Approve Payment",
        "message": f"Approve payment {p.reference_code} by {p.user.email}?",
        "post_url": reverse("admin_approve_payment", args=[p.id]),
        "back_url": reverse("admin_payments"),
    })


@admin_required
def admin_repair_move_in_payment(request, payment_id: int):
    p = get_object_or_404(ManualPayment.objects.select_related("user", "user__tenantprofile"), pk=payment_id)
    if request.method == "POST":
        try:
            success, message = repair_historical_move_in_payment(p)
            if success:
                messages.success(request, message)
            else:
                messages.error(request, message)
        except Exception as e:
            messages.error(request, f"Error repairing move-in payment: {e}")
            logger.exception("Error repairing historical move-in payment")
        return redirect("admin_payment_detail", payment_id=p.id)
    return render(request, "admin_portal/confirm.html", {
        "title": "Repair Move-in Payment",
        "message": (
            f"Repair historical move-in payment {p.reference_code} for {p.user.email}?\n\n"
            f"This is intended only for old testing records where the tenant actually paid "
            f"but the payment was manually rejected."
        ),
        "post_url": reverse("admin_repair_move_in_payment", args=[p.id]),
        "back_url": reverse("admin_payment_detail", args=[p.id]),
    })


@admin_required
def admin_reject_payment(request, payment_id: int):
    p = get_object_or_404(ManualPayment.objects.select_related("user", "user__tenantprofile"), pk=payment_id)
    if request.method == "POST":
        reject_manual_payment(p)
        messages.success(request, f"Payment {p.reference_code} rejected.")
        return redirect("admin_payments")
    return render(request, "admin_portal/confirm.html", {
        "title": "Reject Payment",
        "message": f"Reject payment {p.reference_code} by {p.user.email}?",
        "post_url": reverse("admin_reject_payment", args=[p.id]),
        "back_url": reverse("admin_payments"),
    })


@admin_required
def admin_confirm_schedule(request, payment_id: int):
    """Confirm F2F cash payment schedule - notifies tenant that time is confirmed"""
    p = get_object_or_404(ManualPayment.objects.select_related("user", "user__tenantprofile"), pk=payment_id)
    if request.method == "POST":
        p.schedule_confirmed = True
        p.save(update_fields=["schedule_confirmed"])

        # Notify tenant that schedule is confirmed
        try:
            from rentals.models import Notification
            schedule_info = f"on {p.preferred_date.strftime('%B %d, %Y')}" if p.preferred_date else ""
            if p.preferred_time:
                schedule_info += f" at {p.preferred_time.strftime('%I:%M %p')}"

            Notification.create_tenant_notification(
                title="Cash Payment Appointment Confirmed",
                message=f"Your face-to-face cash payment appointment has been confirmed.\n\nAmount: \u20b1{p.amount:,.2f}\nScheduled: {schedule_info}\n\nPlease bring the exact amount. See you then!",
                notification_type='PAYMENT',
                tenant_user=p.user
            )
        except Exception as e:
            logger.exception(f"Failed to create schedule confirmation notification: {e}")

        messages.success(request, f"Schedule confirmed for {p.user.email}. Tenant has been notified.")
        return redirect("admin_payments")

    schedule_info = f"{p.preferred_date.strftime('%B %d, %Y')}" if p.preferred_date else "No date"
    if p.preferred_time:
        schedule_info += f" at {p.preferred_time.strftime('%I:%M %p')}"

    return render(request, "admin_portal/confirm.html", {
        "title": "Confirm F2F Schedule",
        "message": f"Confirm cash payment appointment for {p.user.email}?\n\nAmount: \u20b1{p.amount:,.2f}\nScheduled: {schedule_info}\n\nTenant will be notified that the appointment is confirmed.",
        "post_url": reverse("admin_confirm_schedule", args=[p.id]),
        "back_url": reverse("admin_payments"),
    })


@admin_required
def admin_payments(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    method = request.GET.get("method", "").strip()

    payments = _admin_payment_queryset()
    if status in ("PENDING", "APPROVED", "REJECTED"):
        payments = payments.filter(status=status)
    if method == "GCASH":
        payments = payments.filter(payment_method="GCASH")
    elif method == "CASH":
        payments = payments.filter(payment_method="CASH")
    elif method == "PAYMONGO":
        payments = payments.filter(payment_method="PAYMONGO")

    if q:
        payments = payments.filter(
            Q(user__email__icontains=q) |
            Q(reference_code__icontains=q) |
            Q(bill_ids__icontains=q)
        )

    filtered_payments = payments.order_by("-created_at")

    status_counts = filtered_payments.aggregate(
        pending_count=Count("id", filter=Q(status="PENDING")),
        approved_count=Count("id", filter=Q(status="APPROVED")),
        rejected_count=Count("id", filter=Q(status="REJECTED")),
        cash_schedule_count=Count("id", filter=Q(payment_method="CASH", status="PENDING")),
    )
    pending_count = status_counts["pending_count"] or 0
    approved_count = status_counts["approved_count"] or 0
    rejected_count = status_counts["rejected_count"] or 0
    cash_schedule_count = status_counts["cash_schedule_count"] or 0

    paginator = Paginator(filtered_payments, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    page_payments = list(page_obj.object_list)
    page_user_ids = {payment.user_id for payment in page_payments}
    tenant_leases = (
        Lease.objects.filter(tenant_id__in=page_user_ids)
        .select_related("unit")
        .order_by("tenant_id", "-start_date")
    )
    latest_lease_by_user_id = {}
    for tenant_lease in tenant_leases:
        latest_lease_by_user_id.setdefault(tenant_lease.tenant_id, tenant_lease)

    page_bill_ids = set()
    payment_bill_ids = {}
    for payment in page_payments:
        bid_list = [int(x.strip()) for x in payment.bill_ids.split(',') if x.strip().isdigit()]
        payment_bill_ids[payment.id] = bid_list
        page_bill_ids.update(bid_list)

    bills_by_id = {}
    if page_bill_ids:
        bills_by_id = {
            bill.id: bill
            for bill in MonthlyBill.objects.filter(pk__in=page_bill_ids).only(
                "id",
                "billing_month",
                "base_rent",
                "water_amount",
                "parking_fee",
            )
        }

    for p in page_payments:
        tenant_lease = latest_lease_by_user_id.get(p.user_id)
        p.unit_number = tenant_lease.unit.number if tenant_lease and tenant_lease.unit else None
        p.tenant_display_name = _tenant_display_name(p.user)
        p.bill_type_label = p.get_payment_type_display() if hasattr(p, 'get_payment_type_display') else p.payment_type
        try:
            bid_list = payment_bill_ids.get(p.id, [])
            if bid_list:
                bills = [bills_by_id[bill_id] for bill_id in bid_list if bill_id in bills_by_id]
                parts = []
                has_rent = any(b.base_rent > 0 for b in bills)
                has_water = any(b.water_amount > 0 for b in bills)
                has_parking = any(b.parking_fee > 0 for b in bills)
                if has_rent:
                    parts.append('Rent')
                if has_water:
                    parts.append('Water')
                if has_parking:
                    parts.append('Parking')
                p.bill_components = ', '.join(parts) if parts else 'Rent'
                months = sorted({bill.billing_month for bill in bills})
                p.affected_months = ", ".join(month.strftime("%b %Y") for month in months) if months else "â€”"
            else:
                p.bill_components = 'â€”'
                p.affected_months = 'â€”'
        except Exception:
            p.bill_components = 'â€”'
            p.affected_months = 'â€”'

    is_f2f_schedule_view = method == "CASH" and status == "PENDING"
    cash_schedule_payments = page_payments if is_f2f_schedule_view else []
    other_payments = [] if is_f2f_schedule_view else page_payments

    context = {
        "page_obj": page_obj,
        "cash_schedule_payments": cash_schedule_payments,
        "other_payments": other_payments,
        "q": q,
        "status": status,
        "method": method,
        "is_f2f_schedule_view": is_f2f_schedule_view,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "cash_schedule_count": cash_schedule_count,
    }
    if is_f2f_schedule_view:
        context.update(
            _build_cash_calendar_context(
                request,
                f"{reverse('admin_payments')}?status=PENDING&method=CASH",
            )
        )

    return render(request, "admin_portal/payments.html", context)


@admin_required
def admin_payment_calendar(request):
    context = _build_cash_calendar_context(request, reverse("admin_payment_calendar"))
    return render(request, "admin_portal/payment_calendar.html", context)


@admin_required
def admin_delete_payment(request, payment_id: int):
    payment = get_object_or_404(ManualPayment.objects.select_related("user", "user__tenantprofile"), pk=payment_id)
    if request.method == "POST":
        if not admin_password_verified(request):
            return render_admin_password_confirm(
                request,
                title="Delete Billing History",
                message=f"Delete payment history {payment.reference_code} for {payment.user.email}?",
                post_url=reverse("admin_delete_payment", args=[payment.id]),
                back_url=reverse("admin_payments"),
                error="Incorrect admin password. Payment history was not deleted.",
            )
        with transaction.atomic():
            payment.delete()
        return redirect("admin_payments")
    return render_admin_password_confirm(
        request,
        title="Delete Billing History",
        message=f"Delete payment history {payment.reference_code} for {payment.user.email}?",
        post_url=reverse("admin_delete_payment", args=[payment.id]),
        back_url=reverse("admin_payments"),
    )


@admin_required
def admin_payment_detail(request, payment_id: int):
    """
    Display complete payment details including breakdown of bills and amounts.
    """
    from billing.services import parse_bill_ids

    payment = get_object_or_404(ManualPayment.objects.select_related("user", "user__tenantprofile"), pk=payment_id)
    is_settled_payment = payment.status == "APPROVED"
    tenant_display_name = _tenant_display_name(payment.user)

    payment_type_choices = [
        ("rent_only", "Monthly Rent"),
        ("water_only", "Water Only"),
        ("full", "Full Bill"),
    ]

    if request.method == "POST" and request.POST.get("action") == "update_payment_type":
        if payment.payment_type != "move_in":
            new_payment_type = (request.POST.get("payment_type") or "").strip()
            valid_types = {value for value, _ in payment_type_choices}
            if new_payment_type in valid_types and new_payment_type != payment.payment_type:
                payment.payment_type = new_payment_type
                metadata = payment.metadata if isinstance(payment.metadata, dict) else {}
                metadata = dict(metadata)
                metadata["payment_type"] = new_payment_type
                payment.metadata = metadata
                payment.save(update_fields=["payment_type", "metadata"])
                messages.success(request, f"Payment type updated to {payment.get_payment_type_display()}.")
            else:
                messages.info(request, "Payment type was not changed.")
        else:
            messages.error(request, "Move-in payments cannot be changed from this page.")
        return redirect("admin_payment_detail", payment_id=payment.id)

    bill_ids = parse_bill_ids(payment.bill_ids)
    bills = []
    bills_by_id = {
        bill.id: bill
        for bill in MonthlyBill.objects.select_related("lease", "lease__unit").filter(pk__in=bill_ids)
    }
    remaining_payment_amount = Decimal(payment.amount or 0)

    for bill_id in bill_ids:
        bill = bills_by_id.get(bill_id)
        if bill is None:
            bills.append({
                "id": bill_id,
                "month": "Unknown",
                "unit": "Unknown",
                "full_rent": 0,
                "full_water": 0,
                "full_parking": 0,
                "full_penalty": 0,
                "rent": 0,
                "water": 0,
                "parking": 0,
                "penalty": 0,
                "total": 0,
            })
            continue

        if payment.payment_type == "rent_only":
            pay_rent = bill.base_rent if is_settled_payment else bill.rent_balance
            pay_water = 0
            pay_parking = bill.parking_fee if is_settled_payment else bill.parking_balance
            pay_penalty = bill.interest
        elif payment.payment_type == "water_only":
            pay_rent = 0
            pay_water = bill.water_amount if is_settled_payment else bill.water_balance
            pay_parking = 0
            pay_penalty = 0
        else:
            pay_rent = bill.base_rent if is_settled_payment else bill.rent_balance
            pay_water = bill.water_amount if is_settled_payment else bill.water_balance
            pay_parking = bill.parking_fee if is_settled_payment else bill.parking_balance
            pay_penalty = bill.interest

        pay_total = pay_rent + pay_water + pay_parking + pay_penalty
        if pay_total == 0 and remaining_payment_amount > 0:
            pay_rent, pay_water, pay_parking, pay_penalty = _payment_record_fallback_amounts(
                payment,
                bill,
                remaining_payment_amount,
            )
            pay_total = pay_rent + pay_water + pay_parking + pay_penalty
        remaining_payment_amount = max(remaining_payment_amount - pay_total, Decimal("0.00"))

        bills.append({
            "id": bill.id,
            "month": bill.billing_month.strftime("%B %Y"),
            "unit": bill.lease.unit.number if bill.lease and bill.lease.unit else "Unknown",
            "full_rent": bill.base_rent,
            "full_water": bill.water_amount,
            "full_parking": bill.parking_fee,
            "full_penalty": bill.interest,
            "rent": pay_rent,
            "water": pay_water,
            "parking": pay_parking,
            "penalty": pay_penalty,
            "total": pay_total,
        })

    total_rent = sum(b["rent"] for b in bills)
    total_water = sum(b["water"] for b in bills)
    total_parking = sum(b["parking"] for b in bills)
    total_penalty = sum(b["penalty"] for b in bills)
    calculated_total = total_rent + total_water + total_parking + total_penalty

    context = {
        "payment": payment,
        "tenant_display_name": tenant_display_name,
        "payment_method_label": payment.get_payment_method_display() if hasattr(payment, "get_payment_method_display") else payment.payment_method,
        "paymongo_method_label": (payment.paid_via or "").replace("_", " ").title(),
        "payment_type_choices": payment_type_choices,
        "bills": bills,
        "bill_count": len(bills),
        "total_rent": total_rent,
        "total_water": total_water,
        "total_parking": total_parking,
        "total_penalty": total_penalty,
        "total_amount": calculated_total,
    }

    return render(request, "admin_portal/payment_detail.html", context)


@admin_required
def admin_reschedule_cash_payment(request, payment_id: int):
    payment = get_object_or_404(_admin_payment_queryset(), pk=payment_id)
    if payment.payment_method != "CASH":
        messages.error(request, "Only face-to-face cash appointments can be rescheduled.")
        return redirect("admin_payment_detail", payment_id=payment.id)
    if payment.status != "PENDING":
        messages.error(request, "Only pending cash appointments can be rescheduled.")
        return redirect("admin_payment_detail", payment_id=payment.id)

    current_date = payment.preferred_date
    current_time = payment.preferred_time
    current_note = payment.schedule_admin_note or ""

    if request.method == "POST":
        preferred_date = (request.POST.get("preferred_date") or "").strip()
        preferred_time = (request.POST.get("preferred_time") or "").strip()
        admin_note = (request.POST.get("schedule_admin_note") or "").strip()

        parsed_date = _parse_calendar_date(preferred_date, None)
        parsed_time = _parse_reschedule_time(preferred_time)

        if not parsed_date:
            messages.error(request, "Please choose a valid reschedule date.")
        elif not parsed_time:
            messages.error(request, "Please choose an available office-hour time.")
        else:
            is_valid_schedule, schedule_error = is_office_schedule(parsed_date, parsed_time)
            if not is_valid_schedule:
                messages.error(request, schedule_error)
            else:
                old_schedule = _format_schedule(current_date, current_time)
                new_schedule = _format_schedule(parsed_date, parsed_time)

                payment.preferred_date = parsed_date
                payment.preferred_time = parsed_time
                payment.schedule_admin_note = admin_note
                payment.schedule_confirmed = True
                payment.save(
                    update_fields=[
                        "preferred_date",
                        "preferred_time",
                        "schedule_admin_note",
                        "schedule_confirmed",
                    ]
                )

                notification_message = (
                    "Your face-to-face cash payment appointment has been rescheduled.\n\n"
                    f"Previous schedule: {old_schedule}\n"
                    f"New schedule: {new_schedule}\n"
                    f"Amount: PHP {payment.amount:,.2f}\n"
                    f"Reference: {payment.reference_code or '-'}"
                )
                if admin_note:
                    notification_message += f"\n\nAdmin note: {admin_note}"

                try:
                    Notification.create_tenant_notification(
                        title="Cash Payment Appointment Rescheduled",
                        message=notification_message,
                        notification_type="PAYMENT",
                        tenant_user=payment.user,
                    )
                except Exception as exc:
                    logger.exception("Failed to create cash reschedule notification for payment %s: %s", payment.id, exc)
                    messages.warning(request, "Schedule was updated, but tenant notification could not be created.")

                email_sent = send_email_via_resend(
                    payment.user.email,
                    "[REALESTATE360+] Cash Payment Appointment Rescheduled",
                    (
                        f"Hello {_tenant_display_name(payment.user)},\n\n"
                        f"{notification_message}\n\n"
                        "Please check your tenant portal for the updated appointment details.\n\n"
                        "REALESTATE360+ Administration"
                    ),
                )
                if email_sent:
                    messages.success(request, "Cash appointment rescheduled. Tenant notification and email were sent.")
                else:
                    messages.warning(request, "Cash appointment rescheduled, but the email was not sent. Check Resend configuration/logs.")
                return redirect("admin_payment_detail", payment_id=payment.id)

        current_date = parsed_date or current_date
        current_time = parsed_time or current_time
        current_note = admin_note

    return render(request, "admin_portal/payment_reschedule.html", {
        "payment": payment,
        "tenant_display_name": _tenant_display_name(payment.user),
        "office_time_slots": f2f_time_slots(),
        "office_hours_label": OFFICE_HOURS_LABEL,
        "selected_date": current_date,
        "selected_time": current_time.strftime("%H:%M") if current_time else "",
        "schedule_admin_note": current_note,
        "back_url": reverse("admin_payment_detail", args=[payment.id]),
    })
