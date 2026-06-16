from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def _is_admin_user(user):
    return user.is_authenticated and (
        getattr(user, "role", "") == "ADMIN" or user.is_superuser or user.is_staff
    )


def _is_tenant_user(user):
    return user.is_authenticated and getattr(user, "role", "") == "TENANT"


def admin_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if _is_admin_user(request.user):
            return view_func(request, *args, **kwargs)

        messages.warning(request, "You do not have permission to access the admin portal.")
        if _is_tenant_user(request.user):
            return redirect("tenant_dashboard")
        return redirect("login")

    return wrapper


def tenant_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if _is_tenant_user(request.user):
            return view_func(request, *args, **kwargs)

        messages.warning(request, "You do not have permission to access the tenant portal.")
        if _is_admin_user(request.user):
            return redirect("admin_dashboard")
        return redirect("login")

    return wrapper
