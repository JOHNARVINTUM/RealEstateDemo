from django.contrib.auth.views import LoginView
from django.urls import reverse

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
        return reverse("tenant_dashboard")      # change if your tenant url name is different
