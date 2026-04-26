from billing.models import MonthlyBill
from rentals.models import TenantRiskClassification
from rentals.services import TenantRiskService

# Check diana.miller - highest score but still medium risk
tenant_email = 'diana.miller@email.com'
print(f'Detailed analysis for {tenant_email}:')
print('=' * 60)

risk = TenantRiskClassification.objects.get(tenant__email=tenant_email)
print(f'Current risk: {risk.risk_level} ({risk.payment_score}/100)')
print(f'Late payments: {risk.late_payment_count}')
print(f'Unpaid bills: {risk.unpaid_bill_count}')

# Check payment details
bills = MonthlyBill.objects.filter(lease__tenant__email=tenant_email)
paid_bills = bills.filter(status='PAID')

print(f'\nPayment Analysis:')
print(f'Total bills: {bills.count()}')
print(f'Paid bills: {paid_bills.count()}')

# Calculate on-time payments
on_time_count = 0
late_count = 0
for bill in paid_bills:
    if bill.paid_at and bill.due_date:
        days_late = (bill.paid_at.date() - bill.due_date).days
        if days_late <= 0:
            on_time_count += 1
        else:
            late_count += 1
        print(f'  {bill.billing_month}: {days_late} days late')

on_time_percentage = (on_time_count / paid_bills.count()) * 100
print(f'\nOn-time percentage: {on_time_percentage:.1f}% ({on_time_count}/{paid_bills.count()})')

# Calculate individual components
timeliness = TenantRiskService._calculate_payment_timeliness(risk.tenant)
consistency = TenantRiskService._calculate_payment_consistency(risk.tenant)
current_status = TenantRiskService._calculate_current_payment_status(risk.tenant)
payment_method = TenantRiskService._calculate_payment_method_reliability(risk.tenant)

print(f'\nScoring Components:')
print(f'Payment Timeliness (40%): {timeliness}')
print(f'Payment Consistency (30%): {consistency}')
print(f'Current Payment Status (20%): {current_status}')
print(f'Payment Method Reliability (10%): {payment_method}')

# Calculate weighted score
total_score = (
    timeliness * 0.4 +
    consistency * 0.3 +
    current_status * 0.2 +
    payment_method * 0.1
)
print(f'Calculated total score: {total_score}')

# Check what score would be needed for Low Risk
low_risk_threshold = 80
print(f'Score needed for Low Risk: {low_risk_threshold}')
print(f'Gap to Low Risk: {low_risk_threshold - total_score}')
