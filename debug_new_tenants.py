from rentals.models import TenantRiskClassification, Lease
from billing.models import MonthlyBill
from datetime import datetime

print('Investigating New Tenant Classifications:')
print('=' * 60)

# Check each tenant marked as new
new_tenants = TenantRiskClassification.objects.filter(is_new_tenant=True)

for risk in new_tenants:
    tenant_email = risk.tenant.email
    print(f'\n{tenant_email}:')
    print(f'  Risk Level: {risk.risk_level} ({risk.payment_score}/100)')
    print(f'  Late Payments: {risk.late_payment_count}')
    print(f'  Unpaid Bills: {risk.unpaid_bill_count}')
    
    # Check lease details
    lease = Lease.objects.filter(tenant=risk.tenant, is_active=True).first()
    if lease:
        months_since_start = (datetime.now().year - lease.start_date.year) * 12 + (datetime.now().month - lease.start_date.month)
        print(f'  Lease Start: {lease.start_date}')
        print(f'  Months Since Start: {months_since_start}')
        print(f'  Unit: {lease.unit.number}')
    else:
        print('  No active lease found')
    
    # Check payment history
    all_bills = MonthlyBill.objects.filter(lease__tenant=risk.tenant)
    paid_bills = all_bills.filter(status='PAID')
    
    print(f'  Total Bills: {all_bills.count()}')
    print(f'  Paid Bills: {paid_bills.count()}')
    
    if paid_bills.count() > 0:
        first_payment = paid_bills.order_by('paid_at').first()
        last_payment = paid_bills.order_by('-paid_at').first()
        print(f'  First Payment: {first_payment.paid_at.date() if first_payment else "None"}')
        print(f'  Last Payment: {last_payment.paid_at.date() if last_payment else "None"}')
        
        # Show payment pattern
        print('  Payment History:')
        for bill in paid_bills.order_by('billing_month')[:6]:  # Show first 6 payments
            if bill.paid_at and bill.due_date:
                days_late = (bill.paid_at.date() - bill.due_date).days
                status = 'ON TIME' if days_late <= 0 else f'{days_late} DAYS LATE'
                print(f'    {bill.billing_month}: {status}')
