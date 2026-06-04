from django.db import models
from django.utils import timezone


class MonthlyBill(models.Model):
    STATUS_CHOICES = [
        ("UNPAID", "Unpaid"),
        ("PARTIALLY_PAID", "Partially Paid"),
        ("PAID", "Paid"),
    ]
    
    BILL_TYPE_CHOICES = [
        ("RENT", "Rent"),
        ("WATER", "Water"),
        ("PENALTY", "Penalty"),
    ]

    lease = models.ForeignKey("rentals.Lease", on_delete=models.CASCADE, related_name="monthly_bills")
    billing_month = models.DateField()  # recommended: month-start date (e.g., 2026-02-01)
    due_date = models.DateField(null=True, blank=True)
    bill_type = models.CharField(max_length=20, choices=BILL_TYPE_CHOICES, default="RENT")

    base_rent = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    water_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    interest = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="UNPAID")
    paid_at = models.DateTimeField(null=True, blank=True)
    payment_reference = models.CharField(max_length=80, blank=True, default="")
    
    parking_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Monthly parking fee (0 if no parking)")

    # NEW: Partial payment tracking for rent/water separation
    rent_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    water_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    parking_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rent_paid_at = models.DateTimeField(null=True, blank=True)
    water_paid_at = models.DateTimeField(null=True, blank=True)
    
    # NEW: Water computation audit (safe additive change)
    water_computed_from_system = models.BooleanField(
        default=False,
        help_text="True if water_amount was computed from WaterReading system"
    )
    # Optional FK to source reading for traceability
    source_water_reading = models.ForeignKey(
        "water.WaterReading",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_monthly_bills"
    )

    class Meta:
        unique_together = ("lease", "billing_month")
        ordering = ("-billing_month",)
        indexes = [
            models.Index(
                fields=["lease", "status", "billing_month"],
                name="bill_lease_stat_month_idx",
            ),
            models.Index(
                fields=["status", "due_date"],
                name="bill_stat_due_idx",
            ),
            models.Index(
                fields=["billing_month"],
                name="bill_month_idx",
            ),
            models.Index(
                fields=["status", "billing_month"],
                name="bill_stat_month_idx",
            ),
        ]

    def __str__(self):
        return f"{self.lease} - {self.billing_month} ({self.status})"

    @property
    def parking_balance(self):
        """Remaining parking fee to pay"""
        return max(self.parking_fee - self.parking_paid, 0)

    @property
    def rent_balance(self):
        """Remaining rent amount to pay"""
        return max(self.base_rent - self.rent_paid, 0)
    
    @property
    def water_balance(self):
        """Remaining water amount to pay"""
        return max(self.water_amount - self.water_paid, 0)
    
    @property
    def total_balance(self):
        """Total remaining balance including interest and parking"""
        if self.status == "PAID":
            return 0
        if self.base_rent == 0 and self.water_amount == 0 and self.total_due > 0:
            return max(self.total_due - (self.rent_paid + self.water_paid + self.parking_paid), 0)
        return self.rent_balance + self.water_balance + self.parking_balance + self.interest
    
    @property
    def is_rent_paid(self):
        """Check if rent is fully paid"""
        return self.rent_paid >= self.base_rent if self.base_rent > 0 else True
    
    @property
    def is_water_paid(self):
        """Check if water is fully paid"""
        return self.water_paid >= self.water_amount if self.water_amount > 0 else True
    
    @property
    def payment_status(self):
        """Detailed payment status"""
        if self.status == "PAID":
            return "FULLY_PAID"
        if self.is_rent_paid and self.is_water_paid and (self.base_rent > 0 or self.water_amount > 0):
            return "FULLY_PAID"
        elif self.is_rent_paid and self.base_rent > 0:
            return "RENT_PAID_WATER_PENDING"
        elif self.is_water_paid and self.water_amount > 0:
            return "WATER_PAID_RENT_PENDING"
        else:
            return "PARTIALLY_PAID" if (self.rent_paid > 0 or self.water_paid > 0 or self.status == "PARTIALLY_PAID") else "UNPAID"

    @property
    def billing_state(self):
        """Computed billing state for ledger display. No DB column."""
        from datetime import date as _date
        if self.status == "PAID" or (self.total_balance == 0 and self.status not in ("UNPAID", "PARTIALLY_PAID")):
            return "PAID"
        today = _date.today()
        current_month = today.replace(day=1)
        bill_month = self.billing_month.replace(day=1)
        if bill_month > current_month:
            return "UPCOMING"
        if bill_month == current_month:
            return "DUE"
        return "OVERDUE"

