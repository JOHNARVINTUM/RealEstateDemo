from django.db import models
from django.conf import settings


def normalize_reference_code(value):
    value = (value or "").strip()
    if not value:
        return ""
    if value.upper().startswith("REF-"):
        return value
    return f"REF-{value}"


class ManualPayment(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "PENDING"),
        ("APPROVED", "APPROVED"),
        ("REJECTED", "REJECTED"),
    ]
    
    PAYMENT_TYPE_CHOICES = [
        ("full", "Full Payment"),
        ("rent_only", "Monthly Rent"),
        ("water_only", "Water Only"),
        ("maintenance_only", "Maintenance Charge Only"),
        ("move_in", "Move-in Payment"),
    ]

    PAYMENT_METHOD_CHOICES = [
        ("GCASH", "GCash QR"),
        ("CASH", "Face-to-Face Cash"),
        ("PAYMONGO", "PayMongo Checkout"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    reference_code = models.CharField(max_length=80, blank=True, default="")
    
    # ADDED: This reconnects your Python code to the database column!
    # We use a CharField because we are passing a comma-separated string like "27,28"
    bill_ids = models.CharField(max_length=255, default="")
    
    # NEW: Track payment type for partial payments
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES, default="full")
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES, default="GCASH")
    
    # Store the actual payment amount
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Face-to-Face cash payment scheduling (optional)
    preferred_date = models.DateField(null=True, blank=True)
    preferred_time = models.TimeField(null=True, blank=True)
    tenant_note = models.TextField(blank=True, default="")

    # Schedule confirmation for F2F payments
    schedule_confirmed = models.BooleanField(default=False, help_text="Admin has confirmed the F2F appointment time")
    schedule_admin_note = models.TextField(blank=True, default="", help_text="Latest admin note for F2F schedule changes")

    # PayMongo Checkout fields
    checkout_session_id = models.CharField(max_length=100, blank=True, default="")
    checkout_url = models.URLField(max_length=500, blank=True, default="")
    paymongo_payment_id = models.CharField(max_length=100, blank=True, default="")
    paid_via = models.CharField(max_length=30, blank=True, default="", help_text="Actual method used in PayMongo (gcash, card, grab_pay, etc.)")
    metadata = models.JSONField(default=dict, blank=True, help_text="Store PayMongo metadata including lease_id, payment_type, etc.")

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["user", "status", "created_at"],
                name="pay_user_stat_created_idx",
            ),
            models.Index(
                fields=["status", "payment_method", "created_at"],
                name="pay_stat_method_created_idx",
            ),
            models.Index(
                fields=["created_at"],
                name="pay_created_idx",
            ),
            models.Index(
                fields=["payment_method", "created_at"],
                name="pay_method_created_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        self.reference_code = normalize_reference_code(self.reference_code)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.email} - {self.payment_method} - ₱{self.amount} ({self.status})"
