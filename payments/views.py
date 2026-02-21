from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods

from .models import ManualPayment


@login_required
@require_http_methods(["GET", "POST"])
def manual_gcash_payment(request):
    if request.method == "POST":
        reference_code = (request.POST.get("reference_code") or "").strip()

        if not reference_code:
            return render(request, "payments/manual_gcash.html", {
                "error": "GCash reference number is required.",
                "gcash_number": getattr(settings, "GCASH_NUMBER", ""),
                "gcash_name": getattr(settings, "GCASH_NAME", ""),
            })

        ManualPayment.objects.create(
            user=request.user,
            reference_code=reference_code,
        )

        return redirect("tenant_dashboard")

    return render(request, "payments/manual_gcash.html", {
        "gcash_number": getattr(settings, "GCASH_NUMBER", ""),
        "gcash_name": getattr(settings, "GCASH_NAME", ""),
    })