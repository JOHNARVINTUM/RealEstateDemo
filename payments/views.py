from datetime import datetime
from decimal import Decimal
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from django.contrib import messages

from accounts.decorators import tenant_required
from .models import ManualPayment
from .paymongo import retrieve_checkout_session
logger = logging.getLogger(__name__)

from .paymongo_workflow import (
    build_paymongo_checkout_metadata,
    build_paymongo_success_url,
    create_f2f_cash_payment_request,
    create_paymongo_checkout_session_or_error,
    get_paymongo_admin_success_context,
    get_paymongo_session_updates,
    get_recent_pending_manual_payment,
    get_pending_paymongo_payment,
    parse_paymongo_webhook_payload,
    process_paymongo_webhook_payload,
    validate_paymongo_webhook_request,
    upsert_pending_paymongo_checkout_payment,
    render_paymongo_tenant_success,
)
from .scheduling import OFFICE_HOURS_LABEL, f2f_time_slots, is_office_schedule
from rentals.models import Lease, Notification


def _f2f_cash_context(**overrides):
    context = {
        "office_time_slots": f2f_time_slots(),
        "office_hours_label": OFFICE_HOURS_LABEL,
        "back_url": reverse("tenant_pay_advance"),
    }
    context.update(overrides)
    return context


@tenant_required
@require_http_methods(["GET", "POST"])
def manual_gcash_payment(request):
    if request.method == "POST":
        # 1. Catch ALL the data submitted by the form (including the hidden fields)
        reference_code = (request.POST.get("reference_code") or "").strip()
        amount_to_pay = request.POST.get("amount", "0.00")
        bill_ids = request.POST.get("bill_ids", "")

        # 2. Handle missing reference code
        if not reference_code:
            return render(request, "payments/manual_gcash.html", {
                "error": "GCash reference number is required.",
                "gcash_number": getattr(settings, "GCASH_NUMBER", "09XX-XXX-XXXX"),
                "gcash_name": getattr(settings, "GCASH_NAME", "STA. MARIA REALTY"),
                "amount_to_pay": amount_to_pay,
                "bill_ids": bill_ids,
            })

        # 3. FIX: Save the transaction WITH the required bill_ids and payment_type
        payment_type = request.POST.get("payment_type", "full")

        # Prevent duplicate submissions (same user + bills within 2 minutes)
        if get_recent_pending_manual_payment(
            user=request.user,
            bill_ids=bill_ids,
            payment_methods=["GCASH"],
        ):
            messages.info(request, "You already have a pending payment for these bills. Please wait for admin verification.")
            return redirect("tenant_dashboard")

        payment = ManualPayment.objects.create(
            user=request.user,
            reference_code=reference_code,
            bill_ids=bill_ids,  # This stops the NOT NULL IntegrityError
            payment_type=payment_type,
            amount=amount_to_pay,
        )
        
        # Create real-time notification for admin about new payment
        try:
            # Build the approval URL for the notification
            from django.urls import reverse
            approval_url = reverse('admin_payments')
            
            notification = Notification.create_notification(
                title=f"New Payment Received",
                message=f"{request.user.email} submitted a payment of ₱{amount_to_pay} with reference code {reference_code}. Please review and approve this payment.",
                notification_type='PAYMENT',
                recipient_type='ADMIN',
                related_tenant=request.user
            )
        except Exception as e:
            # Don't block payment submission if notification fails
            logger.exception(f"Failed to create payment notification: {e}")
        
        messages.success(request, "Payment submitted! Please wait for admin verification.")
        return redirect("tenant_dashboard")

    # 4. Handle the initial page load (GET request)
    amount_to_pay = request.GET.get("amount", "0.00")
    bill_ids = request.GET.get("bill_ids", "")
    payment_type = request.GET.get("payment_type", "full")

    return render(request, "payments/manual_gcash.html", {
        "gcash_number": getattr(settings, "GCASH_NUMBER", "09XX-XXX-XXXX"),
        "gcash_name": getattr(settings, "GCASH_NAME", "STA. MARIA REALTY"),
        "amount_to_pay": amount_to_pay,
        "bill_ids": bill_ids,
        "payment_type": payment_type,
    })


@tenant_required
@require_http_methods(["GET", "POST"])
def f2f_cash_payment(request):
    """Face-to-Face cash payment scheduling view."""
    if request.method == "POST":
        amount_to_pay = request.POST.get("amount", "0.00")
        bill_ids = request.POST.get("bill_ids", "")
        payment_type = request.POST.get("payment_type", "full")
        preferred_date = request.POST.get("preferred_date", "")
        preferred_time = request.POST.get("preferred_time", "")
        tenant_note = request.POST.get("tenant_note", "").strip()

        # Validate required fields
        if not preferred_date:
            return render(request, "payments/f2f_cash.html", _f2f_cash_context(
                error="Please select a preferred date for the cash payment.",
                amount_to_pay=amount_to_pay,
                bill_ids=bill_ids,
                payment_type=payment_type,
                preferred_date=preferred_date,
                preferred_time=preferred_time,
                tenant_note=tenant_note,
            ))

        # Parse date and time
        parsed_date = None
        parsed_time = None
        try:
            if preferred_date:
                parsed_date = datetime.strptime(preferred_date, "%Y-%m-%d").date()
            if preferred_time:
                parsed_time = datetime.strptime(preferred_time, "%H:%M").time()
        except ValueError:
            return render(request, "payments/f2f_cash.html", _f2f_cash_context(
                error="Invalid date or time format.",
                amount_to_pay=amount_to_pay,
                bill_ids=bill_ids,
                payment_type=payment_type,
                preferred_date=preferred_date,
                preferred_time=preferred_time,
                tenant_note=tenant_note,
            ))

        is_valid_schedule, schedule_error = is_office_schedule(parsed_date, parsed_time)
        if not is_valid_schedule:
            return render(request, "payments/f2f_cash.html", _f2f_cash_context(
                error=schedule_error,
                amount_to_pay=amount_to_pay,
                bill_ids=bill_ids,
                payment_type=payment_type,
                preferred_date=preferred_date,
                preferred_time=preferred_time,
                tenant_note=tenant_note,
            ))

        payment, duplicate_reason = create_f2f_cash_payment_request(
            user=request.user,
            amount=amount_to_pay,
            bill_ids=bill_ids,
            payment_type=payment_type,
            preferred_date=parsed_date,
            preferred_time=parsed_time,
            tenant_note=tenant_note,
        )
        if duplicate_reason == "duplicate":
            messages.info(request, "You already have a pending cash payment for these bills. Please wait for admin confirmation.")
            return redirect("tenant_dashboard")

        # Create notification for admin
        try:
            schedule_info = f"on {parsed_date.strftime('%b %d, %Y')}" if parsed_date else ""
            if parsed_time:
                schedule_info += f" at {parsed_time.strftime('%I:%M %p')}"
            Notification.create_notification(
                title="Cash Payment Scheduled",
                message=(
                    f"{request.user.email} requested F2F cash payment of \u20b1{amount_to_pay} {schedule_info}. "
                    f"Reference: {payment.reference_code}. Please confirm availability."
                ),
                notification_type='PAYMENT',
                recipient_type='ADMIN',
                related_tenant=request.user
            )
        except Exception as e:
            import logging
            logging.exception(f"Failed to create F2F notification: {e}")

        messages.success(request, "Cash payment request submitted! Please wait for admin to confirm your schedule.")
        return redirect("tenant_dashboard")

    # GET request - show form
    amount_to_pay = request.GET.get("amount", "0.00")
    bill_ids = request.GET.get("bill_ids", "")
    payment_type = request.GET.get("payment_type", "full")

    return render(request, "payments/f2f_cash.html", _f2f_cash_context(
        amount_to_pay=amount_to_pay,
        bill_ids=bill_ids,
        payment_type=payment_type,
    ))


# ─────────────────────────────────────────────────────────────────────────────
# PayMongo Checkout Views
# ─────────────────────────────────────────────────────────────────────────────

@tenant_required
@require_http_methods(["GET"])
def paymongo_checkout(request):
    """
    Create a PayMongo Checkout Session and redirect tenant to the hosted page.
    Query params: amount, bill_ids, payment_type
    """
    amount_str = request.GET.get("amount", "0")
    bill_ids = request.GET.get("bill_ids", "")
    payment_type = request.GET.get("payment_type", "full")

    try:
        amount = Decimal(amount_str)
    except Exception:
        messages.error(request, "Invalid payment amount.")
        return redirect("tenant_pay_advance")

    if amount <= 0:
        messages.error(request, "Payment amount must be greater than zero.")
        return redirect("tenant_pay_advance")

    # Build description
    type_label = {"full": "Full Payment", "rent_only": "Rent Only", "water_only": "Water Only"}.get(payment_type, "Payment")
    description = f"REALESTATE360+ {type_label} - {request.user.email}"

    # Build cancel URL (success URL needs session ID, built after creation)
    base_url = request.build_absolute_uri("/")[:-1]  # e.g. http://localhost:8000
    # Add cancelled flag so we can detect when user returns without paying
    cancel_url = base_url + reverse("tenant_pay_advance") + "?cancelled=1"

    metadata = build_paymongo_checkout_metadata(
        user=request.user,
        bill_ids=bill_ids,
        payment_type=payment_type,
        amount=amount,
    )

    # First pass: create session with a placeholder success_url
    # PayMongo does NOT template-substitute variables in success_url,
    # so we embed the session ID ourselves after creation.
    placeholder_success = build_paymongo_success_url(base_url)

    result, error_message = create_paymongo_checkout_session_or_error(
        amount=amount,
        description=description,
        metadata=metadata,
        success_url=placeholder_success,
        cancel_url=cancel_url,
    )

    if error_message:
        messages.error(request, error_message)
        if "not configured" in error_message.lower():
            logger.error("PayMongo attempted but API keys not configured in settings/.env")
        return redirect("tenant_pay_advance")

    payment = upsert_pending_paymongo_checkout_payment(
        user=request.user,
        bill_ids=bill_ids,
        payment_type=payment_type,
        amount=amount,
        checkout_session_id=result["checkout_session_id"],
        checkout_url=result["checkout_url"],
    )

    # Redirect tenant to PayMongo's hosted checkout page
    return redirect(result["checkout_url"])


@login_required
def paymongo_success(request):
    """
    Landing page after successful PayMongo checkout.
    Finds the most recent PENDING PayMongo payment for this user,
    polls the session to confirm, and auto-approves.
    Redirects admin users to admin success page, tenants to tenant success page.
    """
    # Check if admin user
    is_admin = getattr(request.user, "role", "") == "ADMIN" or request.user.is_superuser
    
    session_id = request.GET.get("session_id", "").strip()
    payment = get_pending_paymongo_payment(request.user, session_id)

    if not payment:
        if is_admin:
            messages.info(request, "Payment received. The lease will be activated shortly.")
            return redirect("admin_dashboard")
        else:
            messages.info(request, "Payment received. Your bills will be updated shortly.")
            return redirect("tenant_dashboard")

    session_id = payment.checkout_session_id

    session_data = retrieve_checkout_session(session_id)
    payment_approved = get_paymongo_session_updates(payment, session_data)
    
    # For admin users, render admin success page with tenant welcome
    if is_admin:
        return render(request, "admin_portal/paymongo_success.html", get_paymongo_admin_success_context(payment))

    return render_paymongo_tenant_success(request, payment, payment_approved)


@login_required
@require_http_methods(["GET"])
def admin_paymongo_checkout_generate(request):
    """
    Simple admin endpoint to generate PayMongo checkout for move-in.
    Creates payment record and checkout session, then redirects to PayMongo.
    """
    amount_str = request.GET.get("amount", "0")
    tenant_id = request.GET.get("tenant_id", "")
    lease_id = request.GET.get("lease_id", "")

    try:
        amount = Decimal(amount_str)
    except Exception:
        messages.error(request, "Invalid amount")
        return redirect("admin_dashboard")

    if amount <= 0:
        messages.error(request, "Amount must be greater than zero")
        return redirect("admin_dashboard")

    lease = None
    if lease_id:
        lease = Lease.objects.select_related("tenant").filter(pk=lease_id).first()
    if not lease and tenant_id:
        lease = (
            Lease.objects.select_related("tenant")
            .filter(tenant_id=tenant_id, status=Lease.STATUS_PENDING_PAYMENT)
            .order_by("-created_at")
            .first()
        )

    if not lease or not lease.tenant:
        messages.error(request, "A tenant lease is required before generating a move-in checkout.")
        return redirect("admin_dashboard")

    tenant_user = lease.tenant

    base_url = request.build_absolute_uri("/")[:-1]

    # Set cancel URL to admin lease payment page if lease_id provided, else admin dashboard
    if lease_id:
        cancel_url = base_url + reverse("admin_lease_payment", args=[lease_id])
    else:
        cancel_url = base_url + reverse("admin_dashboard")

    metadata = build_paymongo_checkout_metadata(
        user=tenant_user,
        bill_ids="",
        payment_type="move_in",
        amount=amount,
        extra={
            "generated_by_admin": str(request.user.id),
            "tenant_id": str(tenant_user.id),
            "lease_id": str(lease.id),
        },
    )

    result, error_message = create_paymongo_checkout_session_or_error(
        amount=amount,
        description="REALESTATE360+ Move-in Payment",
        metadata=metadata,
        success_url=build_paymongo_success_url(base_url),
        cancel_url=cancel_url,
    )

    if error_message:
        messages.error(request, error_message)
        return redirect("admin_dashboard")

    # Create payment record with PENDING status
    payment = ManualPayment.objects.create(
        user=tenant_user,
        payment_type="move_in",
        payment_method="PAYMONGO",
        amount=amount,
        reference_code=f"REF-PM-{result['checkout_session_id'][-8:].upper()}",
        checkout_session_id=result["checkout_session_id"],
        checkout_url=result["checkout_url"],
        status="PENDING",
        tenant_note=f"Admin-generated checkout for move-in payment",
        metadata=metadata,
    )

    logger.info(
        "Admin %s generated PayMongo checkout %s for tenant %s amount %s",
        request.user.id,
        payment.id,
        tenant_user.id,
        amount,
    )

    # Redirect to PayMongo for payment
    return redirect(result["checkout_url"])


@csrf_exempt
@require_POST
def paymongo_webhook(request):
    """
    Webhook endpoint for PayMongo events.
    Handles checkout_session.payment.paid event.
    Auto-approves the payment and notifies admin.
    
    Security: Verifies PayMongo signature before processing.
    """
    payload_body = request.body
    signature_header = request.headers.get('Paymongo-Signature', '')
    webhook_secret = getattr(settings, 'PAYMONGO_WEBHOOK_SECRET', '')

    signature_error = validate_paymongo_webhook_request(
        payload_body,
        signature_header,
        webhook_secret,
        settings.IS_PRODUCTION,
    )
    if signature_error:
        return signature_error

    payload, payload_error = parse_paymongo_webhook_payload(request)
    if payload_error:
        return payload_error

    return process_paymongo_webhook_payload(payload)
