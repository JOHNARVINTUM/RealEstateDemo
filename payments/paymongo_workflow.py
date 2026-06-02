import json
import logging
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.utils import timezone
from django.shortcuts import render
from django.urls import reverse

from .models import ManualPayment
from .paymongo import create_checkout_session, verify_webhook_signature
from billing.services import approve_manual_payment
from rentals.models import Notification

logger = logging.getLogger(__name__)


def _payment_metadata(payment):
    return payment.metadata if isinstance(payment.metadata, dict) else {}


def _payment_tenant_id(payment):
    return _payment_metadata(payment).get("tenant_id")


def _payment_lease_id(payment):
    return _payment_metadata(payment).get("lease_id")


def _display_name_for_user(user):
    try:
        tenant_profile = user.tenantprofile
    except Exception:
        tenant_profile = None

    if tenant_profile:
        full_name = tenant_profile.full_name.strip()
        if full_name:
            return full_name

    return user.email


def get_recent_pending_manual_payment(
    *,
    user,
    bill_ids: str,
    payment_methods=None,
    within_minutes: int = 2,
):
    cutoff = timezone.now() - timedelta(minutes=within_minutes)
    filters = {
        "user": user,
        "bill_ids": bill_ids,
        "status": "PENDING",
        "created_at__gte": cutoff,
    }
    if payment_methods:
        filters["payment_method__in"] = list(payment_methods)
    return ManualPayment.objects.filter(**filters).first()


def upsert_pending_paymongo_checkout_payment(
    *,
    user,
    bill_ids: str,
    payment_type: str,
    amount,
    checkout_session_id: str,
    checkout_url: str,
):
    existing_payment = ManualPayment.objects.filter(
        user=user,
        bill_ids=bill_ids,
        status="PENDING",
        payment_method__in=["PAYMONGO", "GCASH"],
    ).first()

    if existing_payment:
        logger.info(f"Updating existing payment {existing_payment.id} with new PayMongo session")
        existing_payment.checkout_session_id = checkout_session_id
        existing_payment.checkout_url = checkout_url
        existing_payment.reference_code = f"REF-PM-{checkout_session_id[-8:].upper()}"
        existing_payment.payment_method = "PAYMONGO"
        existing_payment.amount = amount
        existing_payment.save(
            update_fields=[
                "checkout_session_id",
                "checkout_url",
                "reference_code",
                "payment_method",
                "amount",
            ]
        )
        return existing_payment

    return ManualPayment.objects.create(
        user=user,
        bill_ids=bill_ids,
        payment_type=payment_type,
        payment_method="PAYMONGO",
        amount=amount,
        reference_code=f"REF-PM-{checkout_session_id[-8:].upper()}",
        checkout_session_id=checkout_session_id,
        checkout_url=checkout_url,
        status="PENDING",
    )


def create_f2f_cash_payment_request(
    *,
    user,
    amount,
    bill_ids: str,
    payment_type: str,
    preferred_date,
    preferred_time,
    tenant_note: str,
):
    if get_recent_pending_manual_payment(
        user=user,
        bill_ids=bill_ids,
        payment_methods=["CASH"],
    ):
        return None, "duplicate"

    payment = ManualPayment.objects.create(
        user=user,
        reference_code="REF-F2F-" + datetime.now().strftime("%Y%m%d-%H%M%S"),
        bill_ids=bill_ids,
        payment_type=payment_type,
        payment_method="CASH",
        amount=amount,
        preferred_date=preferred_date,
        preferred_time=preferred_time,
        tenant_note=tenant_note,
    )
    return payment, None


def build_paymongo_checkout_metadata(*, user, bill_ids: str, payment_type: str, amount, extra=None):
    metadata = {
        "user_id": str(user.id),
        "bill_ids": bill_ids,
        "payment_type": payment_type,
        "amount": str(amount),
    }
    if extra:
        metadata.update(extra)
    return metadata


def create_paymongo_checkout_session_or_error(
    *,
    amount,
    description: str,
    metadata: dict,
    success_url: str,
    cancel_url: str,
):
    amount_cents = int(amount * 100)
    result = create_checkout_session(
        amount_cents=amount_cents,
        description=description,
        metadata=metadata,
        success_url=success_url,
        cancel_url=cancel_url,
    )

    if not result:
        return None, "Failed to create checkout session. Please try another payment method."

    if isinstance(result, dict) and result.get("error"):
        error_msg = result.get("error", "")
        if "not configured" in error_msg.lower():
            return None, "PayMongo payment gateway is not configured. Please contact the administrator."
        return None, f"Payment gateway error: {error_msg}. Please try another payment method."

    return result, None


def build_paymongo_success_url(base_url: str):
    return base_url + reverse("paymongo_success")


def validate_paymongo_webhook_request(payload_body, signature_header: str, webhook_secret: str, is_production: bool):
    if not webhook_secret:
        logger.error("PAYMONGO_WEBHOOK_SECRET not configured - webhook verification disabled")
        if is_production:
            return HttpResponse("Webhook secret not configured", status=500)
        return None

    if not verify_webhook_signature(payload_body, signature_header, webhook_secret):
        logger.warning("Invalid webhook signature received")
        return HttpResponseForbidden("Invalid signature")

    return None


def resolve_payment_tenant_user(payment):
    tenant_id = _payment_tenant_id(payment)
    if tenant_id:
        User = get_user_model()
        tenant = User.objects.select_related("tenantprofile").filter(pk=tenant_id).first()
        if tenant:
            return tenant

    lease_id = _payment_lease_id(payment)
    if lease_id:
        from rentals.models import Lease

        lease = Lease.objects.select_related("tenant").filter(pk=lease_id).first()
        if lease and lease.tenant:
            return lease.tenant

    return payment.user


def resolve_payment_display_name(payment):
    lease_id = _payment_lease_id(payment)
    if lease_id:
        from rentals.models import Lease

        lease = Lease.objects.select_related("tenant__tenantprofile").filter(pk=lease_id).first()
        if lease and lease.tenant:
            return _display_name_for_user(lease.tenant)

    return _display_name_for_user(resolve_payment_tenant_user(payment))


def get_pending_paymongo_payment(request_user, session_id):
    if session_id and session_id != "{checkout_session_id}":
        return ManualPayment.objects.filter(
            checkout_session_id=session_id,
            user=request_user,
        ).first()

    return ManualPayment.objects.filter(
        user=request_user,
        payment_method="PAYMONGO",
        status="PENDING",
    ).order_by("-created_at").first()


def get_paymongo_session_updates(payment, session_data):
    if not session_data:
        return False

    attrs = session_data.get("attributes", {})
    payments_list = attrs.get("payments", [])
    session_status = attrs.get("status", "")

    logger.info(
        f"PayMongo session status for payment {payment.id}: "
        f"session_status={session_status}, payments_count={len(payments_list)}, "
        f"current_db_status={payment.status}"
    )

    if payments_list and payment.status != "APPROVED":
        pm_payment = payments_list[0]
        pm_attrs = pm_payment.get("attributes", {})
        payment.paid_via = pm_attrs.get("source", {}).get("type", "unknown")
        payment.paymongo_payment_id = pm_payment.get("id", "")
        payment.save(update_fields=["paymongo_payment_id", "paid_via"])
        try:
            auto_approve_paymongo_payment(payment)
            logger.info(f"Payment {payment.id} auto-approved via success page")
            return True
        except Exception as e:
            logger.error(f"Failed to auto-approve payment {payment.id}: {e}")
            return False

    if session_status == "paid" and payment.status != "APPROVED":
        try:
            auto_approve_paymongo_payment(payment)
            logger.info(f"Payment {payment.id} auto-approved via session status")
            return True
        except Exception as e:
            logger.error(f"Failed to auto-approve payment {payment.id} from session: {e}")
            return False

    return False


def get_paymongo_admin_success_context(payment):
    lease = None
    tenant_name = ""
    if payment.payment_type == "move_in":
        from rentals.models import Lease

        lease_id = payment.metadata.get("lease_id") if payment.metadata else None
        if lease_id:
            try:
                lease = Lease.objects.get(id=lease_id)
                tenant_name = lease.tenant.tenantprofile.full_name if hasattr(lease.tenant, "tenantprofile") else lease.tenant.email
            except Lease.DoesNotExist:
                pass

    return {
        "payment": payment,
        "payment_approved": payment.status == "APPROVED",
        "auto_refresh": payment.status != "APPROVED",
        "lease": lease,
        "tenant_name": tenant_name,
    }


def render_paymongo_tenant_success(request, payment, payment_approved):
    if payment.status == "APPROVED":
        messages.success(request, "Payment successful! Your bills have been updated. Thank you for your payment.")
    elif payment_approved:
        messages.success(request, "Payment received and is being processed. Your account will be updated shortly.")
    else:
        messages.info(
            request,
            "Payment confirmation received. Please allow a moment for your account to be updated. "
            "You will receive a notification once the payment is confirmed.",
        )

    return render(request, "payments/paymongo_success.html", {
        "payment": payment,
        "payment_approved": payment.status == "APPROVED",
        "auto_refresh": payment.status != "APPROVED",
    })


def parse_paymongo_webhook_payload(request):
    payload_body = request.body
    try:
        return json.loads(payload_body), None
    except json.JSONDecodeError:
        return None, HttpResponseBadRequest("Invalid JSON")


def find_paymongo_webhook_payment(payload):
    event_data = payload["data"]["attributes"]["data"]
    attrs = event_data.get("attributes", {})
    checkout_session_id = event_data.get("id", "")
    payments_list = attrs.get("payments", [])
    metadata = attrs.get("metadata", {})

    payment = ManualPayment.objects.filter(
        checkout_session_id=checkout_session_id,
        payment_method="PAYMONGO",
    ).first()

    if not payment and metadata.get("user_id"):
        payment = ManualPayment.objects.filter(
            user_id=metadata["user_id"],
            bill_ids=metadata.get("bill_ids", ""),
            payment_method="PAYMONGO",
            status="PENDING",
        ).first()

    return payment, payments_list


def apply_paymongo_payment_source(payment, payments_list):
    if not payments_list:
        return

    pm_payment = payments_list[0]
    pm_attrs = pm_payment.get("attributes", {})
    payment.paid_via = pm_attrs.get("source", {}).get("type", "unknown")
    payment.paymongo_payment_id = pm_payment.get("id", "")
    payment.save(update_fields=["paid_via", "paymongo_payment_id"])


def get_pending_move_in_lease(payment):
    from rentals.models import Lease

    return Lease.objects.filter(
        tenant=payment.user,
        status=Lease.STATUS_PENDING_PAYMENT,
    ).order_by("-created_at").first()


def activate_paymongo_move_in_lease(payment):
    lease_id = _payment_lease_id(payment)
    if not lease_id and payment.payment_type == "move_in":
        pending_lease = get_pending_move_in_lease(payment)
        if pending_lease:
            lease_id = pending_lease.id
            logger.info(f"Found pending lease {lease_id} for move-in payment {payment.id} via fallback")

    if not lease_id or payment.payment_type != "move_in":
        return False

    from rentals.services import LeaseActivationService

    success, message = LeaseActivationService.activate_lease_after_payment(
        lease_id=int(lease_id),
        payment_method="PAYMONGO",
        payment_reference=payment.reference_code,
        amount=payment.amount,
    )
    if success:
        logger.info(f"Lease {lease_id} activated via PayMongo webhook")
        return True

    logger.warning(f"Lease activation failed for {lease_id}: {message}")
    return False


def approve_regular_paymongo_payment(payment):
    try:
        approve_manual_payment(payment)
        logger.info(f"PayMongo payment {payment.id} auto-approved successfully")
        return True
    except Exception as e:
        logger.exception(f"Failed to auto-approve PayMongo payment {payment.id}: {e}")
        return False


def _mark_paymongo_payment_approved(payment):
    payment.status = "APPROVED"
    payment.save(update_fields=["status"])
    logger.info(f"Move-in payment {payment.id} marked as APPROVED after lease activation")


def _notify_admin_about_paymongo_payment(payment, lease_activated):
    try:
        notify_admin_about_paymongo_payment(payment, lease_activated)
    except Exception as e:
        logger.exception(f"Failed to create admin notification for PayMongo payment: {e}")


def _approve_regular_paymongo_payment_if_needed(payment, lease_activated):
    if not lease_activated and payment.payment_type != "move_in":
        approve_regular_paymongo_payment(payment)


def notify_admin_about_paymongo_payment(payment, lease_activated):
    tenant_user = resolve_payment_tenant_user(payment)
    tenant_name = resolve_payment_display_name(payment)
    paid_via_display = (payment.paid_via or "online").replace("_", " ").title()

    if lease_activated:
        title = "Move-in Payment Received - Lease Activated"
        message = (
            f"{tenant_name} paid ₱{payment.amount:,.2f} via PayMongo ({paid_via_display}). "
            f"Reference: {payment.reference_code}. "
            "Lease has been automatically ACTIVATED and first month's bill marked as PAID."
        )
    else:
        title = "Online Payment Received & Auto-Approved"
        message = (
            f"{tenant_name} paid ₱{payment.amount:,.2f} via PayMongo ({paid_via_display}). "
            f"Reference: {payment.reference_code}. Bills have been automatically marked as PAID."
        )

    Notification.create_notification(
        title=title,
        message=message,
        notification_type="PAYMENT",
        recipient_type="ADMIN",
        related_tenant=tenant_user,
    )


def auto_approve_paymongo_payment(payment):
    if payment.status == "APPROVED":
        return

    lease_activated = False
    try:
        lease_activated = activate_paymongo_move_in_lease(payment)
    except Exception as e:
        logger.exception(f"Error checking lease activation for payment {payment.id}: {e}")

    _approve_regular_paymongo_payment_if_needed(payment, lease_activated)

    if lease_activated:
        _mark_paymongo_payment_approved(payment)

    _notify_admin_about_paymongo_payment(payment, lease_activated)


def process_paymongo_webhook_payload(payload):
    event_type = payload.get("data", {}).get("attributes", {}).get("type", "")
    logger.info(f"PayMongo webhook received: {event_type}")

    if event_type != "checkout_session.payment.paid":
        return JsonResponse({"status": "ok"})

    payment, payments_list = find_paymongo_webhook_payment(payload)
    if payment and payment.status != "APPROVED":
        apply_paymongo_payment_source(payment, payments_list)
        auto_approve_paymongo_payment(payment)
        logger.info(f"PayMongo webhook auto-approved payment {payment.id}")

    return JsonResponse({"status": "ok"})
