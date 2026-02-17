from django import forms
from .models import MaintenanceRequest


class MaintenanceRequestForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = ["category", "title", "description"]  # no priority/status here
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
        }
