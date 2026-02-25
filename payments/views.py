from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from django.contrib import messages

from .models import ManualPayment

@login_required
@require_http_methods(["GET", "POST"])
def manual_gcash_payment(request):
    if request.method == "POST":
        # 1. Catch ALL the data submitted by the form (including the hidden fields)
        reference_code = (request.POST.get("reference_code") or "").strip()
        amount_to_pay = request.POST.get("amount", "0.00")
        bill_ids = request.POST.get("bill_ids", "")

        # 2. Handle missing reference code
        if not reference_code:
            return render(request, "payments/manual_gcash.html", {
                "error": "GCash reference number is required.",
                "gcash_number": getattr(settings, "GCASH_NUMBER", "09XX-XXX-XXXX"),
                "gcash_name": getattr(settings, "GCASH_NAME", "STA. MARIA REALTY"),
                "amount_to_pay": amount_to_pay,
                "bill_ids": bill_ids,
            })

        # 3. FIX: Save the transaction WITH the required bill_ids
        ManualPayment.objects.create(
            user=request.user,
            reference_code=reference_code,
            bill_ids=bill_ids,  # This stops the NOT NULL IntegrityError
        )
        
        messages.success(request, "Payment submitted! Please wait for admin verification.")
        return redirect("tenant_dashboard")

    # 4. Handle the initial page load (GET request)
    amount_to_pay = request.GET.get("amount", "0.00")
    bill_ids = request.GET.get("bill_ids", "")

    return render(request, "payments/manual_gcash.html", {
        "gcash_number": getattr(settings, "GCASH_NUMBER", "09XX-XXX-XXXX"),
        "gcash_name": getattr(settings, "GCASH_NAME", "STA. MARIA REALTY"),
        "amount_to_pay": amount_to_pay,
        "bill_ids": bill_ids, # Sends the IDs to the HTML template
    })