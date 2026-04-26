from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
from billing.models import MonthlyBill
import random

class Command(BaseCommand):
    help = 'Fix payment dates to create more realistic payment patterns'

    def handle(self, *args, **options):
        self.stdout.write('Fixing payment dates for realistic patterns...')
        
        # Get all paid bills
        paid_bills = MonthlyBill.objects.filter(status='PAID')
        
        for bill in paid_bills:
            # Create more realistic payment patterns
            # 70% chance of on-time payment, 30% chance of late payment
            if random.random() < 0.7:
                # On-time payment (before or on due date)
                days_before_due = random.randint(1, 5)
                paid_date = bill.due_date - timedelta(days=days_before_due)
            else:
                # Late payment (1-10 days after due date)
                days_late = random.randint(1, 10)
                paid_date = bill.due_date + timedelta(days=days_late)
            
            bill.paid_at = paid_date
            bill.save()
            
            payment_status = "ON TIME" if paid_date <= bill.due_date else f"{(paid_date - bill.due_date).days} DAYS LATE"
            self.stdout.write(f'Updated {bill.lease.unit.number} - {bill.billing_month}: Paid {paid_date} ({payment_status})')
        
        self.stdout.write(self.style.SUCCESS(f'Updated payment dates for {paid_bills.count()} bills'))
        
        # Recalculate risk classifications
        from rentals.services import TenantRiskService
        updated_count = TenantRiskService.update_all_tenant_risks()
        self.stdout.write(self.style.SUCCESS(f'Recalculated risk for {updated_count} tenants'))
