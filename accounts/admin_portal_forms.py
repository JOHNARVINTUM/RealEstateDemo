from django import forms
from rentals.models import TenantProfile, Lease, Unit
from announcements.models import Announcement
from billing.models import MonthlyBill


class TenantProfileForm(forms.ModelForm):
    class Meta:
        model = TenantProfile
        fields = ["user", "full_name", "contact_no"]


class LeaseForm(forms.ModelForm):
    class Meta:
        model = Lease
        fields = ["tenant", "unit", "monthly_rent", "due_day", "start_date", "is_active"]


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

        from rentals.models import Lease

class LeaseForm(forms.ModelForm):
    class Meta:
        model = Lease
        fields = ["tenant", "unit", "monthly_rent", "due_day", "start_date", "is_active"]