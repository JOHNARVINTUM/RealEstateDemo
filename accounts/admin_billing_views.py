from datetime import date

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone as dj_timezone
from django.utils import timezone
from django.db.models import Q

from billing.models import MonthlyBill
from billing.services import set_bill_status

from .admin_portal_views import admin_required, admin_password_verified, render_admin_password_confirm


@admin_required
def admin_mark_bill_paid(request, bill_id: int):
    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    if request.method == "POST":
        set_bill_status(bill, status="PAID", paid_at=dj_timezone.now())
        return redirect("admin_billing")
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
            name,
            b.lease.tenant.email,
            b.lease.unit.number,
            b.billing_month.strftime("%B %Y"),
            b.due_date.strftime("%Y-%m-%d") if b.due_date else "",
            peso(b.base_rent),
            peso(b.water_amount),
            peso(b.interest),
            peso(b.total_due),
            peso(b.rent_paid),
            peso(b.water_paid),
            peso(b.total_balance),
            b.get_status_display(),
            b.payment_reference or "",
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

    stats_qs = base_qs
    paid_count = stats_qs.filter(status="PAID").count()
    unpaid_count = stats_qs.filter(
        status__in=["UNPAID", "PARTIALLY_PAID"],
        billing_month__lte=current_month
    ).count()
    overdue_count = stats_qs.filter(
        status__in=["UNPAID", "PARTIALLY_PAID"],
        billing_month__lt=current_month
    ).count()
    partial_count = stats_qs.filter(status="PARTIALLY_PAID").count()
    upcoming_count = stats_qs.filter(
        billing_month__gt=current_month
    ).count()

    if active_tab == "active":
        display_qs = base_qs.filter(billing_month__lte=current_month)
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
        display_qs = base_qs.filter(billing_month__gt=current_month)

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
        import resend
        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send({
            'from': 'REALESTATE360+ <noreply@realestate360.site>',
            'to': [tenant.email],
            'subject': subject,
            'text': message,
        })
        messages.success(request, f"Warning email sent to {tenant.email} for {billing_month}.")
    except Exception as e:
        messages.error(request, f"Failed to send email: {e}")

    return redirect(f"{reverse('admin_billing')}?tab=active")
