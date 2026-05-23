from django import forms
from .models import MaintenanceRequest


class MaintenanceRequestForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = ["category", "title", "description", "photo"]  # no priority/status here
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
            "photo": forms.ClearableFileInput(attrs={"class": "w-full border-2 border-slate-100 rounded-2xl px-6 py-4 text-lg font-black text-slate-900 bg-white focus:border-slate-900 transition-all cursor-pointer file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-slate-50 file:text-slate-700 hover:file:bg-slate-100"}),
        }


class AdminMaintenanceUpdateForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = ["status", "priority", "fixed_by"]
        widgets = {
            "fixed_by": forms.TextInput(attrs={"placeholder": "Name of person who fixed it (optional)"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # For the admin quick-update form, restrict status options to in-progress or resolved
        self.fields["status"].choices = [
            (k, v) for k, v in MaintenanceRequest.STATUS_CHOICES if k in ("IN_PROGRESS", "RESOLVED")
        ]
