from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime
from billing.models import MonthlyBill
import random

class Command(BaseCommand):
    help = 'Fix billing status to have realistic unpaid bills for recent months'

    def handle(self, *args, **options):
        self.stdout.write('Fixing billing status for realistic data...')
        
        today = timezone.now().date()
        
        # Update bills for the last 4 months to have some unpaid bills
        for i in range(4):  # Last 4 months
            # Calculate month from current date going back
            if i == 0:
                month_date = today.replace(day=1)  # Current month
            else:
                month_year = today.year
                month_month = today.month - i
                while month_month <= 0:
                    month_month += 12
                    month_year -= 1
                month_date = datetime(month_year, month_month, 1).date()
            
            self.stdout.write(f'Updating bills for {month_date.strftime("%Y-%m")}...')
            
            # Get all bills for this month
            bills = MonthlyBill.objects.filter(billing_month=month_date)
            
            for bill in bills:
                # For recent months, make some bills unpaid (30% chance)
                if random.random() < 0.3:
                    bill.status = 'UNPAID'
                    bill.paid_at = None
                    self.stdout.write(f'  Made {bill.lease.unit.number} bill UNPAID')
                else:
                    # Keep as paid but ensure paid_at is set
                    if not bill.paid_at:
                        bill.paid_at = month_date.replace(day=random.randint(16, 28))
                    bill.status = 'PAID'
                
                bill.save()
        
        # Show updated statistics
        total_bills = MonthlyBill.objects.count()
        paid_bills = MonthlyBill.objects.filter(status='PAID').count()
        unpaid_bills = MonthlyBill.objects.filter(status='UNPAID').count()
        
        self.stdout.write(self.style.SUCCESS(f'Updated billing status:'))
        self.stdout.write(f'  Total bills: {total_bills}')
        self.stdout.write(f'  Paid bills: {paid_bills}')
        self.stdout.write(f'  Unpaid bills: {unpaid_bills}')
        
        # Show recent months breakdown
        self.stdout.write('\nRecent months breakdown:')
        for i in range(4):
            if i == 0:
                month_date = today.replace(day=1)
            else:
                month_year = today.year
                month_month = today.month - i
                while month_month <= 0:
                    month_month += 12
                    month_year -= 1
                month_date = datetime(month_year, month_month, 1).date()
            
            bills_this_month = MonthlyBill.objects.filter(billing_month=month_date)
            paid = bills_this_month.filter(status='PAID').count()
            unpaid = bills_this_month.filter(status='UNPAID').count()
            self.stdout.write(f'  {month_date.strftime("%Y-%m")}: {paid} paid, {unpaid} unpaid')
