import logging

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from billing.models import MonthlyBill
from billing.services import approve_manual_payment, reject_manual_payment
from payments.models import ManualPayment
from rentals.models import Lease
from rentals.services import repair_historical_move_in_payment

from .admin_portal_views import admin_required, admin_password_verified, render_admin_password_confirm

logger = logging.getLogger(__name__)


def _tenant_display_name(user):
    if hasattr(user, "tenantprofile"):
        full_name = getattr(user.tenantprofile, "full_name", "").strip()
        if full_name:
            return full_name
    return user.email


@admin_required
def admin_approve_payment(request, payment_id: int):
    p = get_object_or_404(ManualPayment, pk=payment_id)
    if request.method == "POST":
        try:
            approve_manual_payment(p)
            messages.success(request, f"Payment {p.reference_code} approved successfully.")

            try:
                from rentals.services import send_email_via_resend
                tenant_name = _tenant_display_name(p.user)
                payment_type_label = {'full': 'Full Payment', 'rent_only': 'Rent Only', 'water_only': 'Water Only'}.get(p.payment_type, 'Payment')
                send_email_via_resend(
                    to_email=p.user.email,
                    subject="[REALESTATE360+] Payment Approved – Receipt Confirmation",
                    message=(
                        f"Dear {tenant_name},\n\n"
                        f"Your payment has been approved and recorded.\n\n"
                        f"  Reference No.: {p.reference_code}\n"
                        f"  Payment Type:  {payment_type_label}\n"
                        f"  Amount:        PHP {p.amount:,.2f}\n"
                        f"  Method:        {p.get_payment_method_display() if hasattr(p, 'get_payment_method_display') else p.payment_method}\n"
                        f"  Status:        APPROVED\n\n"
                        f"Your billing statement has been updated. You can view your payment history in your tenant portal.\n\n"
                        f"Thank you for your payment!\n\n"
                        f"REALESTATE360+ Administration"
                    )
                )
            except Exception as e:
                logger.exception(f"Failed to send payment confirmation email: {e}")

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
    p = get_object_or_404(ManualPayment, pk=payment_id)
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
    p = get_object_or_404(ManualPayment, pk=payment_id)
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
    p = get_object_or_404(ManualPayment, pk=payment_id)
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
                message=f"Your face-to-face cash payment appointment has been confirmed.\n\nAmount: ₱{p.amount:,.2f}\nScheduled: {schedule_info}\n\nPlease bring the exact amount. See you then!",
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
        "message": f"Confirm cash payment appointment for {p.user.email}?\n\nAmount: ₱{p.amount:,.2f}\nScheduled: {schedule_info}\n\nTenant will be notified that the appointment is confirmed.",
        "post_url": reverse("admin_confirm_schedule", args=[p.id]),
        "back_url": reverse("admin_payments"),
    })


@admin_required
def admin_payments(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    method = request.GET.get("method", "").strip()

    payments = ManualPayment.objects.select_related("user")
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
    payments = filtered_payments[:500]

    status_counts = filtered_payments.aggregate(
        pending_count=Count("id", filter=Q(status="PENDING")),
        approved_count=Count("id", filter=Q(status="APPROVED")),
        rejected_count=Count("id", filter=Q(status="REJECTED")),
    )
    pending_count = status_counts["pending_count"] or 0
    approved_count = status_counts["approved_count"] or 0
    rejected_count = status_counts["rejected_count"] or 0

    paginator = Paginator(payments, 10)
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

    bills_by_id = {
        bill.id: bill
        for bill in MonthlyBill.objects.filter(pk__in=page_bill_ids)
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
                p.affected_months = ", ".join(month.strftime("%b %Y") for month in months) if months else "—"
            else:
                p.bill_components = '—'
                p.affected_months = '—'
        except Exception:
            p.bill_components = '—'
            p.affected_months = '—'

    return render(request, "admin_portal/payments.html", {
        "page_obj": page_obj,
        "q": q,
        "status": status,
        "method": method,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
    })


@admin_required
def admin_delete_payment(request, payment_id: int):
    payment = get_object_or_404(ManualPayment.objects.select_related("user"), pk=payment_id)
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

    payment = get_object_or_404(ManualPayment.objects.select_related("user"), pk=payment_id)
    is_settled_payment = payment.status == "APPROVED"
    tenant_display_name = _tenant_display_name(payment.user)

    payment_type_choices = [
        ("rent_only", "Rent Only"),
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
                if metadata:
                    metadata = dict(metadata)
                    metadata["payment_type"] = new_payment_type
                    payment.metadata = metadata
                    payment.save(update_fields=["payment_type", "metadata"])
                else:
                    payment.save(update_fields=["payment_type"])
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
            pay_penalty = 0
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
