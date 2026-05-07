"""
Water Billing Services - Manual Computation Only
Safe implementation for production system with NO auto-generation
"""
from decimal import Decimal
from datetime import date
import logging

from django.db import transaction
from django.core.exceptions import ValidationError

from billing.models import MonthlyBill
from .models import WaterRate, WaterReading, WaterComputationLog

logger = logging.getLogger(__name__)


def get_active_rate_for_date(target_date: date) -> WaterRate:
    """
    Get the active water rate for a specific date.
    Returns the most recent rate that was effective on or before target_date.
    
    Raises:
        ValidationError: If no active rate exists for the date
    """
    rate = WaterRate.objects.filter(
        effective_date__lte=target_date,
        is_active=True
    ).order_by('-effective_date').first()
    
    if not rate:
        raise ValidationError(
            f"No active water rate found for {target_date}. "
            f"Please configure a WaterRate in admin first."
        )
    
    return rate


def compute_water_reading(water_reading: WaterReading) -> Decimal:
    """
    Compute water consumption and amount for a reading.
    Updates the reading object in-place but does NOT save.
    
    Args:
        water_reading: WaterReading instance to compute
        
    Returns:
        computed_amount: The water bill amount
    """
    # Get rate for this period
    rate = get_active_rate_for_date(water_reading.reading_month)
    
    # Store rate snapshot
    water_reading.rate_used = rate.rate_per_cu_m
    
    # Calculate consumption
    if water_reading.is_first_reading:
        water_reading.consumption = Decimal("0.00")
    else:
        consumption = water_reading.current_reading - water_reading.previous_reading
        if consumption < 0:
            raise ValidationError(
                f"Invalid consumption: {consumption}. "
                "Current reading must be >= previous reading."
            )
        water_reading.consumption = consumption.quantize(Decimal("0.01"))
    
    # Calculate amount
    water_reading.computed_amount = (
        water_reading.consumption * water_reading.rate_used
    ).quantize(Decimal("0.01"))
    
    logger.info(
        f"Computed water for {water_reading}: "
        f"consumption={water_reading.consumption}, "
        f"rate={water_reading.rate_used}, "
        f"amount={water_reading.computed_amount}"
    )
    
    return water_reading.computed_amount


@transaction.atomic
def create_or_update_monthly_bill_from_reading(
    water_reading: WaterReading,
    computed_by=None,
    force_update=False
) -> tuple[MonthlyBill, bool]:
    """
    Create or update MonthlyBill from WaterReading.
    SAFE: Uses get_or_create with unique constraint (lease, billing_month)
    
    Args:
        water_reading: Validated WaterReading with computed values
        computed_by: User who triggered computation (for audit)
        force_update: If True, update existing UNPAID bill; if False, skip existing
        
    Returns:
        (monthly_bill, created): The bill and whether it was created new
        
    Raises:
        ValidationError: If bill exists and is PAID (cannot modify)
    """
    # Ensure reading is computed
    if water_reading.computed_amount == 0 and not water_reading.is_first_reading:
        compute_water_reading(water_reading)
    
    lease = water_reading.lease
    billing_month = water_reading.reading_month
    water_amount = water_reading.computed_amount
    
    # Use database-level locking to prevent race conditions
    bill, created = MonthlyBill.objects.select_for_update().get_or_create(
        lease=lease,
        billing_month=billing_month,
        defaults={
            'due_date': _calculate_due_date(lease, billing_month),
            'base_rent': lease.monthly_rent or 0,
            'water_amount': water_amount,
            'interest': 0,  # Will be computed by billing services if late
            'total_due': (lease.monthly_rent or 0) + water_amount,
            'status': 'UNPAID',
            'bill_type': 'RENT',
            'water_computed_from_system': True,
            'source_water_reading': water_reading,
        }
    )
    
    if not created:
        # Bill already exists - check if we can update
        if bill.status == 'PAID':
            raise ValidationError(
                f"MonthlyBill #{bill.id} is already PAID. "
                "Cannot modify water amount. "
                "If correction is needed, contact system admin."
            )
        
        if not force_update:
            logger.info(f"MonthlyBill #{bill.id} exists, skipping update (force_update=False)")
            return bill, created
        
        # Safe to update (UNPAID status) - ALWAYS update water from reading
        # This ensures water_amount is always transferred from WaterReading
        old_water = bill.water_amount
        bill.water_amount = water_amount
        bill.total_due = bill.base_rent + water_amount + bill.interest
        bill.water_computed_from_system = True
        bill.source_water_reading = water_reading
        bill.save()
        
        logger.info(
            f"Updated MonthlyBill #{bill.id}: "
            f"water {old_water} → {water_amount}, "
            f"total_due now {bill.total_due}"
        )
    
    # Log the computation (bill is already linked via source_water_reading)
    WaterComputationLog.objects.create(
        water_reading=water_reading,
        monthly_bill=bill,
        computed_by=computed_by,
        notes=f"Bill {'created' if created else 'updated'} from reading"
    )
    
    return bill, created


def _calculate_due_date(lease, billing_month: date) -> date:
    """Calculate due date based on lease configuration"""
    from billing.services import due_date_for_month
    
    due_day = getattr(lease, 'due_day', 5)  # Default to 5th if not set
    return due_date_for_month(billing_month.year, billing_month.month, due_day)


def validate_reading_can_be_modified(water_reading: WaterReading) -> bool:
    """
    Check if a WaterReading can still be modified.
    Returns False if linked bill is PAID.
    """
    return not water_reading.generated_monthly_bills.filter(status='PAID').exists()


def get_or_create_reading(
    lease,
    reading_month: date,
    previous_reading: Decimal = None,
    current_reading: Decimal = None,
    is_first_reading: bool = False,
    entered_by=None
) -> tuple[WaterReading, bool]:
    """
    Get existing WaterReading or create new one.
    For manual entry workflow.
    """
    reading, created = WaterReading.objects.get_or_create(
        lease=lease,
        reading_month=reading_month,
        defaults={
            'previous_reading': previous_reading or Decimal("0.00"),
            'current_reading': current_reading or Decimal("0.00"),
            'is_first_reading': is_first_reading,
            'read_by': entered_by,
        }
    )
    
    if not created:
        logger.info(f"Found existing reading for {lease} - {reading_month}")
    
    return reading, created
