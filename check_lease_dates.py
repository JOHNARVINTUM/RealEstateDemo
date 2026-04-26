from rentals.models import Lease
from billing.models import MonthlyBill
from datetime import datetime

print('Checking Lease vs Payment Date Consistency:')
print('=' * 60)

# Check all active leases
leases = Lease.objects.filter(is_active=True)
print(f'Active leases: {leases.count()}')

for lease in leases:
    print(f'\n{lease.tenant.email} - Unit {lease.unit.number}:')
    print(f'  Lease Start: {lease.start_date}')
    print(f'  Lease End: {lease.end_date}')
    
    # Check bills for this tenant
    bills = MonthlyBill.objects.filter(lease__tenant=lease.tenant)
    earliest_bill = bills.order_by('billing_month').first()
    latest_bill = bills.order_by('billing_month').last()
    
    print(f'  Earliest Bill: {earliest_bill.billing_month if earliest_bill else "None"}')
    print(f'  Latest Bill: {latest_bill.billing_month if latest_bill else "None"}')
    
    # Check for inconsistency
    if earliest_bill and lease.start_date:
        if earliest_bill.billing_month < lease.start_date.replace(day=1):
            print(f'  ⚠️  INCONSISTENCY: Bills exist before lease start!')
            print(f'     First bill: {earliest_bill.billing_month}')
            print(f'     Lease start: {lease.start_date}')
        else:
            print(f'  ✅ Consistent: Bills start after lease start')
