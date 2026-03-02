from django import forms
from .models import MaintenanceRequest


class MaintenanceRequestForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = ["category", "title", "description"]  # no priority/status here
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
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
