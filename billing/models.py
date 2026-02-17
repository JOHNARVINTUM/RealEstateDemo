from django.db import models
from rentals.models import Lease

class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"
        LATE = "LATE", "Late"

    lease = models.ForeignKey(Lease, on_delete=models.CASCADE)
    billing_month = models.DateField()  # store as first day of month (e.g. 2026-02-01)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)

    # “QR testing”
    payment_reference = models.CharField(max_length=120, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.lease.unit.number} {self.billing_month} {self.status}"
