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

