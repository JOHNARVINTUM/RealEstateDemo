from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from rentals.models import Lease
from .forms import MaintenanceRequestForm
from .models import MaintenanceRequest


@login_required
def report_issue(request):
    user = request.user
    lease = Lease.objects.filter(tenant=user, is_active=True).select_related("unit").first()

    if request.method == "POST":
        form = MaintenanceRequestForm(request.POST)
        if form.is_valid():
            obj: MaintenanceRequest = form.save(commit=False)
            obj.tenant = user
            obj.lease = lease
            # priority/status left for admin (defaults are fine)
            obj.save()
            return redirect("maintenance_list")
    else:
        form = MaintenanceRequestForm()

    # show unit info on the right side
    context = {
        "form": form,
        "lease": lease,
    }
    return render(request, "maintenance/report_issue.html", context)


@login_required
def maintenance_list(request):
    user = request.user
    qs = MaintenanceRequest.objects.filter(tenant=user).order_by("-created_at")
    return render(request, "maintenance/my_requests.html", {"requests": qs})
