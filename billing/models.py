from django.db import models
from django.utils import timezone


class MonthlyBill(models.Model):
    STATUS_CHOICES = [
        ("UNPAID", "Unpaid"),
        ("PAID", "Paid"),
    ]

    lease = models.ForeignKey("rentals.Lease", on_delete=models.CASCADE, related_name="monthly_bills")
    billing_month = models.DateField()  # recommended: month-start date (e.g., 2026-02-01)
    due_date = models.DateField(null=True, blank=True)

    base_rent = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    water_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    interest = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="UNPAID")
    paid_at = models.DateTimeField(null=True, blank=True)
    payment_reference = models.CharField(max_length=80, blank=True, default="")

    class Meta:
        unique_together = ("lease", "billing_month")
        ordering = ("-billing_month",)

    def __str__(self):
        return f"{self.lease} - {self.billing_month} ({self.status})"



