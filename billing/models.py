from django.db import models
from rentals.models import Lease
from decimal import Decimal
from datetime import date

class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"
        LATE = "LATE", "Late"

    

    lease = models.ForeignKey(Lease, on_delete=models.CASCADE)
    billing_month = models.DateField()  # store as first day of month e.g. 2026-02-01

    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)

    water_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    payment_reference = models.CharField(max_length=120, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lease", "billing_month"], name="unique_payment_per_month")
        ]

    def __str__(self):
        return f"{self.lease.unit.number} {self.billing_month} {self.status}"


class PaymentTransaction(models.Model):
    lease = models.ForeignKey(Lease, on_delete=models.CASCADE)
    reference = models.CharField(max_length=120)
    months_paid = models.PositiveSmallIntegerField(default=1)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    paid_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.lease.unit.number} {self.reference}"

class MonthlyBill(models.Model):
    STATUS_CHOICES = [
        ("UNPAID", "Unpaid"),
        ("PAID", "Paid"),
    ]

    lease = models.ForeignKey(Lease, on_delete=models.CASCADE, related_name="monthly_bills")
    billing_month = models.DateField()  # always first day of month

    due_date = models.DateField()
    base_rent = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    water_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    interest = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    total_due = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="UNPAID")

    paid_at = models.DateTimeField(null=True, blank=True)
    payment_reference = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("lease", "billing_month")
        ordering = ["-billing_month"]

    def __str__(self):
        return f"{self.lease} - {self.billing_month}"