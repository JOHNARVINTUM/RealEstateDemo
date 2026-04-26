from billing.models import MonthlyBill
from rentals.models import Lease

# Check a tenant with 0 late payments and 0 unpaid bills
tenant_email = 'michael.lewis@email.com'
print(f'Checking payment history for {tenant_email}:')
print('=' * 60)

# Check if tenant has any leases
leases = Lease.objects.filter(tenant__email=tenant_email, is_active=True)
print(f'Active leases: {leases.count()}')

for lease in leases:
    print(f'  Unit: {lease.unit.number}, Rent: {lease.monthly_rent}')

# Check all bills for this tenant
all_bills = MonthlyBill.objects.filter(lease__tenant__email=tenant_email)
print(f'\nAll bills: {all_bills.count()}')

paid_bills = all_bills.filter(status='PAID')
unpaid_bills = all_bills.filter(status='UNPAID')

print(f'Paid bills: {paid_bills.count()}')
print(f'Unpaid bills: {unpaid_bills.count()}')

print('\nBill details:')
for bill in all_bills:
    status = bill.status
    if bill.paid_at and bill.due_date:
        days_late = (bill.paid_at.date() - bill.due_date).days
        late_status = 'LATE' if days_late > 0 else 'ON TIME'
        print(f'  {bill.billing_month}: {status} - Due {bill.due_date} - Paid {bill.paid_at.date()} - {days_late} days ({late_status})')
    else:
        print(f'  {bill.billing_month}: {status} - Due {bill.due_date} - No payment date')

# Check if this tenant should have bills based on their lease
if leases.exists():
    lease = leases.first()
    print(f'\nLease start date: {lease.start_date}')
    print(f'Lease should have bills from: {lease.start_date.replace(day=1)} onwards')
