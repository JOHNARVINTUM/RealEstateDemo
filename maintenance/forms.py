from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import User

from .models import MaintenanceCharge, MaintenanceRequest


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


ACTIVE_ASSIGNMENT_STATUSES = ("OPEN", "IN_PROGRESS")


def _staff_assignment_queryset(include_user=None):
    staff_queryset = (
        get_user_model()
        .objects.filter(role=User.Role.STAFF)
        .select_related("tenantprofile")
        .annotate(
            active_job_count=Count(
                "assigned_maintenance_requests",
                filter=Q(
                    assigned_maintenance_requests__review_status="ACCEPTED",
                    assigned_maintenance_requests__status__in=ACTIVE_ASSIGNMENT_STATUSES,
                ),
                distinct=True,
            )
        )
    )
    if include_user is not None and getattr(include_user, "pk", None):
        staff_queryset = staff_queryset.filter(Q(is_active=True) | Q(pk=include_user.pk))
    else:
        staff_queryset = staff_queryset.filter(is_active=True)
    return staff_queryset.order_by("tenantprofile__first_name", "tenantprofile__last_name", "email")


def _staff_assignment_label(user):
    active_job_count = getattr(user, "active_job_count", 0) or 0
    job_suffix = "job" if active_job_count == 1 else "jobs"
    inactive_suffix = " (Inactive)" if not user.is_active else ""
    return f"{_person_label(user)} - {active_job_count} active {job_suffix}{inactive_suffix}"

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
        current_staff = getattr(self.instance, "assigned_staff", None)
        self.fields["assigned_staff"].queryset = _staff_assignment_queryset(include_user=current_staff)
        self.fields["assigned_staff"].label_from_instance = _staff_assignment_label
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


class StaffMaintenanceChargeSuggestionForm(forms.ModelForm):
    suggested_total = forms.DecimalField(
        required=False,
        decimal_places=2,
        max_digits=12,
        disabled=True,
        label="Computed suggested total",
    )

    class Meta:
        model = MaintenanceCharge
        fields = ["diagnosis", "repair_notes", "labor_cost", "material_cost", "suggested_total"]
        widgets = {
            "diagnosis": forms.Textarea(attrs={"rows": 3, "placeholder": "Summarize the diagnosed cause of the issue."}),
            "repair_notes": forms.Textarea(attrs={"rows": 4, "placeholder": "Describe the repair work performed or planned."}),
            "labor_cost": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "material_cost": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    def __init__(self, *args, maintenance_request=None, staff_user=None, **kwargs):
        self.maintenance_request = maintenance_request
        self.staff_user = staff_user
        super().__init__(*args, **kwargs)
        self.fields["diagnosis"].label = "Diagnosis"
        self.fields["repair_notes"].label = "Repair notes"
        self.fields["labor_cost"].label = "Labor cost"
        self.fields["material_cost"].label = "Material cost"
        self.fields["suggested_total"].initial = getattr(self.instance, "suggested_total", None)

    def clean(self):
        cleaned_data = super().clean()
        req = self.maintenance_request
        if req is None:
            raise forms.ValidationError("Maintenance request context is required.")
        if req.review_status != "ACCEPTED" or req.assigned_staff_id != getattr(self.staff_user, "id", None):
            raise forms.ValidationError("You can only suggest costs for accepted requests assigned to you.")

        current_status = self.instance.status if self.instance and self.instance.pk else MaintenanceCharge.STATUS_PENDING_REVIEW
        if current_status != MaintenanceCharge.STATUS_PENDING_REVIEW:
            raise forms.ValidationError("This repair cost suggestion is locked after admin review.")

        cleaned_data["suggested_total"] = (
            (cleaned_data.get("labor_cost") or 0) + (cleaned_data.get("material_cost") or 0)
        )
        return cleaned_data

    def save(self, commit=True):
        charge = super().save(commit=False)
        charge.maintenance_request = self.maintenance_request
        if not charge.suggested_by_id:
            charge.suggested_by = self.staff_user
        if commit:
            charge.save()
        return charge


class AdminMaintenanceChargeReviewForm(forms.ModelForm):
    REVIEW_ACTION_APPROVE_AS_IS = "approve_as_is"
    REVIEW_ACTION_APPROVE_ADJUSTED = "approve_adjusted"
    REVIEW_ACTION_NO_CHARGE = "no_charge"

    admin_approved_total = forms.DecimalField(
        required=False,
        decimal_places=2,
        max_digits=12,
        min_value=0,
        label="Approved amount",
    )

    class Meta:
        model = MaintenanceCharge
        fields = ["admin_approved_total"]
        widgets = {
            "admin_approved_total": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    def __init__(self, *args, maintenance_request=None, admin_user=None, action=None, **kwargs):
        self.maintenance_request = maintenance_request
        self.admin_user = admin_user
        self.action = action
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.admin_approved_total is None:
            self.initial.setdefault("admin_approved_total", self.instance.suggested_total)

    def clean(self):
        cleaned_data = super().clean()
        req = self.maintenance_request
        if req is None:
            raise forms.ValidationError("Maintenance request context is required.")
        if not self.instance or not self.instance.pk:
            raise forms.ValidationError("A staff cost suggestion is required before admin review.")
        if req.review_status != "ACCEPTED":
            raise forms.ValidationError("Only accepted maintenance requests can receive a repair charge decision.")
        if self.instance.status != MaintenanceCharge.STATUS_PENDING_REVIEW:
            raise forms.ValidationError("This repair cost suggestion is already locked after admin review.")
        if self.action not in {
            self.REVIEW_ACTION_APPROVE_AS_IS,
            self.REVIEW_ACTION_APPROVE_ADJUSTED,
            self.REVIEW_ACTION_NO_CHARGE,
        }:
            raise forms.ValidationError("Choose a valid admin repair charge action.")

        if self.action == self.REVIEW_ACTION_APPROVE_AS_IS:
            cleaned_data["admin_approved_total"] = self.instance.suggested_total
        elif self.action == self.REVIEW_ACTION_APPROVE_ADJUSTED:
            approved_total = cleaned_data.get("admin_approved_total")
            if approved_total is None:
                self.add_error("admin_approved_total", "Enter the approved amount when adjusting the staff suggestion.")
        elif self.action == self.REVIEW_ACTION_NO_CHARGE:
            cleaned_data["admin_approved_total"] = None
        return cleaned_data

    def save(self, commit=True):
        charge = super().save(commit=False)
        charge.approved_by = self.admin_user
        charge.approved_at = timezone.now()
        if self.action == self.REVIEW_ACTION_NO_CHARGE:
            charge.admin_approved_total = None
            charge.status = MaintenanceCharge.STATUS_NO_CHARGE
        else:
            charge.status = MaintenanceCharge.STATUS_READY_FOR_BILLING
        if commit:
            charge.save()
        return charge
