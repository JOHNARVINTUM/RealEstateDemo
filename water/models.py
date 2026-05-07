"""
Water Billing Models - Manual Computation Only
Safe, additive implementation for production system
"""
from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

User = get_user_model()


class WaterRate(models.Model):
    """
    Global water rate configuration.
    Admin sets this when supplier changes prices.
    """
    effective_date = models.DateField(
        help_text="Date when this rate becomes active"
    )
    rate_per_cu_m = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        help_text="Price per cubic meter (e.g., 45.00)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Uncheck to disable this rate"
    )
    notes = models.TextField(
        blank=True,
        help_text="Optional notes (e.g., 'Supplier price increase June 2026')"
    )
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name="created_water_rates"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-effective_date']
        verbose_name = "Water Rate"
        verbose_name_plural = "Water Rates"
    
    def __str__(self):
        return f"₱{self.rate_per_cu_m}/m³ (from {self.effective_date})"
    
    def clean(self):
        if self.rate_per_cu_m <= 0:
            raise ValidationError("Rate must be greater than zero")


class WaterReading(models.Model):
    """
    Manual meter readings per tenant per month.
    Admin enters these, system computes water bill.
    """
    lease = models.ForeignKey(
        "rentals.Lease",
        on_delete=models.CASCADE,
        related_name="water_readings",
        help_text="Tenant lease (links to unit)"
    )
    reading_month = models.DateField(
        help_text="Month being billed (enter 1st of month, e.g., 2026-06-01)"
    )
    
    # Readings
    previous_reading = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Previous meter reading (cubic meters)"
    )
    current_reading = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Current meter reading (cubic meters)"
    )
    
    # Computed values (stored for audit)
    consumption = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Computed: Current - Previous (auto-filled)"
    )
    rate_used = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Rate per m³ used for calculation (snapshot)"
    )
    computed_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Computed: Consumption × Rate (auto-filled)"
    )
    
    # Special flags
    is_first_reading = models.BooleanField(
        default=False,
        help_text="Check if this is the initial move-in reading (no consumption charged)"
    )
    
    # Audit
    read_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entered_water_readings"
    )
    read_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('lease', 'reading_month')
        ordering = ['-reading_month', '-id']
        verbose_name = "Water Reading"
        verbose_name_plural = "Water Readings"
    
    def __str__(self):
        unit_num = self.lease.unit.number if self.lease and self.lease.unit else "Unknown"
        return f"Unit {unit_num} - {self.reading_month.strftime('%b %Y')}"
    
    def clean(self):
        # Validate readings
        if self.current_reading < 0 or self.previous_reading < 0:
            raise ValidationError("Readings cannot be negative")
        
        if not self.is_first_reading and self.current_reading < self.previous_reading:
            raise ValidationError(
                f"Current reading ({self.current_reading}) must be >= "
                f"previous reading ({self.previous_reading}). "
                f"Check 'First Reading' if this is initial move-in."
            )
        
        # Auto-compute values
        if self.is_first_reading:
            self.consumption = Decimal("0.00")
        else:
            self.consumption = (self.current_reading - self.previous_reading).quantize(Decimal("0.01"))
        
        # Get active rate for this month
        rate = self.get_rate_for_month()
        if rate:
            self.rate_used = rate.rate_per_cu_m
        
        self.computed_amount = (self.consumption * self.rate_used).quantize(Decimal("0.01"))
    
    def get_rate_for_month(self):
        """Get the active water rate for this reading month"""
        from django.db.models import Q
        
        return WaterRate.objects.filter(
            effective_date__lte=self.reading_month,
            is_active=True
        ).order_by('-effective_date').first()
    
    def save(self, *args, **kwargs):
        # Safety check: prevent modification if bill already created and paid
        # Check if any MonthlyBill references this reading and is PAID
        if self.pk:
            from billing.models import MonthlyBill
            paid_bill = MonthlyBill.objects.filter(
                source_water_reading=self,
                status='PAID'
            ).first()
            if paid_bill:
                raise ValidationError(
                    "Cannot modify reading - linked MonthlyBill is already PAID. "
                    "Contact system admin if correction needed."
                )
        
        self.full_clean()
        super().save(*args, **kwargs)


class WaterComputationLog(models.Model):
    """
    Audit log for water computations.
    Tracks when readings were converted to MonthlyBills.
    """
    water_reading = models.ForeignKey(
        WaterReading,
        on_delete=models.CASCADE,
        related_name="computation_logs"
    )
    monthly_bill = models.ForeignKey(
        "billing.MonthlyBill",
        on_delete=models.CASCADE,
        related_name="water_computation_logs"
    )
    computed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True
    )
    computed_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-computed_at']
    
    def __str__(self):
        return f"{self.water_reading} → Bill #{self.monthly_bill.id}"


# ============================================================================
# LEGACY MODELS (Preserved for backward compatibility)
# These models are maintained for existing data. New water billing uses
# WaterReading + WaterRate above.
# ============================================================================

class WaterBill(models.Model):
    """
    LEGACY MODEL - Preserved for existing data.
    New system uses WaterReading + manual MonthlyBill creation.
    """
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("POSTED", "Posted"),
    ]

    unit = models.ForeignKey("rentals.Unit", on_delete=models.CASCADE, related_name="legacy_water_bills")

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
        total = Decimal("0.00")
        for c in self.charges.all():
            total += (c.amount or 0)
        return total.quantize(Decimal("0.01"))

    @property
    def total_amount(self):
        return (self.consumption_amount + self.charges_total).quantize(Decimal("0.01"))


class WaterCharge(models.Model):
    """
    LEGACY MODEL - Extra charges for legacy WaterBill system.
    """
    bill = models.ForeignKey(WaterBill, on_delete=models.CASCADE, related_name="charges")

    label = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    def __str__(self):
        return f"{self.bill} - {self.label}"
