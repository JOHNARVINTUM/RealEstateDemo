from datetime import date

from django.db.models import Sum, Q
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone

from accounts.decorators import admin_required
from rentals.models import Lease, Unit, TenantProfile
from billing.models import MonthlyBill
from payments.models import ManualPayment
from maintenance.models import MaintenanceRequest
from announcements.models import Announcement

from .admin_portal_forms import TenantProfileForm, AnnouncementForm


@admin_required
def admin_dashboard(request):
    total_tenants = Lease.objects.filter(is_active=True).values("tenant").distinct().count()
    occupied_units = Lease.objects.filter(is_active=True).count()
    vacant_units = Unit.objects.filter(is_active=True).count() - occupied_units

    today = timezone.now().date()
    month_start = date(today.year, today.month, 1)
    total_revenue = (
        MonthlyBill.objects.filter(status="PAID", billing_month=month_start)
        .aggregate(total=Sum("total_due"))["total"] or 0
    )
    overdue_payments = MonthlyBill.objects.filter(status="UNPAID", due_date__lt=today).count()

    return render(request, "admin_portal/dashboard.html", {
        "total_tenants": total_tenants,
        "occupied_units": occupied_units,
        "vacant_units": max(vacant_units, 0),
        "total_revenue": total_revenue,
        "overdue_payments": overdue_payments,
    })


@admin_required
def admin_tenants(request):
    q = request.GET.get("q", "").strip()

    tenants = TenantProfile.objects.select_related("user")
    if q:
        tenants = tenants.filter(
            Q(full_name__icontains=q) |
            Q(contact_no__icontains=q) |
            Q(user__email__icontains=q) |
            Q(user__username__icontains=q)
        )

    tenants = tenants.order_by("full_name")[:500]
    return render(request, "admin_portal/tenants.html", {"tenants": tenants, "q": q})


@admin_required
def admin_tenant_detail(request, tenant_id: int):
    tenant = get_object_or_404(TenantProfile.objects.select_related("user"), pk=tenant_id)
    leases = Lease.objects.select_related("unit", "tenant").filter(tenant=tenant.user).order_by("-start_date")
    return render(request, "admin_portal/tenant_detail.html", {"tenant": tenant, "leases": leases})


@admin_required
def admin_create_tenant_profile(request):
    """
    Admin portal: create a TenantProfile row (linked to an existing User).
    """
    form = TenantProfileForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("admin_tenants")

    return render(request, "admin_portal/form.html", {
        "title": "Add Tenant",
        "form": form,
        "back_url": reverse("admin_tenants"),
    })


@admin_required
def admin_billing(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    bills = MonthlyBill.objects.select_related("lease", "lease__unit", "lease__tenant")

    if status in ("PAID", "UNPAID"):
        bills = bills.filter(status=status)

    if q:
        bills = bills.filter(
            Q(lease__tenant__email__icontains=q) |
            Q(lease__unit__number__icontains=q) |
            Q(payment_reference__icontains=q)
        )

    bills = bills.order_by("-billing_month")[:500]
    return render(request, "admin_portal/billing.html", {"bills": bills, "q": q, "status": status})


@admin_required
def admin_payments(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    payments = ManualPayment.objects.select_related("user")
    if status in ("PENDING", "APPROVED", "REJECTED"):
        payments = payments.filter(status=status)
    if q:
        payments = payments.filter(
            Q(user__email__icontains=q) |
            Q(reference_code__icontains=q) |
            Q(bill_ids__icontains=q)
        )

    payments = payments.order_by("-created_at")[:500]
    return render(request, "admin_portal/payments.html", {"payments": payments, "q": q, "status": status})


@admin_required
def admin_maintenance(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    reqs = MaintenanceRequest.objects.select_related("lease", "lease__unit", "lease__tenant")

    if status:
        reqs = reqs.filter(status=status)

    if q:
        reqs = reqs.filter(
            Q(lease__tenant__email__icontains=q) |
            Q(lease__unit__number__icontains=q) |
            Q(description__icontains=q)
        )

    reqs = reqs.order_by("-created_at")[:500]
    return render(request, "admin_portal/maintenance.html", {"reqs": reqs, "q": q, "status": status})


@admin_required
def admin_announcements(request):
    q = request.GET.get("q", "").strip()
    items = Announcement.objects.all()

    # FIX: model field is "body", not "content"
    if q:
        items = items.filter(Q(title__icontains=q) | Q(body__icontains=q))

    items = items.order_by("-created_at")[:200]
    return render(request, "admin_portal/announcements.html", {"items": items, "q": q})


@admin_required
def admin_create_announcement(request):
    form = AnnouncementForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save(user=request.user)  # uses your custom save(user=...)
        return redirect("admin_announcements")

    return render(request, "admin_portal/form.html", {
        "title": "Add Announcement",
        "form": form,
        "back_url": reverse("admin_announcements"),
    })




