from decimal import Decimal

from django.conf import settings
from django.db import models
from rentals.models import Lease, get_user_files_storage


class MaintenanceRequest(models.Model):
    CATEGORY_CHOICES = [
        ("PLUMBING", "Plumbing"),
        ("ELECTRICAL", "Electrical"),
        ("STRUCTURAL", "Structural"),
        ("OTHER", "Other"),
    ]

    STATUS_CHOICES = [
        ("OPEN", "Open"),
        ("IN_PROGRESS", "In Progress"),
        ("RESOLVED", "Resolved"),
        ("CLOSED", "Closed"),
    ]

    REVIEW_STATUS_CHOICES = [
        ("PENDING", "Pending Admin Review"),
        ("ACCEPTED", "Accepted"),
        ("REJECTED", "Rejected"),
    ]

    SCHEDULE_DECISION_CHOICES = [
        ("PENDING", "Pending Admin Review"),
        ("APPROVED", "Approved"),
        ("RESCHEDULED", "Rescheduled"),
        ("DECLINED", "Declined"),
    ]

    # Admin-only (tenant does NOT set this)
    PRIORITY_CHOICES = [
        ("LOW", "Low"),
        ("MEDIUM", "Medium"),
        ("HIGH", "High"),
        ("URGENT", "Urgent"),
    ]

    tenant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="maintenance_requests")
    lease = models.ForeignKey(Lease, on_delete=models.SET_NULL, null=True, blank=True, related_name="maintenance_requests")
    assigned_staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_maintenance_requests",
        limit_choices_to={"role": "STAFF"},
        help_text="Staff member assigned after admin acceptance.",
    )

    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    title = models.CharField(max_length=120)
    description = models.TextField()
    photo = models.ImageField(
        upload_to="maintenance/",
        storage=get_user_files_storage(),
        null=True,
        blank=True,
    )
    requested_schedule_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Tenant's preferred date and time for maintenance visit.",
    )
    schedule_decision = models.CharField(
        max_length=20,
        choices=SCHEDULE_DECISION_CHOICES,
        default="PENDING",
    )
    admin_scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Admin-approved or rescheduled maintenance visit time.",
    )
    schedule_admin_note = models.TextField(blank=True, default="")

    review_status = models.CharField(max_length=20, choices=REVIEW_STATUS_CHOICES, default="PENDING")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="OPEN")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="MEDIUM")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Admin-entered info
    fixed_by = models.CharField(max_length=120, blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)

    # NLP auto-prediction (English only — multilingual support is future work)
    nlp_priority = models.CharField(max_length=10, blank=True, default="",
        help_text="Priority predicted by NLP model from description text")
    nlp_priority_confidence = models.FloatField(null=True, blank=True,
        help_text="Confidence score (0.0-1.0) of the NLP priority prediction")

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    @property
    def photo_url(self):
        """Return a browser-ready URL for the maintenance request photo."""
        if not self.photo or not getattr(self.photo, 'name', None):
            return ""

        try:
            return self.photo.url
        except Exception:
            try:
                return self.photo.storage.url(self.photo.name)
            except Exception:
                return ""



class MaintenanceCharge(models.Model):
    STATUS_PENDING_REVIEW = "PENDING_REVIEW"
    STATUS_NO_CHARGE = "NO_CHARGE"
    STATUS_APPROVED = "APPROVED"
    STATUS_READY_FOR_BILLING = "READY_FOR_BILLING"
    STATUS_ADDED_TO_BILL = "ADDED_TO_BILL"

    STATUS_CHOICES = [
        (STATUS_PENDING_REVIEW, "Pending Review"),
        (STATUS_NO_CHARGE, "No Charge"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_READY_FOR_BILLING, "Ready for Billing"),
        (STATUS_ADDED_TO_BILL, "Added to Bill"),
    ]

    maintenance_request = models.OneToOneField(
        MaintenanceRequest,
        on_delete=models.CASCADE,
        related_name="charge",
    )
    suggested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="suggested_maintenance_charges",
    )
    diagnosis = models.TextField(blank=True, default="")
    repair_notes = models.TextField(blank=True, default="")
    labor_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    material_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    suggested_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    admin_approved_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING_REVIEW)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_maintenance_charges",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    bill_line_item = models.ForeignKey(
        "billing.BillLineItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="maintenance_charges",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        labor_cost = self.labor_cost or Decimal("0.00")
        material_cost = self.material_cost or Decimal("0.00")
        self.suggested_total = (labor_cost + material_cost).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Charge for maintenance #{self.maintenance_request_id} ({self.status})"
