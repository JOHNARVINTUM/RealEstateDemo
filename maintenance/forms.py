from django import forms
from django.contrib.auth import get_user_model

from accounts.models import User

from .models import MaintenanceRequest


def _person_label(user):
    profile = getattr(user, "tenantprofile", None)
    if profile and getattr(profile, "full_name", ""):
        return profile.full_name
    if getattr(user, "get_full_name", None):
        full_name = user.get_full_name()
        if full_name:
            return full_name
    return user.username or user.email


def _worker_name_choices(include_user=None):
    users = get_user_model().objects.filter(role=User.Role.STAFF, is_active=True).select_related("tenantprofile").order_by("email")
    choices = [("", "Select worker")]
    seen = set()
    for user in users:
        label = _person_label(user)
        if label not in seen:
            choices.append((label, label))
            seen.add(label)

    if include_user:
        label = _person_label(include_user)
        if label and label not in seen:
            choices.append((label, label))
    return choices


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
    fixed_by = forms.ChoiceField(required=False)

    class Meta:
        model = MaintenanceRequest
        fields = [
            "category",
            "priority",
            "review_status",
            "assigned_staff",
            "status",
            "fixed_by",
            "schedule_decision",
            "admin_scheduled_at",
            "schedule_admin_note",
        ]
        widgets = {
            "admin_scheduled_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "schedule_admin_note": forms.Textarea(attrs={"rows": 3, "placeholder": "Optional note for the tenant"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        self.fields["assigned_staff"].queryset = User.objects.filter(role="STAFF", is_active=True).order_by("email")
        self.fields["fixed_by"].choices = _worker_name_choices(include_user=getattr(self.instance, "assigned_staff", None))
        assigned_staff_name = _person_label(self.instance.assigned_staff) if getattr(self.instance, "assigned_staff", None) else ""
        current_fixed_by = getattr(self.instance, "fixed_by", "") or ""
        if current_fixed_by and current_fixed_by not in dict(self.fields["fixed_by"].choices):
            self.fields["fixed_by"].choices.append((current_fixed_by, current_fixed_by))
        if not current_fixed_by and assigned_staff_name:
            self.initial["fixed_by"] = assigned_staff_name
        self.fields["admin_scheduled_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        if self.instance and self.instance.admin_scheduled_at:
            self.initial["admin_scheduled_at"] = self.instance.admin_scheduled_at.strftime("%Y-%m-%dT%H:%M")
        self.fields["status"].choices = [
            (k, v) for k, v in MaintenanceRequest.STATUS_CHOICES if k in ("OPEN", "IN_PROGRESS", "RESOLVED")
        ]
        self.fields["category"].label = "Issue category"
        self.fields["priority"].label = "Priority level"
        self.fields["review_status"].label = "Admin review decision"
        self.fields["assigned_staff"].label = "Assigned staff"
        self.fields["status"].label = "Work status"
        self.fields["schedule_decision"].label = "Visit schedule decision"
        self.fields["admin_scheduled_at"].label = "Approved / rescheduled visit time"
        self.fields["admin_scheduled_at"].required = False
        self.fields["schedule_admin_note"].label = "Admin schedule note"
        self.fields["assigned_staff"].required = False
        self.fields["fixed_by"].label = "Completed by"

    def clean(self):
        cleaned_data = super().clean()
        decision = cleaned_data.get("schedule_decision")
        admin_scheduled_at = cleaned_data.get("admin_scheduled_at")
        requested_schedule_at = getattr(self.instance, "requested_schedule_at", None)
        review_status = cleaned_data.get("review_status")
        assigned_staff = cleaned_data.get("assigned_staff")
        status = cleaned_data.get("status")

        if decision == "APPROVED" and not admin_scheduled_at and requested_schedule_at:
            cleaned_data["admin_scheduled_at"] = requested_schedule_at
        if decision == "RESCHEDULED" and not admin_scheduled_at:
            self.add_error("admin_scheduled_at", "Set the new visit date and time when rescheduling.")

        if review_status == "ACCEPTED" and not assigned_staff:
            self.add_error("assigned_staff", "Assign a staff member when accepting this request.")

        if review_status in {"PENDING", "REJECTED"} and assigned_staff:
            self.add_error("assigned_staff", "Only accepted requests can be assigned to staff.")

        if review_status in {"PENDING", "REJECTED"} and status in {"IN_PROGRESS", "RESOLVED"}:
            self.add_error("status", "Only accepted requests can move into work-progress statuses.")

        return cleaned_data


class StaffMaintenanceUpdateForm(forms.ModelForm):
    fixed_by = forms.ChoiceField(required=False)

    class Meta:
        model = MaintenanceRequest
        fields = ["status", "fixed_by"]
        widgets = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (k, v) for k, v in MaintenanceRequest.STATUS_CHOICES if k in ("IN_PROGRESS", "RESOLVED")
        ]
        self.fields["status"].label = "Work status"
        self.fields["fixed_by"].label = "Completed by"
        self.fields["fixed_by"].choices = _worker_name_choices(include_user=getattr(self.instance, "assigned_staff", None))
        assigned_staff_name = _person_label(self.instance.assigned_staff) if getattr(self.instance, "assigned_staff", None) else ""
        current_fixed_by = getattr(self.instance, "fixed_by", "") or ""
        if current_fixed_by and current_fixed_by not in dict(self.fields["fixed_by"].choices):
            self.fields["fixed_by"].choices.append((current_fixed_by, current_fixed_by))
        if not current_fixed_by and assigned_staff_name:
            self.initial["fixed_by"] = assigned_staff_name
