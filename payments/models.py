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
    
    # ADDED: This reconnects your Python code to the database column!
    # We use a CharField because we are passing a comma-separated string like "27,28"
    bill_ids = models.CharField(max_length=255, default="") 
    
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} - {self.reference_code} ({self.status})"