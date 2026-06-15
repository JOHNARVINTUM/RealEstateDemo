from django import forms
from .models import MaintenanceRequest


class MaintenanceRequestForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = ["title", "description", "requested_schedule_at", "photo"]  # category is auto-classified from text
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Short summary of the problem"}),
            "description": forms.Textarea(attrs={"rows": 6, "placeholder": "Describe what happened, where it happened, and any details that can help classify the issue."}),
            "requested_schedule_at": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "placeholder": "Choose your available date and time",
                },
                format="%Y-%m-%dT%H:%M",
            ),
            "photo": forms.ClearableFileInput(attrs={"class": "w-full border-2 border-slate-100 rounded-2xl px-6 py-4 text-lg font-black text-slate-900 bg-white focus:border-slate-900 transition-all cursor-pointer file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-slate-50 file:text-slate-700 hover:file:bg-slate-100"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["requested_schedule_at"].label = "Preferred visit date and time"
        self.fields["requested_schedule_at"].required = True
        self.fields["requested_schedule_at"].input_formats = ["%Y-%m-%dT%H:%M"]


class AdminMaintenanceUpdateForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = [
            "category",
            "status",
            "priority",
            "fixed_by",
            "schedule_decision",
            "admin_scheduled_at",
            "schedule_admin_note",
        ]
        widgets = {
            "fixed_by": forms.TextInput(attrs={"placeholder": "Name of person who fixed it (optional)"}),
            "admin_scheduled_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "schedule_admin_note": forms.Textarea(attrs={"rows": 3, "placeholder": "Optional note for the tenant"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["admin_scheduled_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        if self.instance and self.instance.admin_scheduled_at:
            self.initial["admin_scheduled_at"] = self.instance.admin_scheduled_at.strftime("%Y-%m-%dT%H:%M")
        # For the admin quick-update form, restrict status options to in-progress or resolved
        self.fields["status"].choices = [
            (k, v) for k, v in MaintenanceRequest.STATUS_CHOICES if k in ("IN_PROGRESS", "RESOLVED")
        ]
        self.fields["category"].label = "Issue category"
        self.fields["priority"].label = "Priority level"
        self.fields["status"].label = "Status"
        self.fields["schedule_decision"].label = "Visit schedule decision"
        self.fields["admin_scheduled_at"].label = "Approved / rescheduled visit time"
        self.fields["admin_scheduled_at"].required = False
        self.fields["schedule_admin_note"].label = "Admin schedule note"

    def clean(self):
        cleaned_data = super().clean()
        decision = cleaned_data.get("schedule_decision")
        admin_scheduled_at = cleaned_data.get("admin_scheduled_at")
        requested_schedule_at = getattr(self.instance, "requested_schedule_at", None)

        if decision == "APPROVED" and not admin_scheduled_at and requested_schedule_at:
            cleaned_data["admin_scheduled_at"] = requested_schedule_at
        if decision == "RESCHEDULED" and not admin_scheduled_at:
            self.add_error("admin_scheduled_at", "Set the new visit date and time when rescheduling.")
        return cleaned_data
