from datetime import datetime
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from django.contrib import messages

from .models import ManualPayment
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
        payment = ManualPayment.objects.create(
            user=request.user,
            reference_code=reference_code,
            bill_ids=bill_ids,  # This stops the NOT NULL IntegrityError
            payment_type=payment_type,
            amount=amount_to_pay,
        )
        
        # Create real-time notification for admin about new payment
        try:
            notification = Notification.create_notification(
                title=f" New Payment Received",
                message=f" {request.user.email} submitted a payment of {amount_to_pay} with reference code {reference_code}. Please review and approve this payment.",
                notification_type='PAYMENT',
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

        # Create F2F payment request
        payment = ManualPayment.objects.create(
            user=request.user,
            reference_code="F2F-" + datetime.now().strftime("%Y%m%d-%H%M%S"),
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