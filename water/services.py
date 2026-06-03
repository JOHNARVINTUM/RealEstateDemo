"""
Water Billing Services - Manual Computation Only
Safe implementation for production system with NO auto-generation
"""
from decimal import Decimal
from datetime import date
import logging

from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum

from billing.models import MonthlyBill
from .models import WaterBillingSettings, WaterRate, WaterReading, WaterComputationLog

logger = logging.getLogger(__name__)


def quantize_money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def is_water_bill_locked(bill: MonthlyBill | None) -> bool:
    return bool(bill and bill.water_paid > 0)


def refresh_bill_status_from_component_payments(bill: MonthlyBill) -> None:
    remaining_balance = (
        max(bill.base_rent - bill.rent_paid, Decimal("0.00"))
        + max(bill.water_amount - bill.water_paid, Decimal("0.00"))
        + max(bill.parking_fee - bill.parking_paid, Decimal("0.00"))
        + bill.interest
    ).quantize(Decimal("0.01"))
    has_any_payment = bill.rent_paid > 0 or bill.water_paid > 0 or bill.parking_paid > 0

    if remaining_balance == 0 and has_any_payment:
        bill.status = "PAID"
        bill.paid_at = bill.paid_at or bill.rent_paid_at or bill.water_paid_at
    elif has_any_payment:
        bill.status = "PARTIALLY_PAID"
        bill.paid_at = None
    else:
        bill.status = "UNPAID"
        bill.paid_at = None


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


def get_water_billing_settings_for_month(target_date: date) -> WaterBillingSettings:
    settings, _ = WaterBillingSettings.objects.get_or_create(
        reading_month=target_date,
        defaults={
            "shared_pump_total": Decimal("0.00"),
            "vat_percent": Decimal("12.00"),
        },
    )
    return settings


def previous_unpaid_water_balance(lease, reading_month: date) -> Decimal:
    total = Decimal("0.00")
    bills = MonthlyBill.objects.filter(
        lease=lease,
        billing_month__lt=reading_month,
    ).filter(Q(status="UNPAID") | Q(status="PARTIALLY_PAID"))
    for bill in bills:
        total += bill.water_balance
    return quantize_money(total)


def total_consumption_for_month(reading_month: date, pending_readings=None) -> Decimal:
    total = Decimal("0.00")
    if pending_readings:
        for reading in pending_readings:
            total += Decimal(reading.consumption or 0)

    existing_total = WaterReading.objects.filter(
        reading_month=reading_month
    ).aggregate(total=Sum("consumption"))["total"] or Decimal("0.00")
    return quantize_money(total + existing_total)


def compute_water_reading(
    water_reading: WaterReading,
    *,
    total_month_consumption: Decimal | None = None,
    shared_pump_total: Decimal | None = None,
    vat_percent: Decimal | None = None,
    previous_unpaid_water_amount: Decimal | None = None,
) -> Decimal:
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
    
    settings = get_water_billing_settings_for_month(water_reading.reading_month)
    if shared_pump_total is None:
        shared_pump_total = settings.shared_pump_total
    if vat_percent is None:
        vat_percent = settings.vat_percent
    if previous_unpaid_water_amount is None:
        previous_unpaid_water_amount = previous_unpaid_water_balance(
            water_reading.lease,
            water_reading.reading_month,
        )
    if total_month_consumption is None:
        total_month_consumption = total_consumption_for_month(water_reading.reading_month)

    water_reading.base_water_amount = quantize_money(
        water_reading.consumption * water_reading.rate_used
    )
    if total_month_consumption > 0 and shared_pump_total > 0:
        water_reading.shared_pump_amount = quantize_money(
            (water_reading.consumption / total_month_consumption) * shared_pump_total
        )
    else:
        water_reading.shared_pump_amount = Decimal("0.00")

    water_reading.vat_percent = quantize_money(vat_percent)
    vat_base = water_reading.base_water_amount + water_reading.shared_pump_amount
    water_reading.vat_amount = quantize_money(vat_base * (water_reading.vat_percent / Decimal("100.00")))
    water_reading.previous_unpaid_water_amount = quantize_money(previous_unpaid_water_amount)
    water_reading.computed_amount = quantize_money(
        water_reading.base_water_amount
        + water_reading.shared_pump_amount
        + water_reading.vat_amount
        + water_reading.previous_unpaid_water_amount
    )
    
    logger.info(
        f"Computed water for {water_reading}: "
        f"consumption={water_reading.consumption}, "
        f"rate={water_reading.rate_used}, "
        f"base={water_reading.base_water_amount}, "
        f"pump={water_reading.shared_pump_amount}, "
        f"vat={water_reading.vat_amount}, "
        f"previous_unpaid_water={water_reading.previous_unpaid_water_amount}, "
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
        ValidationError: If bill exists and water was already paid (cannot modify water)
    """
    # Ensure reading is computed
    if water_reading.computed_amount == 0 and not water_reading.is_first_reading:
        compute_water_reading(water_reading)
    
    lease = water_reading.lease
    billing_month = water_reading.reading_month
    water_amount = water_reading.computed_amount
    parking_fee = lease.parking_fee
    
    # Use database-level locking to prevent race conditions
    bill, created = MonthlyBill.objects.select_for_update().get_or_create(
        lease=lease,
        billing_month=billing_month,
        defaults={
            'due_date': _calculate_due_date(lease, billing_month),
            'base_rent': lease.monthly_rent or 0,
            'water_amount': water_amount,
            'interest': 0,  # Will be computed by billing services if late
            'parking_fee': parking_fee,
            'total_due': (lease.monthly_rent or 0) + water_amount + parking_fee,
            'status': 'UNPAID',
            'bill_type': 'RENT',
            'water_computed_from_system': True,
            'source_water_reading': water_reading,
        }
    )
    
    if not created:
        # Bill already exists - check if we can update the water portion.
        if is_water_bill_locked(bill):
            raise ValidationError(
                f"MonthlyBill #{bill.id} already has a paid water amount. "
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
        bill.total_due = bill.base_rent + water_amount + bill.parking_fee + bill.interest
        bill.water_computed_from_system = True
        bill.source_water_reading = water_reading
        refresh_bill_status_from_component_payments(bill)
        bill.save(update_fields=[
            "water_amount",
            "total_due",
            "water_computed_from_system",
            "source_water_reading",
            "status",
            "paid_at",
        ])
        
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
    Returns False if linked bill already has paid water.
    """
    return not water_reading.generated_monthly_bills.filter(water_paid__gt=0).exists()


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
