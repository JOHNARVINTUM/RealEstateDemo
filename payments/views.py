import hashlib
import hmac
import json
from datetime import datetime
from decimal import Decimal
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from django.contrib import messages

from .models import ManualPayment
from .paymongo import create_checkout_session, retrieve_checkout_session, verify_webhook_signature
from rentals.models import Notification

logger = logging.getLogger(__name__)

@login_required
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
        from django.utils import timezone as tz
        from datetime import timedelta
        recent_cutoff = tz.now() - timedelta(minutes=2)
        if ManualPayment.objects.filter(
            user=request.user, bill_ids=bill_ids, status="PENDING",
            created_at__gte=recent_cutoff
        ).exists():
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


@login_required
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
            return render(request, "payments/f2f_cash.html", {
                "error": "Please select a preferred date for the cash payment.",
                "amount_to_pay": amount_to_pay,
                "bill_ids": bill_ids,
                "payment_type": payment_type,
                "preferred_date": preferred_date,
                "preferred_time": preferred_time,
                "tenant_note": tenant_note,
            })

        # Parse date and time
        parsed_date = None
        parsed_time = None
        try:
            if preferred_date:
                parsed_date = datetime.strptime(preferred_date, "%Y-%m-%d").date()
            if preferred_time:
                parsed_time = datetime.strptime(preferred_time, "%H:%M").time()
        except ValueError:
            return render(request, "payments/f2f_cash.html", {
                "error": "Invalid date or time format.",
                "amount_to_pay": amount_to_pay,
                "bill_ids": bill_ids,
                "payment_type": payment_type,
                "preferred_date": preferred_date,
                "preferred_time": preferred_time,
                "tenant_note": tenant_note,
            })

        # Prevent duplicate submissions (same user + bills within 2 minutes)
        from django.utils import timezone as tz
        from datetime import timedelta
        recent_cutoff = tz.now() - timedelta(minutes=2)
        if ManualPayment.objects.filter(
            user=request.user, bill_ids=bill_ids, payment_method="CASH", status="PENDING",
            created_at__gte=recent_cutoff
        ).exists():
            messages.info(request, "You already have a pending cash payment for these bills. Please wait for admin confirmation.")
            return redirect("tenant_dashboard")

        # Create F2F payment request
        payment = ManualPayment.objects.create(
            user=request.user,
            reference_code="REF-F2F-" + datetime.now().strftime("%Y%m%d-%H%M%S"),
            bill_ids=bill_ids,
            payment_type=payment_type,
            payment_method="CASH",
            amount=amount_to_pay,
            preferred_date=parsed_date,
            preferred_time=parsed_time,
            tenant_note=tenant_note,
        )

        # Create notification for admin
        try:
            schedule_info = f"on {parsed_date.strftime('%b %d, %Y')}" if parsed_date else ""
            if parsed_time:
                schedule_info += f" at {parsed_time.strftime('%I:%M %p')}"
            Notification.create_notification(
                title="Cash Payment Scheduled",
                message=f"{request.user.email} requested F2F cash payment of ₱{amount_to_pay} {schedule_info}. Please confirm availability.",
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

    return render(request, "payments/f2f_cash.html", {
        "amount_to_pay": amount_to_pay,
        "bill_ids": bill_ids,
        "payment_type": payment_type,
    })


# ─────────────────────────────────────────────────────────────────────────────
# PayMongo Checkout Views
# ─────────────────────────────────────────────────────────────────────────────

@login_required
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

    # Convert to centavos (PayMongo expects integer centavos)
    amount_cents = int(amount * 100)

    # Build description
    type_label = {"full": "Full Payment", "rent_only": "Rent Only", "water_only": "Water Only"}.get(payment_type, "Payment")
    description = f"REALESTATE360+ {type_label} - {request.user.email}"

    # Build cancel URL (success URL needs session ID, built after creation)
    base_url = request.build_absolute_uri("/")[:-1]  # e.g. http://localhost:8000
    cancel_url = base_url + reverse("tenant_pay_advance")

    metadata = {
        "user_id": str(request.user.id),
        "bill_ids": bill_ids,
        "payment_type": payment_type,
        "amount": str(amount),
    }

    # First pass: create session with a placeholder success_url
    # PayMongo does NOT template-substitute variables in success_url,
    # so we embed the session ID ourselves after creation.
    placeholder_success = base_url + reverse("paymongo_success")

    result = create_checkout_session(
        amount_cents=amount_cents,
        description=description,
        metadata=metadata,
        success_url=placeholder_success,
        cancel_url=cancel_url,
    )

    if not result:
        messages.error(request, "Failed to create checkout session. Please try another payment method.")
        return redirect("tenant_pay_advance")
    
    # Check for configuration error
    if isinstance(result, dict) and result.get("error"):
        error_msg = result.get("error")
        if "not configured" in error_msg.lower():
            messages.error(request, "PayMongo payment gateway is not configured. Please contact the administrator.")
            logger.error("PayMongo attempted but API keys not configured in settings/.env")
        else:
            messages.error(request, f"Payment gateway error: {error_msg}. Please try another payment method.")
        return redirect("tenant_pay_advance")

    # Create a PENDING ManualPayment record to track this
    payment = ManualPayment.objects.create(
        user=request.user,
        bill_ids=bill_ids,
        payment_type=payment_type,
        payment_method="PAYMONGO",
        amount=amount,
        reference_code=f"REF-PM-{result['checkout_session_id'][-8:].upper()}",
        checkout_session_id=result["checkout_session_id"],
        checkout_url=result["checkout_url"],
        status="PENDING",
    )

    # Redirect tenant to PayMongo's hosted checkout page
    return redirect(result["checkout_url"])


@login_required
def paymongo_success(request):
    """
    Landing page after successful PayMongo checkout.
    Finds the most recent PENDING PayMongo payment for this user,
    polls the session to confirm, and auto-approves.
    """
    # Try session_id from query param first, fall back to latest PENDING
    session_id = request.GET.get("session_id", "").strip()

    if session_id and session_id != "{checkout_session_id}":
        payment = ManualPayment.objects.filter(
            checkout_session_id=session_id,
            user=request.user,
        ).first()
    else:
        # Fallback: find the most recent PENDING PayMongo payment for this user
        payment = ManualPayment.objects.filter(
            user=request.user,
            payment_method="PAYMONGO",
            status="PENDING",
        ).order_by("-created_at").first()

    if not payment:
        messages.info(request, "Payment received. Your bills will be updated shortly.")
        return redirect("tenant_dashboard")

    session_id = payment.checkout_session_id

    # Retrieve session from PayMongo to confirm payment
    session_data = retrieve_checkout_session(session_id)
    if session_data:
        attrs = session_data.get("attributes", {})
        payments_list = attrs.get("payments", [])

        if payments_list and payment.status != "APPROVED":
            # Extract payment info
            pm_payment = payments_list[0]
            pm_attrs = pm_payment.get("attributes", {})
            paid_via = pm_attrs.get("source", {}).get("type", "unknown")
            paymongo_payment_id = pm_payment.get("id", "")

            payment.paymongo_payment_id = paymongo_payment_id
            payment.paid_via = paid_via
            payment.save(update_fields=["paymongo_payment_id", "paid_via"])

            # Auto-approve the payment
            _auto_approve_paymongo_payment(payment)

            # Refresh from DB
            payment.refresh_from_db()

    return render(request, "payments/paymongo_success.html", {
        "payment": payment,
    })


@login_required
@require_http_methods(["GET", "POST"])
def admin_paymongo_checkout_generate(request):
    """
    Admin endpoint to generate a PayMongo checkout for a tenant.
    Returns JSON with checkout URL for admin to share with tenant.
    Used in lease creation move-in payment flow.
    """
    # Only allow admin users
    if not (getattr(request.user, "role", "") == "ADMIN" or request.user.is_superuser):
        return JsonResponse({"error": "Admin access required"}, status=403)
    
    amount_str = request.GET.get("amount", "0")
    tenant_id = request.GET.get("tenant_id", "")
    payment_type = request.GET.get("payment_type", "move_in")
    
    try:
        amount = Decimal(amount_str)
    except Exception:
        return JsonResponse({"error": "Invalid amount"}, status=400)
    
    if amount <= 0:
        return JsonResponse({"error": "Amount must be greater than zero"}, status=400)
    
    # Convert to centavos (PayMongo expects integer centavos)
    amount_cents = int(amount * 100)
    
    # Build description
    description = f"REALESTATE360+ Move-in Payment"
    
    # Build URLs - success will be tenant dashboard
    base_url = request.build_absolute_uri("/")[:-1]
    success_url = base_url + reverse("paymongo_success")
    cancel_url = base_url + reverse("tenant_dashboard")
    
    # Metadata for tracking
    metadata = {
        "payment_type": payment_type,
        "amount": str(amount),
        "generated_by_admin": str(request.user.id),
    }
    if tenant_id:
        metadata["tenant_id"] = tenant_id
    
    result = create_checkout_session(
        amount_cents=amount_cents,
        description=description,
        metadata=metadata,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    
    if not result:
        return JsonResponse({"error": "Failed to create checkout session"}, status=500)
    
    # Check for configuration error
    if isinstance(result, dict) and result.get("error"):
        error_msg = result.get("error")
        if "not configured" in error_msg.lower():
            return JsonResponse({"error": "PayMongo not configured. Check PAYMONGO_SECRET_KEY in .env"}, status=503)
        return JsonResponse({"error": error_msg}, status=500)
    
    # Create a PENDING ManualPayment record (will be linked to tenant later when they pay)
    payment = ManualPayment.objects.create(
        user=request.user,  # Temporarily assigned to admin, will update on payment
        payment_type=payment_type,
        payment_method="PAYMONGO",
        amount=amount,
        reference_code=f"REF-PM-{result['checkout_session_id'][-8:].upper()}",
        checkout_session_id=result["checkout_session_id"],
        checkout_url=result["checkout_url"],
        status="PENDING",
        notes=f"Admin-generated checkout for move-in payment",
    )
    
    logger.info(f"Admin {request.user.id} generated PayMongo checkout {payment.id} for amount {amount}")
    
    return JsonResponse({
        "checkout_url": result["checkout_url"],
        "checkout_session_id": result["checkout_session_id"],
        "payment_id": payment.id,
    })


@csrf_exempt
@require_POST
def paymongo_webhook(request):
    """
    Webhook endpoint for PayMongo events.
    Handles checkout_session.payment.paid event.
    Auto-approves the payment and notifies admin.
    
    Security: Verifies PayMongo signature before processing.
    """
    # Get raw body for signature verification (must be done before reading body)
    payload_body = request.body
    
    # Verify webhook signature
    signature_header = request.headers.get('Paymongo-Signature', '')
    webhook_secret = getattr(settings, 'PAYMONGO_WEBHOOK_SECRET', '')
    
    if not webhook_secret:
        logger.error("PAYMONGO_WEBHOOK_SECRET not configured - webhook verification disabled")
        # In production, reject webhooks if secret not configured
        if settings.IS_PRODUCTION:
            return HttpResponse("Webhook secret not configured", status=500)
    elif not verify_webhook_signature(payload_body, signature_header, webhook_secret):
        logger.warning(f"Invalid webhook signature from {request.META.get('REMOTE_ADDR')}")
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Invalid signature")
    
    try:
        payload = json.loads(payload_body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    event_type = payload.get("data", {}).get("attributes", {}).get("type", "")
    logger.info(f"PayMongo webhook received: {event_type}")

    if event_type == "checkout_session.payment.paid":
        event_data = payload["data"]["attributes"]["data"]
        attrs = event_data.get("attributes", {})
        checkout_session_id = event_data.get("id", "")

        # If the event wraps a payment inside a checkout session
        payments_list = attrs.get("payments", [])
        metadata = attrs.get("metadata", {})

        # Try to find payment by checkout_session_id
        payment = ManualPayment.objects.filter(
            checkout_session_id=checkout_session_id,
            payment_method="PAYMONGO",
        ).first()

        if not payment and metadata.get("user_id"):
            # Fallback: look by metadata
            payment = ManualPayment.objects.filter(
                user_id=metadata["user_id"],
                bill_ids=metadata.get("bill_ids", ""),
                payment_method="PAYMONGO",
                status="PENDING",
            ).first()

        if payment and payment.status != "APPROVED":
            # Extract actual payment method used
            if payments_list:
                pm_payment = payments_list[0]
                pm_attrs = pm_payment.get("attributes", {})
                payment.paid_via = pm_attrs.get("source", {}).get("type", "unknown")
                payment.paymongo_payment_id = pm_payment.get("id", "")
                payment.save(update_fields=["paid_via", "paymongo_payment_id"])

            _auto_approve_paymongo_payment(payment)
            logger.info(f"PayMongo webhook auto-approved payment {payment.id}")

    return JsonResponse({"status": "ok"})


def _auto_approve_paymongo_payment(payment):
    """
    Auto-approve a PayMongo payment: mark bills as PAID and notify admin.
    """
    from billing.services import approve_manual_payment

    if payment.status == "APPROVED":
        return

    try:
        approve_manual_payment(payment)
        logger.info(f"PayMongo payment {payment.id} auto-approved successfully")
    except Exception as e:
        logger.exception(f"Failed to auto-approve PayMongo payment {payment.id}: {e}")
        # Even if bill approval fails, mark payment as approved so we don't retry incorrectly
        payment.status = "APPROVED"
        payment.save(update_fields=["status"])

    # Notify admin about the auto-approved payment
    try:
        tenant_name = payment.user.email
        if hasattr(payment.user, 'tenantprofile'):
            tenant_name = payment.user.tenantprofile.full_name
        paid_via_display = (payment.paid_via or "online").replace("_", " ").title()

        Notification.create_notification(
            title="Online Payment Received & Auto-Approved",
            message=(
                f"{tenant_name} paid ₱{payment.amount:,.2f} via PayMongo ({paid_via_display}). "
                f"Reference: {payment.reference_code}. Bills have been automatically marked as PAID."
            ),
            notification_type='PAYMENT',
            recipient_type='ADMIN',
            related_tenant=payment.user,
        )
    except Exception as e:
        logger.exception(f"Failed to create admin notification for PayMongo payment: {e}")