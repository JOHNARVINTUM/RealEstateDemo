import logging
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.contrib.auth import update_session_auth_hash
from django.urls import reverse, reverse_lazy
from django.contrib import messages

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
