"""
Management command to add June 2026 upcoming bills to existing data.
"""

import random
from decimal import Decimal
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model

from rentals.models import Lease
from billing.models import MonthlyBill
from water.models import WaterRate, WaterReading

User = get_user_model()


class Command(BaseCommand):
    help = "Add June 2026 upcoming bills to existing database"

    def handle(self, *args, **options):
        self.stdout.write("Adding June 2026 upcoming bills...")
        
        with transaction.atomic():
            # Get active leases
            leases = Lease.objects.filter(is_active=True).select_related('unit', 'tenant')
            
            # Get water rate
            water_rate = WaterRate.objects.filter(is_active=True).latest('effective_date')
            rate = water_rate.rate_per_cu_m
            
            # Get admin user for water readings
            admin = User.objects.filter(role='ADMIN').first()
            
            created_bills = 0
            created_readings = 0
            
            # Add June 2026 bills
            for lease in leases:
                # Check if June 2026 bill already exists
                if MonthlyBill.objects.filter(
                    lease=lease,
                    billing_month__year=2026,
                    billing_month__month=6
                ).exists():
                    self.stdout.write(f"  Skipping {lease.unit.number} - June 2026 bill already exists")
                    continue
                
                # Get last water reading for this lease (should be May 2026)
                last_reading = WaterReading.objects.filter(
                    lease=lease
                ).order_by('-reading_month').first()
                
                if not last_reading:
                    self.stdout.write(f"  Skipping {lease.unit.number} - no previous water reading")
                    continue
                
                # Generate realistic water consumption (30-85 m³)
                consumption = Decimal(str(round(random.gauss(50, 12), 2)))
                consumption = max(Decimal('30'), min(Decimal('85'), consumption))
                new_reading = last_reading.current_reading + consumption
                
                # Create June 2026 water reading
                jun_reading = WaterReading.objects.create(
                    lease=lease,
                    reading_month=date(2026, 6, 1),
                    previous_reading=last_reading.current_reading,
                    current_reading=new_reading,
                    consumption=consumption,
                    rate_used=rate,
                    computed_amount=(consumption * rate).quantize(Decimal('0.01')),
                    is_first_reading=False,
                    read_by=admin
                )
                created_readings += 1
                
                # Calculate due date
                due_day = min(lease.due_day, 28)
                due_date = date(2026, 6, due_day)
                
                # Create June 2026 bill (upcoming, unpaid)
                MonthlyBill.objects.create(
                    lease=lease,
                    billing_month=date(2026, 6, 1),
                    due_date=due_date,
                    base_rent=lease.monthly_rent,
                    water_amount=jun_reading.computed_amount,
                    interest=Decimal('0'),
                    total_due=lease.monthly_rent + jun_reading.computed_amount,
                    status='UNPAID',
                    water_computed_from_system=True,
                    source_water_reading=jun_reading
                )
                created_bills += 1
                self.stdout.write(f"  Created June 2026 upcoming bill for unit {lease.unit.number}")
        
        self.stdout.write(self.style.SUCCESS(
            f"\nCreated {created_readings} water readings and {created_bills} upcoming bills for June 2026"
        ))
