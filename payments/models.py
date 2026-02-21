from django.db import models
from django.conf import settings

class ManualPayment(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "PENDING"),
        ("APPROVED", "APPROVED"),
        ("REJECTED", "REJECTED"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    reference_code = models.CharField(max_length=80)

    # store which bills are being paid
    bill_ids = models.JSONField(default=list, blank=True)

    # store expected amount for admin checking
    expected_amount = models.DecimalField(max_digits=12, decimal_places=2)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["reference_code"]),
        ]

    def __str__(self):
        return f"{self.user.email} {self.reference_code} ({self.status})"