from django.utils import timezone
from billing.models import MonthlyBill
from rentals.models import Lease
from django.db.models import Sum
from datetime import datetime

# Test the data generation logic
today = timezone.now().date()
print(f'Today: {today}')

# Get monthly rental income data for the past 12 months including current month
monthly_income_data = []
months_labels = []

# Calculate months from 11 months ago to current month (inclusive)
current_month_start = today.replace(day=1)

for i in range(12):
    # Calculate month date: current month minus i months
    if i == 0:
        # Current month
        month_date = current_month_start
    else:
        # Previous months
        # Go back i months from current month
        month_year = current_month_start.year
        month_month = current_month_start.month - i
        
        # Adjust year if month goes below 1
        while month_month <= 0:
            month_month += 12
            month_year -= 1
        
        month_date = datetime(month_year, month_month, 1).date()
    
    # Get paid bills for this month
    month_revenue = (
        MonthlyBill.objects.filter(
            status='PAID',
            paid_at__year=month_date.year,
            paid_at__month=month_date.month
        ).aggregate(total=Sum('total_due'))['total'] or 0
    )
    
    # Get expected revenue from active leases
    expected_revenue = (
        Lease.objects.filter(is_active=True)
        .aggregate(total=Sum('monthly_rent'))['total'] or 0
    )
    
    monthly_income_data.append({
        'month': month_date.strftime('%b %Y'),
        'actual': float(month_revenue),
        'expected': float(expected_revenue)
    })
    months_labels.append(month_date.strftime('%b'))
    
    print(f'{month_date.strftime("%b %Y")} - Actual: {month_revenue}, Expected: {expected_revenue}')

print(f'\nFinal monthly_income_data length: {len(monthly_income_data)}')
print(f'Final months_labels length: {len(months_labels)}')
print(f'Data sample: {monthly_income_data[:3]}')
print(f'Labels sample: {months_labels[:3]}')

# Check if we have any paid bills at all
paid_bills = MonthlyBill.objects.filter(status='PAID')
print(f'\nTotal paid bills: {paid_bills.count()}')
if paid_bills.exists():
    first_bill = paid_bills.first()
    print(f'First paid bill: {first_bill.billing_month} - {first_bill.paid_at}')

# Check active leases
active_leases = Lease.objects.filter(is_active=True)
print(f'Active leases: {active_leases.count()}')
if active_leases.exists():
    total_expected = active_leases.aggregate(total=Sum('monthly_rent'))['total'] or 0
    print(f'Total expected monthly rent: {total_expected}')
