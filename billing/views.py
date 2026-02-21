from django.shortcuts import redirect

def tenant_pay_advance(request):
    if request.method == "POST":
        return redirect("manual_gcash_payment")

    # keep whatever existing context you render
    return render(request, "billing/tenant_pay_advance.html", context)