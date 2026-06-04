import logging
from datetime import date

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from billing.services import cleanup_duplicate_monthly_bills_for_lease, ensure_bills_since_move_in
from payments.models import ManualPayment
from rentals.models import Lease, Notification, TenantProfile

from .admin_portal_forms import LeaseForm, _ordinal
from .admin_portal_views import admin_required, admin_password_verified, render_admin_password_confirm


logger = logging.getLogger(__name__)


def _build_cash_move_in_reference(lease) -> str:
    return f"REF-CASH-MOVEIN-{lease.id}"


def _tenant_display_name(user) -> str:
    try:
        full_name = user.tenantprofile.full_name.strip()
        if full_name:
            return full_name
    except Exception:
        pass
    return user.email


def _create_cash_move_in_notification(lease, payment):
    tenant_name = _tenant_display_name(lease.tenant)
    Notification.create_notification(
        title="Move-in Payment Received - Lease Activated",
        message=(
            f"{tenant_name} paid ₱{payment.amount:,.2f} via Face-to-Face Cash. "
            f"Reference: {payment.reference_code}. "
            "Lease has been activated and first month's bill marked as PAID."
        ),
        notification_type="PAYMENT",
        recipient_type="ADMIN",
        related_tenant=lease.tenant,
        related_unit=lease.unit,
    )


@admin_required
def admin_create_lease(request):
    """Create a lease row linking a tenant to a unit."""
    from rentals.services import LeaseSchedulingService, send_email_via_resend

    initial = {}
    tenant_id = request.GET.get("tenant_id")
    if tenant_id:
        initial["tenant"] = tenant_id

    form = LeaseForm(request.POST or None, initial=initial)
    schedule_preview = None

    if request.method == "POST":
        if form.is_valid():
            try:
                lease = form.save()

                try:
                    Notification.create_notification(
                        title="New Lease Created",
                        message=(
                            f"Lease created for {lease.tenant.email} in Unit {lease.unit.number}\n\n"
                            f"Lease Details:\n"
                            f"• Monthly Rent: ₱{lease.monthly_rent:,.2f}\n"
                            f"• Contract Deposit: ₱{lease.contract_deposit:,.2f} ({lease.deposit_multiplier}x monthly rent)\n"
                            f"• Security Deposit: ₱{lease.security_deposit:,.2f}\n"
                            f"• Total Move-in Cost: ₱{lease.total_move_in_cost:,.2f}\n"
                            f"• Lease Start: {lease.start_date.strftime('%B %d, %Y')}\n"
                            f"• First Rent Due: {lease.first_rent_due_date.strftime('%B %d, %Y')}"
                        ),
                        notification_type="LEASE",
                        related_tenant=lease.tenant,
                        related_unit=lease.unit,
                    )
                except Exception as exc:
                    logger.exception("Failed to create lease notification: %s", exc)

                try:
                    welcome_message = (
                        "Welcome to your new home at REALESTATE360+!\n\n"
                        "Your lease has been successfully created. Here are your payment details:\n\n"
                        "Unit Information:\n"
                        f"• Unit Number: {lease.unit.number}\n"
                        f"• Unit Type: {lease.unit.get_unit_type_display()}\n"
                        f"• Floor Level: {lease.unit.floor_level}\n"
                        f"• Size: {lease.unit.size_sqm} sqm\n\n"
                        "Payment Schedule:\n"
                        f"• Monthly Rent: ₱{lease.monthly_rent:,.2f}\n"
                        f"• Security Deposit: ₱{lease.security_deposit:,.2f} (due on move-in)\n"
                        f"• Contract Deposit: ₱{lease.contract_deposit:,.2f} ({lease.deposit_multiplier}x monthly rent)\n"
                        f"• Total Move-in Cost: ₱{lease.total_move_in_cost:,.2f}\n"
                        f"• Lease Start Date: {lease.start_date.strftime('%B %d, %Y')}\n"
                        f"• First Regular Rent Due: {lease.first_rent_due_date.strftime('%B %d, %Y')}\n\n"
                        f"Your unit features: {lease.unit.description or 'Modern living space with premium amenities.'}\n"
                        f"Amenities included: {lease.unit.amenities or 'Contact admin for full amenities list.'}\n\n"
                        "Payment Due Dates:\n"
                        f"• Rent is due on the {_ordinal(lease.due_day)} of each month\n"
                        f"• Your contract deposit is recorded separately from monthly rent\n"
                        f"• Regular rent payments start {lease.first_rent_due_date.strftime('%B %d, %Y')}\n\n"
                        "You can access your tenant portal to view bills, make payments, and request maintenance.\n\n"
                        "Welcome aboard! We're excited to have you as part of our community!"
                    )
                    Notification.create_notification(
                        title=f"Welcome to Your New Unit {lease.unit.number}!",
                        message=welcome_message,
                        notification_type="SYSTEM",
                        related_tenant=lease.tenant,
                        related_unit=lease.unit,
                    )
                except Exception as exc:
                    logger.exception("Failed to create welcome notification for tenant: %s", exc)

                try:
                    unit = lease.unit
                    unit.status = "AVAILABLE"
                    unit.save(update_fields=["status"])
                    logger.info("Unit %s remains AVAILABLE while lease %s is pending payment", unit.number, lease.id)
                except Exception as exc:
                    logger.exception("Failed to update unit status for lease %s: %s", lease.id, exc)

                try:
                    tenant_profile = TenantProfile.objects.get(user=lease.tenant)
                    tenant_profile.has_seen_unit_welcome = False
                    tenant_profile.save()
                    logger.info("Reset welcome popup flag for tenant %s", lease.tenant.email)
                except Exception as exc:
                    logger.exception("Failed to reset welcome popup flag for tenant %s: %s", lease.tenant.email, exc)

                try:
                    tenant_name = (
                        lease.tenant.tenantprofile.full_name
                        if hasattr(lease.tenant, "tenantprofile")
                        else lease.tenant.email
                    )
                    lease_email_sent = send_email_via_resend(
                        to_email=lease.tenant.email,
                        subject=f"[REALESTATE360+] Unit {lease.unit.number} Assigned to You",
                        message=(
                            f"Dear {tenant_name},\n\n"
                            "Your unit has been successfully assigned. Here are your lease details:\n\n"
                            f"  Unit Number:        {lease.unit.number}\n"
                            f"  Unit Type:          {lease.unit.get_unit_type_display()}\n"
                            f"  Monthly Rent:       PHP {lease.monthly_rent:,.2f}\n"
                            f"  Security Deposit:   PHP {lease.security_deposit:,.2f}\n"
                            f"  Contract Deposit:   PHP {lease.contract_deposit:,.2f} ({lease.deposit_multiplier}× monthly rent)\n"
                            f"  Parking Fee:        PHP {lease.parking_fee:,.2f}/mo\n"
                            f"  Total Move-in Due:  PHP {lease.total_move_in_cost:,.2f}\n"
                            f"  Lease Start:        {lease.start_date.strftime('%B %d, %Y')}\n"
                            f"  Rent Due:           Every {lease.due_day} of the month\n\n"
                            "Move-in Breakdown:\n"
                            f"  1st Month Rent:     PHP {lease.monthly_rent:,.2f}\n"
                            f"  + Security Deposit: PHP {lease.security_deposit:,.2f}\n"
                            f"  + Parking Fee:      PHP {lease.parking_fee:,.2f}\n"
                            f"  = Total:            PHP {lease.total_move_in_cost:,.2f}\n\n"
                            "You can log in to your tenant portal to view your bills and payment schedule.\n\n"
                            "Welcome to your new home!\n\n"
                            "REALESTATE360+ Administration"
                        ),
                    )
                    if lease_email_sent:
                        messages.info(request, f"Lease assignment email sent to {lease.tenant.email}.")
                    else:
                        messages.warning(
                            request,
                            "Lease was created, but the lease assignment email was not sent. "
                            "Check Resend configuration and delivery logs.",
                        )
                except Exception as exc:
                    logger.exception("Failed to send lease assignment email: %s", exc)

                messages.success(
                    request,
                    f"Lease created for {lease.tenant.email} - Unit {lease.unit.number}. "
                    "Status: PENDING PAYMENT. Please complete payment to activate.",
                )
                return redirect("admin_lease_payment", lease_id=lease.id)
            except Exception as exc:
                logger.exception("Error creating lease: %s", exc)
                messages.error(request, f"Error creating lease: {str(exc)}")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        if request.GET.get("preview") == "1":
            service = LeaseSchedulingService()
            sample_data = {
                "monthly_rent": 17000,
                "advance_months": 2,
                "security_deposit": 17000,
                "start_date": date.today(),
                "due_day": 5,
            }
            schedule_preview = service.get_payment_schedule_preview(sample_data)

    back_url = reverse("admin_tenants")
    unit_id = request.GET.get("unit_id")
    if unit_id:
        back_url = reverse("admin_unit_detail", args=[unit_id])

    return render(
        request,
        "admin_portal/lease_form.html",
        {
            "title": "Add Lease",
            "form": form,
            "back_url": back_url,
            "schedule_preview": schedule_preview,
            "gcash_name": getattr(settings, "GCASH_NAME", ""),
            "gcash_number": getattr(settings, "GCASH_NUMBER", ""),
        },
    )


@admin_required
def admin_lease_payment(request, lease_id: int):
    """Move-in payment page for pending lease."""
    from rentals.services import LeaseActivationService

    lease = get_object_or_404(
        Lease.objects.select_related("tenant", "unit"),
        id=lease_id,
    )

    if lease.status != Lease.STATUS_PENDING_PAYMENT:
        tenant_id = lease.tenant.tenantprofile.id if hasattr(lease.tenant, "tenantprofile") else lease.tenant.id
        if lease.status == Lease.STATUS_ACTIVE:
            messages.info(request, "This lease is already active. Move-in payment has already been completed.")
        else:
            messages.info(request, f"This lease is no longer awaiting move-in payment. Current status: {lease.display_status}.")
        return redirect("admin_tenant_detail", tenant_id=tenant_id)

    if request.method == "POST":
        payment_method = request.POST.get("payment_method", "")

        if payment_method == "CASH":
            admin_password = (request.POST.get("admin_password") or "").strip()
            if not request.user.check_password(admin_password):
                messages.error(request, "Admin password verification failed. Cash payment was not recorded.")
                return render(
                    request,
                    "admin_portal/lease_payment.html",
                    {
                        "title": "Lease Payment",
                        "lease": lease,
                        "total_move_in_cost": lease.total_move_in_cost,
                        "cash_reference": _build_cash_move_in_reference(lease),
                        "back_url": reverse("admin_create_lease"),
                    },
                )
            payment_reference = _build_cash_move_in_reference(lease)
            payment = ManualPayment.objects.create(
                user=lease.tenant,
                payment_type="move_in",
                payment_method="CASH",
                amount=lease.total_move_in_cost,
                reference_code=payment_reference,
                status="PENDING",
                tenant_note="Admin-recorded face-to-face move-in payment",
                metadata={
                    "lease_id": lease.id,
                    "generated_by_admin": str(request.user.id),
                    "tenant_id": str(lease.tenant.id),
                },
            )
            success, message = LeaseActivationService.activate_lease_after_payment(
                lease_id=lease.id,
                payment_method="CASH",
                payment_reference=payment_reference,
                amount=lease.total_move_in_cost,
                existing_payment=payment,
            )
            if success:
                try:
                    _create_cash_move_in_notification(lease, payment)
                except Exception as exc:
                    logger.exception("Failed to create cash move-in notification for lease %s: %s", lease.id, exc)
                messages.success(request, f"Lease activated successfully! {message}")
                tenant_id = lease.tenant.tenantprofile.id if hasattr(lease.tenant, "tenantprofile") else lease.tenant.id
                return redirect("admin_tenant_detail", tenant_id=tenant_id)
            messages.error(request, f"Activation failed: {message}")

        elif payment_method == "GCASH":
            return HttpResponseRedirect(
                f"/payments/manual-gcash/?amount={lease.total_move_in_cost}&lease_id={lease.id}&payment_type=move_in"
            )

        elif payment_method == "PAYMONGO":
            return HttpResponseRedirect(
                f"/payments/paymongo/admin-checkout/?amount={lease.total_move_in_cost}&lease_id={lease.id}&payment_type=move_in"
            )

    return render(
        request,
        "admin_portal/lease_payment.html",
        {
            "title": "Lease Payment",
            "lease": lease,
            "total_move_in_cost": lease.total_move_in_cost,
            "cash_reference": _build_cash_move_in_reference(lease),
            "back_url": reverse("admin_create_lease"),
        },
    )


@admin_required
def admin_edit_lease(request, lease_id: int):
    lease = get_object_or_404(Lease, pk=lease_id)
    form = LeaseForm(request.POST or None, instance=lease)
    if request.method == "POST" and form.is_valid():
        lease = form.save()
        try:
            ensure_bills_since_move_in(lease)
            removed_duplicates = cleanup_duplicate_monthly_bills_for_lease(lease)
            if removed_duplicates:
                messages.info(
                    request,
                    f"Cleaned up {removed_duplicates} duplicate historical bill record{'s' if removed_duplicates != 1 else ''} for this lease.",
                )
        except Exception:
            logger.exception("ensure_bills_since_move_in failed while editing lease id %s", getattr(lease, "id", None))
            messages.warning(request, "Failed to update billing rows; please regenerate bills if needed.")
        tenant_id = lease.tenant.tenantprofile.id if hasattr(lease.tenant, "tenantprofile") else lease.tenant.id
        return redirect("admin_tenant_detail", tenant_id=tenant_id)

    return render(
        request,
        "admin_portal/lease_form.html",
        {
            "title": "Edit Lease",
            "form": form,
            "lease": lease,
            "back_url": reverse("admin_tenants"),
            "schedule_preview": None,
            "gcash_name": getattr(settings, "GCASH_NAME", ""),
            "gcash_number": getattr(settings, "GCASH_NUMBER", ""),
        },
    )


@admin_required
def admin_delete_lease(request, lease_id: int):
    lease = get_object_or_404(Lease.objects.select_related("unit"), pk=lease_id)
    is_pending = lease.status == Lease.STATUS_PENDING_PAYMENT
    action_title = "Cancel Pending Lease" if is_pending else "Delete Lease"
    action_message = (
        f"Cancel the pending lease for unit {lease.unit.number}? "
        "No payment has been confirmed, and the unit will remain available."
        if is_pending
        else f"Delete lease for unit {lease.unit.number}? This cannot be undone."
    )
    next_target = request.GET.get("next")
    back_url = reverse("admin_unit_detail", args=[lease.unit.id]) if next_target == "unit" else reverse("admin_tenants")
    post_url = reverse("admin_delete_lease", args=[lease.id])
    if next_target:
        post_url = f"{post_url}?next={next_target}"

    if request.method == "POST":
        if not admin_password_verified(request):
            return render_admin_password_confirm(
                request,
                title=action_title,
                message=action_message,
                post_url=post_url,
                back_url=back_url,
                error="Incorrect admin password. Lease was not cancelled." if is_pending else "Incorrect admin password. Lease was not deleted.",
            )
        unit = lease.unit
        unit_number = unit.number
        lease.delete()
        unit.status = "AVAILABLE"
        unit.save(update_fields=["status"])
        if is_pending:
            messages.success(request, f"Pending lease cancelled and unit {unit_number} remains available.")
        else:
            messages.success(request, f"Lease deleted and unit {unit_number} is now available.")
        return redirect(back_url)

    return render_admin_password_confirm(
        request,
        title=action_title,
        message=action_message,
        post_url=post_url,
        back_url=back_url,
    )
