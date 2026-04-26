from rentals.models import Lease, TenantRiskClassification
from billing.models import MonthlyBill

print('Checking which tenants have active leases and bills:')
print('=' * 60)

# Get all tenants with risk classifications
risks = TenantRiskClassification.objects.all()

for risk in risks:
    tenant_email = risk.tenant.email
    
    # Check active leases
    active_leases = Lease.objects.filter(tenant=risk.tenant, is_active=True)
    
    # Check bills
    all_bills = MonthlyBill.objects.filter(lease__tenant=risk.tenant)
    paid_bills = all_bills.filter(status='PAID')
    unpaid_bills = all_bills.filter(status='UNPAID')
    
    print(f'{tenant_email}:')
    print(f'  Active leases: {active_leases.count()}')
    print(f'  Total bills: {all_bills.count()}')
    print(f'  Paid bills: {paid_bills.count()}')
    print(f'  Unpaid bills: {unpaid_bills.count()}')
    print(f'  Risk level: {risk.risk_level} ({risk.payment_score}/100)')
    
    if active_leases.exists():
        lease = active_leases.first()
        print(f'  Unit: {lease.unit.number}')
    
    print()

# Summary
tenants_with_leases = TenantRiskClassification.objects.filter(tenant__leases__is_active=True).distinct().count()
print(f'Summary:')
print(f'Tenants with active leases: {tenants_with_leases}')
print(f'Total tenants in risk system: {TenantRiskClassification.objects.count()}')
