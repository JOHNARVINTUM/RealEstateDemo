from django.contrib.auth.views import LoginView
from django.shortcuts import redirect

class RoleBasedLoginView(LoginView):
    template_name = "accounts/login.html"

    def get_success_url(self):
        user = self.request.user
        if getattr(user, "role", "") == "ADMIN":
            return "/admin/"
        return "/tenant/"
