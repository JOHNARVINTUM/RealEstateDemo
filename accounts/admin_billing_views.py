from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone as dj_timezone
from django.utils import timezone
from django.db.models import Count, Q

from billing.models import MonthlyBill
from billing.services import (
    cleanup_duplicate_monthly_bills,
    create_and_send_invoice_for_paid_bill,
    duplicate_monthly_bill_cleanup_preview,
    get_or_update_monthly_bill,
    repair_inflated_unpaid_late_fees,
    set_bill_status,
)
from rentals import services as rental_services

from .admin_portal_views import admin_required, admin_password_verified, render_admin_password_confirm


def _safe_csv_value(value):
    if not isinstance(value, str):
        return value
    if value and value[0] in ("=", "+", "-", "@"):
        return f"'{value}"
    return value


def _bill_balance_amount(bill):
    if bill.total_balance > 0:
        return bill.total_balance
    if bill.status != "PAID":
        return bill.total_due
    return Decimal("0.00")


def _refresh_bill_for_settlement_display(bill, today=None):
    if bill.status == "PAID":
        return bill
    today = today or date.today()
    if bill.billing_month.replace(day=1) > today.replace(day=1):
        return bill
    return get_or_update_monthly_bill(bill.lease, bill.billing_month, today=today)


def _settle_bill_and_invoice(bill, paid_at):
    bill = set_bill_status(bill, status="PAID", paid_at=paid_at)
    create_and_send_invoice_for_paid_bill(bill, paid_at=paid_at)
    return bill


def _prior_unpaid_bills_for_settlement(bill):
    current_month = date.today().replace(day=1)
    candidates = (
        MonthlyBill.objects.select_related("lease", "lease__tenant", "lease__tenant__tenantprofile", "lease__unit")
        .filter(
            lease=bill.lease,
            status__in=("UNPAID", "PARTIALLY_PAID"),
            billing_month__lt=current_month,
        )
        .exclude(pk=bill.pk)
        .order_by("billing_month", "id")
    )
    bills = []
    for candidate in candidates:
        if _is_unpaid_duplicate_shell(candidate):
            continue
        refreshed = _refresh_bill_for_settlement_display(candidate)
        if _bill_balance_amount(refreshed) > 0:
            bills.append(refreshed)
    return bills


def _is_unpaid_duplicate_shell(bill):
    if not (
        bill.status == "UNPAID"
        and bill.rent_paid == 0
        and bill.water_paid == 0
        and bill.parking_paid == 0
    ):
        return False
    return MonthlyBill.objects.filter(
        lease=bill.lease,
        billing_month__year=bill.billing_month.year,
        billing_month__month=bill.billing_month.month,
        status__in=("PAID", "PARTIALLY_PAID"),
    ).exclude(pk=bill.pk).exists()


def _bill_computation_rows(bills):
    rows = []
    for bill in bills:
        rows.append({
            "bill": bill,
            "month": bill.billing_month.strftime("%b %Y"),
            "rent": bill.rent_balance,
            "water": bill.water_balance,
            "parking": bill.parking_balance,
            "late_fee": bill.interest,
            "balance": _bill_balance_amount(bill),
        })
    return rows


def _settlement_warning_context(bill, prior_unpaid_bills):
    selected_balance = _bill_balance_amount(bill)
    rows = _bill_computation_rows(prior_unpaid_bills)
    prior_total = sum((row["balance"] for row in rows), Decimal("0.00"))
    return {
        "bill": bill,
        "prior_bills": rows,
        "prior_total": prior_total,
        "selected_balance": selected_balance,
        "settle_all_total": selected_balance + prior_total,
        "post_url": reverse("admin_mark_bill_paid", args=[bill.id]),
        "back_url": reverse("admin_billing"),
    }


@admin_required
def admin_mark_bill_paid(request, bill_id: int):
    bill = get_object_or_404(
        MonthlyBill.objects.select_related("lease", "lease__tenant", "lease__tenant__tenantprofile", "lease__unit"),
        pk=bill_id,
    )
    bill = _refresh_bill_for_settlement_display(bill)
    prior_unpaid_bills = _prior_unpaid_bills_for_settlement(bill)
    if request.method == "POST":
        action = request.POST.get("action", "")
        paid_at = dj_timezone.now()

        if prior_unpaid_bills and action not in ("settle_all", "settle_bill"):
            return render(request, "admin_portal/billing_settle_warning.html", _settlement_warning_context(bill, prior_unpaid_bills))

        if action == "settle_bill":
            target_bill = get_object_or_404(
                MonthlyBill.objects.select_related("lease", "lease__tenant", "lease__unit"),
                pk=request.POST.get("target_bill_id"),
                lease=bill.lease,
            )
            _settle_bill_and_invoice(target_bill, paid_at)
            messages.success(request, f"{target_bill.billing_month.strftime('%B %Y')} was marked as paid.")
            return redirect("admin_mark_bill_paid", bill_id=bill.id)

        if action == "settle_all":
            for prior_bill in prior_unpaid_bills:
                _settle_bill_and_invoice(prior_bill, paid_at)
            _settle_bill_and_invoice(bill, paid_at)
            messages.success(request, f"Settled {len(prior_unpaid_bills) + 1} bill(s) for this tenant.")
            return redirect("admin_billing")

        _settle_bill_and_invoice(bill, paid_at)
        return redirect("admin_billing")
    if prior_unpaid_bills:
        return render(request, "admin_portal/billing_settle_warning.html", _settlement_warning_context(bill, prior_unpaid_bills))
    return render(request, "admin_portal/confirm.html", {
        "title": "Mark Bill Paid",
        "message": f"Mark bill {bill.id} as PAID?",
        "post_url": reverse("admin_mark_bill_paid", args=[bill.id]),
        "back_url": reverse("admin_billing"),
    })


@admin_required
def admin_mark_bill_unpaid(request, bill_id: int):
    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    if request.method == "POST":
        set_bill_status(bill, status="UNPAID")
        return redirect("admin_billing")
    return render(request, "admin_portal/confirm.html", {
        "title": "Mark Bill Unpaid",
        "message": f"Mark bill {bill.id} as UNPAID?",
        "post_url": reverse("admin_mark_bill_unpaid", args=[bill.id]),
        "back_url": reverse("admin_billing"),
    })


@admin_required
def admin_repair_late_fees(request):
    preview = repair_inflated_unpaid_late_fees(dry_run=True)
    if request.method == "POST":
        result = repair_inflated_unpaid_late_fees(dry_run=False)
        messages.success(
            request,
            (
                f"Repaired {result['repaired_count']} unpaid bill late fee(s). "
                f"Total reduction: PHP {result['total_reduction']:,.2f}."
            ),
        )
        return redirect("admin_billing")

    return render(request, "admin_portal/billing_repair_late_fees.html", {
        "preview": preview,
        "post_url": reverse("admin_repair_late_fees"),
        "back_url": reverse("admin_billing"),
    })


@admin_required
def admin_cleanup_duplicate_bills(request):
    preview = duplicate_monthly_bill_cleanup_preview()
    if request.method == "POST":
        removed_count = cleanup_duplicate_monthly_bills()
        messages.success(request, f"Removed {removed_count} duplicate unpaid billing record(s).")
        return redirect("admin_billing")

    return render(request, "admin_portal/billing_cleanup_duplicates.html", {
        "preview": preview,
        "post_url": reverse("admin_cleanup_duplicate_bills"),
        "back_url": reverse("admin_billing"),
    })


@admin_required
def admin_billing_export_csv(request):
    import csv
    from calendar import month_abbr

    month_filter = request.GET.get("month", "").strip()
    year_filter = request.GET.get("year", "").strip()
    status_filter = request.GET.get("status", "").strip()

    bills = MonthlyBill.objects.select_related(
        "lease", "lease__tenant", "lease__tenant__tenantprofile", "lease__unit"
    ).order_by("-billing_month")

    if month_filter:
        bills = bills.filter(billing_month__month=month_filter)
    if year_filter:
        bills = bills.filter(billing_month__year=year_filter)
    if status_filter:
        bills = bills.filter(status=status_filter)

    filename_parts = ["billing_report"]
    if month_filter and year_filter:
        try:
            filename_parts.append(f"{month_abbr[int(month_filter)]}_{year_filter}")
        except Exception:
            pass
    elif year_filter:
        filename_parts.append(year_filter)
    filename = "_".join(filename_parts) + ".csv"

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    def peso(value):
        return f"PHP {float(value):,.2f}"

    writer = csv.writer(response)
    writer.writerow([
        "Tenant Name", "Email", "Unit", "Billing Month", "Due Date",
        "Base Rent", "Water Amount", "Interest", "Total Due",
        "Rent Paid", "Water Paid", "Total Balance",
        "Status", "Payment Reference", "Paid At",
    ])

    for b in bills:
        try:
            tp = b.lease.tenant.tenantprofile
            name = f"{tp.first_name} {tp.last_name}"
        except Exception:
            name = b.lease.tenant.email
        writer.writerow([
            _safe_csv_value(name),
            _safe_csv_value(b.lease.tenant.email),
            _safe_csv_value(b.lease.unit.number),
            b.billing_month.strftime("%B %Y"),
            b.due_date.strftime("%Y-%m-%d") if b.due_date else "",
            peso(b.base_rent),
            peso(b.water_amount),
            peso(b.interest),
            peso(b.total_due),
            peso(b.rent_paid),
            peso(b.water_paid),
            peso(b.total_balance),
            _safe_csv_value(b.get_status_display()),
            _safe_csv_value(b.payment_reference or ""),
            b.paid_at.strftime("%Y-%m-%d %H:%M") if b.paid_at else "",
        ])

    return response


@admin_required
def admin_billing(request):
    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    month_filter = request.GET.get("month", "").strip()
    year_filter = request.GET.get("year", "").strip()
    active_tab = request.GET.get("tab", "active")
    if active_tab not in ("active", "upcoming"):
        active_tab = "active"

    today = date.today()
    current_month = today.replace(day=1)

    base_qs = MonthlyBill.objects.select_related("lease", "lease__unit", "lease__tenant", "lease__tenant__tenantprofile")
    if q:
        for term in q.split():
            base_qs = base_qs.filter(
                Q(lease__tenant__email__icontains=term) |
                Q(lease__tenant__username__icontains=term) |
                Q(lease__tenant__tenantprofile__first_name__icontains=term) |
                Q(lease__tenant__tenantprofile__last_name__icontains=term) |
                Q(lease__unit__number__icontains=term) |
                Q(payment_reference__icontains=term)
            )
    if month_filter and month_filter.isdigit():
        base_qs = base_qs.filter(billing_month__month=int(month_filter))
    if year_filter and year_filter.isdigit():
        base_qs = base_qs.filter(billing_month__year=int(year_filter))

    stats = base_qs.aggregate(
        paid_count=Count("id", filter=Q(status="PAID")),
        unpaid_count=Count(
            "id",
            filter=Q(status__in=["UNPAID", "PARTIALLY_PAID"], billing_month__lte=current_month),
        ),
        overdue_count=Count(
            "id",
            filter=Q(status__in=["UNPAID", "PARTIALLY_PAID"], billing_month__lt=current_month),
        ),
        partial_count=Count("id", filter=Q(status="PARTIALLY_PAID")),
        upcoming_count=Count(
            "id",
            filter=Q(billing_month__gt=current_month) & ~Q(status="PAID"),
        ),
    )
    paid_count = stats["paid_count"] or 0
    unpaid_count = stats["unpaid_count"] or 0
    overdue_count = stats["overdue_count"] or 0
    partial_count = stats["partial_count"] or 0
    upcoming_count = stats["upcoming_count"] or 0

    if active_tab == "active":
        display_qs = base_qs.filter(
            Q(billing_month__lte=current_month) | Q(status__in=("PAID", "PARTIALLY_PAID"))
        )
        if status_filter == "UNPAID":
            display_qs = display_qs.filter(status__in=("UNPAID", "PARTIALLY_PAID"))
        elif status_filter == "OVERDUE":
            display_qs = display_qs.filter(
                status__in=("UNPAID", "PARTIALLY_PAID"),
                billing_month__lt=current_month,
            )
        elif status_filter == "PARTIAL":
            display_qs = display_qs.filter(status="PARTIALLY_PAID")
        elif status_filter == "PAID":
            display_qs = display_qs.filter(status="PAID")
    else:
        display_qs = base_qs.filter(billing_month__gt=current_month).exclude(status="PAID")

    active_count = display_qs.count()
    paginator = Paginator(display_qs.order_by("-billing_month"), 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    current_year = timezone.now().year
    month_choices = [
        (1, "January"), (2, "February"), (3, "March"), (4, "April"),
        (5, "May"), (6, "June"), (7, "July"), (8, "August"),
        (9, "September"), (10, "October"), (11, "November"), (12, "December"),
    ]
    year_choices = list(range(current_year - 3, current_year + 2))

    return render(request, "admin_portal/billing.html", {
        "page_obj": page_obj,
        "active_tab": active_tab,
        "q": q,
        "status_filter": status_filter,
        "month_filter": month_filter,
        "year_filter": year_filter,
        "month_choices": month_choices,
        "year_choices": year_choices,
        "paid_count": paid_count,
        "unpaid_count": unpaid_count,
        "overdue_count": overdue_count,
        "partial_count": partial_count,
        "upcoming_count": upcoming_count,
        "active_count": active_count,
    })


@admin_required
def admin_delete_bill(request, bill_id: int):
    bill = get_object_or_404(MonthlyBill.objects.select_related("lease", "lease__tenant", "lease__unit"), pk=bill_id)
    if request.method == "POST":
        if not admin_password_verified(request):
            return render_admin_password_confirm(
                request,
                title="Delete Billing Record",
                message=f"Delete billing record for {bill.lease.tenant.email} / {bill.lease.unit.number} / {bill.billing_month}? Linked payment history references will be cleaned up.",
                post_url=reverse("admin_delete_bill", args=[bill.id]),
                back_url=reverse("admin_billing"),
                error="Incorrect admin password. Billing record was not deleted.",
            )
        with transaction.atomic():
            bill.delete()
        return redirect("admin_billing")
    return render_admin_password_confirm(
        request,
        title="Delete Billing Record",
        message=f"Delete billing record for {bill.lease.tenant.email} / {bill.lease.unit.number} / {bill.billing_month}? Linked payment history references will be cleaned up.",
        post_url=reverse("admin_delete_bill", args=[bill.id]),
        back_url=reverse("admin_billing"),
    )


@admin_required
def admin_send_bill_warning(request, bill_id: int):
    bill = get_object_or_404(
        MonthlyBill.objects.select_related("lease", "lease__tenant", "lease__unit"),
        pk=bill_id
    )
    tenant = bill.lease.tenant
    unit = bill.lease.unit

    try:
        tp = tenant.tenantprofile
        name = f"{tp.first_name} {tp.last_name}"
    except Exception:
        name = tenant.email

    billing_month = bill.billing_month.strftime("%B %Y")
    balance = float(bill.total_balance) if bill.total_balance else float(bill.total_due)
    due_date = bill.due_date.strftime("%B %d, %Y") if bill.due_date else "N/A"

    subject = f"[REALESTATE360+] Billing Reminder - {billing_month}"
    message = (
        f"Dear {name},\n\n"
        f"This is a friendly reminder that your bill for {billing_month} is still outstanding.\n\n"
        f"  Unit:          {unit.number}\n"
        f"  Billing Month: {billing_month}\n"
        f"  Due Date:      {due_date}\n"
        f"  Amount Due:    PHP {balance:,.2f}\n\n"
        f"Please settle your balance at your earliest convenience to avoid any penalties.\n\n"
        f"If you have already made your payment, please disregard this notice.\n\n"
        f"Thank you,\n"
        f"REALESTATE360+ Administration"
    )

    try:
        sent = rental_services.send_email_via_resend(tenant.email, subject, message)
        if not sent:
            raise RuntimeError("Resend is not configured or rejected the email.")
        messages.success(request, f"Warning email sent to {tenant.email} for {billing_month}.")
    except Exception as e:
        messages.error(request, f"Failed to send email: {e}")

    return redirect(f"{reverse('admin_billing')}?tab=active")
