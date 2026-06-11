import logging
import mimetypes
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.contrib import messages

from rentals.models import Lease, TenantAttachment, TenantProfile

logger = logging.getLogger(__name__)


class RoleBasedLoginView(LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        # If someone hit a protected page, honor ?next=...
        next_url = self.get_redirect_url()
        if next_url:
            return next_url

        user = self.request.user
        if getattr(user, "role", "") == "ADMIN" or user.is_superuser:
            return reverse("admin_dashboard")   # /admin-portal/dashboard/
        return reverse("tenant_dashboard")      # change if your tenant view name is different


class TenantPasswordChangeView(PasswordChangeView):
    """
    Custom password change view for tenants.
    
    This view extends Django's PasswordChangeView to:
    1. Clear the password_change_required flag after successful change
    2. Update session to prevent logout after password change
    3. Show success message to user
    4. Redirect to tenant dashboard
    
    This view is used when tenants are forced to change their temporary
    password on first login.
    """
    template_name = "registration/password_change_form.html"
    success_url = reverse_lazy("tenant_dashboard")
    
    def form_valid(self, form):
        """
        Process valid password change form.
        
        Extends parent behavior to:
        - Clear password_change_required flag
        - Update session to prevent logout
        - Add success message
        
        Args:
            form: Valid PasswordChangeForm instance
            
        Returns:
            HttpResponse: Redirect to success URL
        """
        # Call parent to actually change the password
        response = super().form_valid(form)
        
        # Clear the password_change_required flag
        try:
            if hasattr(self.request.user, 'tenantprofile'):
                if self.request.user.tenantprofile.password_change_required:
                    self.request.user.tenantprofile.password_change_required = False
                    self.request.user.tenantprofile.save(update_fields=['password_change_required'])
                    logger.info(
                        f"Password change completed for tenant {self.request.user.username}, "
                        f"password_change_required flag cleared"
                    )
        except Exception as e:
            # Log error but don't fail the password change
            logger.error(
                f"Failed to clear password_change_required flag for {self.request.user.username}: {e}"
            )
        
        # Update session to prevent logout after password change
        update_session_auth_hash(self.request, self.request.user)
        
        # Add success message
        messages.success(
            self.request,
            "Your password has been updated successfully. Welcome to RealEstate360+!"
        )
        
        return response
    
    def form_invalid(self, form):
        """
        Handle invalid password change form submission.
        
        Adds error message for user feedback.
        
        Args:
            form: Invalid PasswordChangeForm instance
            
        Returns:
            HttpResponse: Rendered form with errors
        """
        messages.error(
            self.request,
            "Please correct the errors below and try again."
        )
        return super().form_invalid(form)


def _is_admin_user(user):
    return getattr(user, "role", "") == "ADMIN" or user.is_superuser or user.is_staff


def _styled_password_form(user, data=None):
    form = PasswordChangeForm(user=user, data=data)
    input_class = (
        "w-full rounded-2xl border-2 border-slate-200 bg-white px-4 py-3 "
        "text-base font-bold text-slate-900 outline-none transition "
        "focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
    )
    for field in form.fields.values():
        field.widget.attrs.update({"class": input_class})
    return form


@login_required
def account_profile(request):
    user = request.user
    tenant_profile = TenantProfile.objects.filter(user=user).first()
    active_lease = (
        Lease.objects.select_related("unit")
        .filter(tenant=user, status=Lease.STATUS_ACTIVE)
        .order_by("-start_date", "-id")
        .first()
    )
    latest_lease = active_lease or (
        Lease.objects.select_related("unit")
        .filter(tenant=user)
        .order_by("-start_date", "-id")
        .first()
    )
    attachments = (
        TenantAttachment.objects.select_related("uploaded_by")
        .filter(tenant=user)
        .order_by("-uploaded_at")
        if tenant_profile
        else TenantAttachment.objects.none()
    )

    if request.method == "POST":
        password_form = _styled_password_form(user, request.POST)
        if password_form.is_valid():
            password_form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Your password has been updated successfully.")
            return redirect("account_profile")
        messages.error(request, "Please correct the password fields and try again.")
    else:
        password_form = _styled_password_form(user)

    display_name = (
        tenant_profile.full_name
        if tenant_profile
        else (user.get_full_name() or user.username or user.email)
    )
    role_label = user.get_role_display() if hasattr(user, "get_role_display") else getattr(user, "role", "User")
    template_name = "accounts/profile_admin.html" if _is_admin_user(user) else "accounts/profile_tenant.html"

    return render(
        request,
        template_name,
        {
            "display_name": display_name,
            "tenant_profile": tenant_profile,
            "latest_lease": latest_lease,
            "active_lease": active_lease,
            "attachments": attachments,
            "password_form": password_form,
            "role_label": role_label,
        },
    )


@login_required
def account_profile_attachment(request, attachment_id: int):
    attachment = get_object_or_404(
        TenantAttachment.objects.select_related("tenant"),
        pk=attachment_id,
    )
    if not _is_admin_user(request.user) and attachment.tenant_id != request.user.id:
        raise Http404("Attachment not found.")
    if not attachment.file:
        raise Http404("Attachment file is not available.")

    content_type = mimetypes.guess_type(attachment.filename)[0] or "application/octet-stream"
    try:
        attachment.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("Attachment file is not available.")

    response = FileResponse(attachment.file, content_type=content_type)
    response["Content-Disposition"] = f'inline; filename="{attachment.filename}"'
    return response
