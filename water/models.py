from decimal import Decimal
from django.db import models
from rentals.models import Unit  # adjust import if your Unit model is elsewhere

class WaterBill(models.Model):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("POSTED", "Posted"),
    ]

    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="water_bills")

    invoice_date = models.DateField(null=True, blank=True)
    invoice_number = models.CharField(max_length=50, blank=True)

    period_start = models.DateField()
    period_end = models.DateField()

    prev_reading = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    curr_reading = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    rate_per_cu_m = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="DRAFT")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("unit", "period_start", "period_end")
        ordering = ["-period_end", "-id"]

    def __str__(self):
        return f"{self.unit} Water {self.period_start} - {self.period_end}"

    @property
    def consumption(self):
        val = (self.curr_reading or 0) - (self.prev_reading or 0)
        return val if val > 0 else Decimal("0.00")

    @property
    def consumption_amount(self):
        return (self.consumption * (self.rate_per_cu_m or 0)).quantize(Decimal("0.01"))

    @property
    def charges_total(self):
        # sum of all extra charges
        total = Decimal("0.00")
        for c in self.charges.all():
            total += (c.amount or 0)
        return total.quantize(Decimal("0.01"))

    @property
    def total_amount(self):
        return (self.consumption_amount + self.charges_total).quantize(Decimal("0.01"))


class WaterCharge(models.Model):
    bill = models.ForeignKey(WaterBill, on_delete=models.CASCADE, related_name="charges")

    label = models.CharField(max_length=120)  # e.g. "Basic Charge", "VAT", "Sewer", "Past Due"
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    def __str__(self):
        return f"{self.bill} - {self.label}"
