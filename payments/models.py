from django.db import models
from django.conf import settings

class ManualPayment(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "PENDING"),
        ("APPROVED", "APPROVED"),
        ("REJECTED", "REJECTED"),
    ]
    
    PAYMENT_TYPE_CHOICES = [
        ("full", "Full Payment"),
        ("rent_only", "Rent Only"),
        ("water_only", "Water Only"),
    ]

    PAYMENT_METHOD_CHOICES = [
        ("GCASH", "GCash QR"),
        ("CASH", "Face-to-Face Cash"),
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

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} - {self.payment_method} - ₱{self.amount} ({self.status})"