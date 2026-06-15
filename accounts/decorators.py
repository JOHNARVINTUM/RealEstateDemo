from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import redirect

def admin_required(view_func):
    def check(user):
        return user.is_authenticated and (getattr(user, "role", "") == "ADMIN" or user.is_superuser)
    return user_passes_test(check)(view_func)


def tenant_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if getattr(request.user, "role", "") == "TENANT":
            return view_func(request, *args, **kwargs)

        messages.warning(request, "Tenant portal pages are only available to tenant accounts.")
        if getattr(request.user, "role", "") == "ADMIN" or request.user.is_superuser:
            return redirect("admin_dashboard")
        return redirect("login")

    return wrapper
