from django.utils import timezone
from datetime import timedelta
from billing.models import MonthlyBill
from rentals.services import TenantRiskService

# Check a tenant with perfect payment records
tenant_email = 'michael.lewis@email.com'
print(f'Debugging payment timeliness for {tenant_email}:')
print('=' * 60)

# Get paid bills from last 6 months
six_months_ago = timezone.now() - timedelta(days=180)
paid_bills = MonthlyBill.objects.filter(
    lease__tenant__email=tenant_email,
    status='PAID',
    paid_at__gte=six_months_ago
)

print(f'Paid bills in last 6 months: {paid_bills.count()}')

if paid_bills.count() == 0:
    print('No paid bills in last 6 months - this is the issue!')
    print('Getting all paid bills:')
    all_paid = MonthlyBill.objects.filter(
        lease__tenant__email=tenant_email,
        status='PAID'
    )
    print(f'All paid bills: {all_paid.count()}')
    
    for bill in all_paid:
        print(f'  {bill.billing_month}: Paid {bill.paid_at} (Due {bill.due_date})')
        if bill.paid_at and bill.due_date:
            days_late = (bill.paid_at.date() - bill.due_date).days
            print(f'    Days late: {days_late}')
else:
    # Calculate on-time percentage
    total_days_late = 0
    on_time_count = 0
    
    for bill in paid_bills:
        if bill.paid_at and bill.due_date:
            days_late = (bill.paid_at.date() - bill.due_date).days
            if days_late <= 0:
                on_time_count += 1
            else:
                total_days_late += days_late
            print(f'{bill.billing_month}: {days_late} days late')
    
    total_bills = paid_bills.count()
    on_time_percentage = (on_time_count / total_bills) * 100
    print(f'On-time percentage: {on_time_percentage}%')
    print(f'On-time count: {on_time_count}/{total_bills}')

# Test the actual function
timeliness_score = TenantRiskService._calculate_payment_timeliness_for_tenant(tenant_email)
print(f'Calculated timeliness score: {timeliness_score}')
