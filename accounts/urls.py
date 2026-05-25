from django.urls import path
from django.contrib.auth import views as auth_views
from .views import RoleBasedLoginView, TenantPasswordChangeView

urlpatterns = [
    path("", RoleBasedLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
    # Password change for tenants (first-login enforcement)
    path(
        "password-change/",
        TenantPasswordChangeView.as_view(),
        name="password_change"
    ),
    # Django's built-in password change done view (success page)
    path(
        "password-change/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="registration/password_change_done.html"
        ),
        name="password_change_done"
    ),
]
