import logging
from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from rentals.models import TenantProfile, Lease, Unit
from announcements.models import Announcement
from billing.models import MonthlyBill

User = get_user_model()
logger = logging.getLogger(__name__)


class TenantProfileForm(forms.ModelForm):
    # allow admin to either pick an existing tenant user or create a new one inline
    existing_user = forms.ModelChoiceField(
        queryset=User.objects.filter(role="TENANT").exclude(tenantprofile__isnull=False),
        required=False,
        label="Existing user (optional)",
    )

    new_email = forms.EmailField(required=False, label="New user email")
    new_username = forms.CharField(required=False, label="New username (optional)")
    new_password1 = forms.CharField(required=False, widget=forms.PasswordInput, label="Password")
    new_password2 = forms.CharField(required=False, widget=forms.PasswordInput, label="Confirm password")

    class Meta:
        model = TenantProfile
        fields = ["full_name", "contact_no"]

    def clean(self):
        cleaned = super().clean()
        existing = cleaned.get("existing_user")
        new_email = cleaned.get("new_email")
        pw1 = cleaned.get("new_password1")
        pw2 = cleaned.get("new_password2")

        if not existing and not new_email:
            raise ValidationError("Either select an existing user or provide a new user's email and password.")

        if new_email:
            # passwords required when creating a new user
            if not pw1 or not pw2:
                raise ValidationError("Please provide and confirm a password for the new user.")
            if pw1 != pw2:
                raise ValidationError("Passwords do not match.")
            if User.objects.filter(email=new_email).exists():
                raise ValidationError({"new_email": "A user with that email already exists."})

        return cleaned

    def save(self, commit=True):
        existing = self.cleaned_data.get("existing_user")
        if existing:
            user = existing
        else:
            email = self.cleaned_data.get("new_email")
            username = self.cleaned_data.get("new_username") or email
            pw = self.cleaned_data.get("new_password1")
            user = User.objects.create_user(email=email, username=username, password=pw)
            # ensure role is TENANT (User model default may already be TENANT)
            try:
                user.role = "TENANT"
                user.save()
            except Exception as e:
                logger.exception("Failed to set role on new user: %s", e)

        instance = super().save(commit=False)
        instance.user = user
        if commit:
            instance.save()
        return instance


class TenantProfileEditForm(forms.ModelForm):
    class Meta:
        model = TenantProfile
        fields = ["full_name", "contact_no"]


class LeaseForm(forms.ModelForm):
    class Meta:
        model = Lease
        fields = ["tenant", "unit", "monthly_rent", "due_day", "start_date", "is_active"]
        widgets = {
            # use a text input with a CSS class so JS datepicker (flatpickr) can enhance it
            "start_date": forms.DateInput(attrs={"type": "text", "class": "flatpickr", "autocomplete": "off"}),
        }

    def clean(self):
        cleaned = super().clean()
        unit = cleaned.get("unit")
        if unit:
            qs = Lease.objects.filter(unit=unit, is_active=True)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError({"unit": "Selected unit already has an active lease."})
        return cleaned

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # only allow selecting users with tenant role
        try:
            self.fields["tenant"].queryset = User.objects.filter(role="TENANT")
        except Exception as e:
            logger.exception("Failed to set tenant queryset: %s", e)


class UnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        fields = ["number", "is_active"]


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ["title", "body", "is_active"]

    def save(self, commit=True, user=None):
        instance = super().save(commit=False)
        if user:
            instance.created_by = user
        if commit:
            instance.save()
        return instance


class MonthlyBillForm(forms.ModelForm):
    class Meta:
        model = MonthlyBill
        fields = [
            "lease",
            "billing_month",
            "due_date",
            "base_rent",
            "water_amount",
            "interest",
            "total_due",
            "status",
            "paid_at",
            "payment_reference",
        ]