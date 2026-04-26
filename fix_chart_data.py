from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta, datetime
from billing.models import MonthlyBill
from rentals.models import Lease

class Command(BaseCommand):
    help = 'Fix chart data to show correct months for 2026'

    def handle(self, *args, **options):
        self.stdout.write('Fixing chart data for 2026...')
        
        # Delete existing bills
        MonthlyBill.objects.all().delete()
        self.stdout.write('Deleted existing bills')
        
        # Create bills for 2026 (current year)
        today = timezone.now().date()
        self.stdout.write(f'Creating bills for 2026, current date: {today}')
        
        for i in range(12):
            # Calculate month from current date going back
            if i == 0:
                month_date = today.replace(day=1)
            else:
                month_year = today.year
                month_month = today.month - i
                while month_month <= 0:
                    month_month += 12
                    month_year -= 1
                month_date = datetime(month_year, month_month, 1).date()
            
            self.stdout.write(f'Creating bills for {month_date.strftime("%Y-%m")}')
            
            for lease in Lease.objects.filter(is_active=True):
                bill, created = MonthlyBill.objects.get_or_create(
                    lease=lease,
                    billing_month=month_date,
                    defaults={
                        'total_due': lease.monthly_rent,
                        'due_date': month_date.replace(day=15),
                        'status': 'PAID' if i < 8 else 'UNPAID',  # Last 4 months unpaid
                        'paid_at': month_date.replace(day=20) if i < 8 else None
                    }
                )
                if created:
                    self.stdout.write(f'  Created bill for {lease.unit.number} - {month_date.strftime("%Y-%m")}')
        
        self.stdout.write(self.style.SUCCESS(f'Total bills created: {MonthlyBill.objects.count()}'))
        
        # Show date range
        bills = MonthlyBill.objects.all().order_by('billing_month')
        self.stdout.write('Date range created:')
        for bill in bills[:12]:
            self.stdout.write(f'  {bill.billing_month} - {bill.status}')
