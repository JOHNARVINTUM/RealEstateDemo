from billing.models import MonthlyBill
from django.utils import timezone
from datetime import datetime

# Check billing data
print('=== BILLING STATUS ANALYSIS ===')
print(f'Total bills: {MonthlyBill.objects.count()}')
print(f'Paid bills: {MonthlyBill.objects.filter(status="PAID").count()}')
print(f'Unpaid bills: {MonthlyBill.objects.filter(status="UNPAID").count()}')

print('\n=== RECENT BILLS (Last 10) ===')
recent_bills = MonthlyBill.objects.all().order_by('-billing_month')[:10]
for bill in recent_bills:
    print(f'{bill.billing_month} - {bill.lease.unit.number} - {bill.status} - Due: {bill.due_date} - Paid: {bill.paid_at}')

print('\n=== BILLS BY MONTH ===')
months = MonthlyBill.objects.dates('billing_month', 'month').order_by('-billing_month')
for month in months[:6]:  # Last 6 months
    bills_this_month = MonthlyBill.objects.filter(billing_month__year=month.year, billing_month__month=month.month)
    paid = bills_this_month.filter(status='PAID').count()
    unpaid = bills_this_month.filter(status='UNPAID').count()
    print(f'{month.strftime("%Y-%m")}: Paid={paid}, Unpaid={unpaid}, Total={bills_this_month.count()}')

print('\n=== BILLS WITH PAID_AT BUT UNPAID STATUS ===')
problem_bills = MonthlyBill.objects.filter(status='UNPAID', paid_at__isnull=False)
print(f'Bills marked UNPAID but have paid_at date: {problem_bills.count()}')
for bill in problem_bills[:5]:
    print(f'{bill.billing_month} - {bill.lease.unit.number} - Status: {bill.status} - Paid at: {bill.paid_at}')

print('\n=== BILLS WITH NO PAID_AT BUT PAID STATUS ===')
problem_bills2 = MonthlyBill.objects.filter(status='PAID', paid_at__isnull=True)
print(f'Bills marked PAID but no paid_at date: {problem_bills2.count()}')
for bill in problem_bills2[:5]:
    print(f'{bill.billing_month} - {bill.lease.unit.number} - Status: {bill.status} - Paid at: {bill.paid_at}')

print('\n=== CURRENT MONTH BILLS ===')
today = timezone.now().date()
current_month = today.replace(day=1)
current_bills = MonthlyBill.objects.filter(billing_month=current_month)
print(f'Current month ({current_month.strftime("%Y-%m")}) bills: {current_bills.count()}')
for bill in current_bills:
    print(f'  {bill.lease.unit.number} - {bill.status} - Due: {bill.due_date} - Paid: {bill.paid_at}')
