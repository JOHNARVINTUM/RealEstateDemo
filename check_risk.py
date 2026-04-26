from rentals.models import TenantRiskClassification

# Check updated risk classifications
risks = TenantRiskClassification.objects.all().order_by('-payment_score')
print('Updated Risk Classifications:')
print('=' * 60)
for risk in risks:
    print(f'{risk.tenant.email}: {risk.risk_level} ({risk.payment_score}/100)')
    print(f'  Late: {risk.late_payment_count}, Unpaid: {risk.unpaid_bill_count}')
    print(f'  Timeliness: {risk.risk_factors.get("payment_timeliness", 0)}/100')
    print()

# Show risk distribution
low_count = TenantRiskClassification.objects.filter(risk_level='LOW').count()
medium_count = TenantRiskClassification.objects.filter(risk_level='MEDIUM').count()
high_count = TenantRiskClassification.objects.filter(risk_level='HIGH').count()

print(f'Risk Distribution:')
print(f'Low Risk: {low_count}')
print(f'Medium Risk: {medium_count}')
print(f'High Risk: {high_count}')
