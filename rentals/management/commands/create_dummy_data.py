from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from rentals.models import Unit, Lease, TenantProfile
from billing.models import MonthlyBill
from payments.models import ManualPayment
import random

User = get_user_model()

class Command(BaseCommand):
    help = 'Create dummy data for testing rental income chart'

    def handle(self, *args, **options):
        self.stdout.write('Creating dummy data for rental income chart...')
        
        # Create admin user if not exists
        admin_user, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@example.com',
                'role': 'ADMIN',
                'is_staff': True,
                'is_superuser': True
            }
        )
        if created:
            admin_user.set_password('admin123')
            admin_user.save()
            self.stdout.write('Created admin user')
        
        # Create sample units
        units_data = [
            {'number': 'A101', 'unit_type': 'STUDIO', 'floor_level': 1, 'monthly_rent': 8000},
            {'number': 'A102', 'unit_type': 'STUDIO', 'floor_level': 1, 'monthly_rent': 8500},
            {'number': 'B201', 'unit_type': 'ONE_BEDROOM', 'floor_level': 2, 'monthly_rent': 12000},
            {'number': 'B202', 'unit_type': 'ONE_BEDROOM', 'floor_level': 2, 'monthly_rent': 12500},
            {'number': 'C301', 'unit_type': 'TWO_BEDROOM', 'floor_level': 3, 'monthly_rent': 18000},
            {'number': 'C302', 'unit_type': 'TWO_BEDROOM', 'floor_level': 3, 'monthly_rent': 19000},
        ]
        
        units = []
        for unit_data in units_data:
            unit, created = Unit.objects.get_or_create(
                number=unit_data['number'],
                defaults={
                    'unit_type': unit_data['unit_type'],
                    'floor_level': unit_data['floor_level'],
                    'status': 'AVAILABLE',
                    'is_active': True
                }
            )
            units.append(unit)
            if created:
                self.stdout.write(f'Created unit {unit.number}')
        
        # Create sample tenants
        tenants_data = [
            {'email': 'tenant1@example.com', 'full_name': 'John Smith', 'contact_no': '09123456789'},
            {'email': 'tenant2@example.com', 'full_name': 'Jane Doe', 'contact_no': '09234567890'},
            {'email': 'tenant3@example.com', 'full_name': 'Bob Johnson', 'contact_no': '09345678901'},
            {'email': 'tenant4@example.com', 'full_name': 'Alice Brown', 'contact_no': '09456789012'},
        ]
        
        tenants = []
        for tenant_data in tenants_data:
            user, created = User.objects.get_or_create(
                email=tenant_data['email'],
                defaults={
                    'username': tenant_data['email'].split('@')[0],
                    'role': 'TENANT'
                }
            )
            if created:
                user.set_password('tenant123')
                user.save()
            
            tenant_profile, created = TenantProfile.objects.get_or_create(
                user=user,
                defaults={
                    'full_name': tenant_data['full_name'],
                    'contact_no': tenant_data['contact_no']
                }
            )
            tenants.append(tenant_profile)
            if created:
                self.stdout.write(f'Created tenant {tenant_profile.full_name}')
        
        # Create sample leases (make some active, some inactive)
        today = timezone.now().date()
        lease_data = [
            {'unit': units[0], 'tenant': tenants[0].user, 'start_date': today - timedelta(days=365), 'monthly_rent': 8000, 'is_active': True},
            {'unit': units[1], 'tenant': tenants[1].user, 'start_date': today - timedelta(days=300), 'monthly_rent': 8500, 'is_active': True},
            {'unit': units[2], 'tenant': tenants[2].user, 'start_date': today - timedelta(days=200), 'monthly_rent': 12000, 'is_active': True},
            {'unit': units[3], 'tenant': tenants[3].user, 'start_date': today - timedelta(days=100), 'monthly_rent': 12500, 'is_active': False},  # Inactive lease
        ]
        
        for lease_info in lease_data:
            lease, created = Lease.objects.get_or_create(
                unit=lease_info['unit'],
                tenant=lease_info['tenant'],
                defaults={
                    'start_date': lease_info['start_date'],
                    'monthly_rent': lease_info['monthly_rent'],
                    'is_active': lease_info['is_active']
                }
            )
            if created:
                # Update unit status based on lease activity
                if lease_info['is_active']:
                    lease_info['unit'].status = 'OCCUPIED'
                    lease_info['unit'].save()
                self.stdout.write(f'Created lease for {lease.unit.number}')
        
        # Create monthly bills for the past 12 months with varying payment status
        for i in range(12):
            bill_date = today - timedelta(days=i*30)
            
            for lease in Lease.objects.filter(is_active=True):
                # Create bill
                bill, created = MonthlyBill.objects.get_or_create(
                    lease=lease,
                    billing_month=bill_date.replace(day=1),
                    defaults={
                        'total_due': lease.monthly_rent,
                        'due_date': bill_date.replace(day=15),
                        'status': 'PAID' if i < 8 else 'UNPAID',  # Last 4 months unpaid
                        'paid_at': bill_date.replace(day=20) if i < 8 else None
                    }
                )
                if created:
                    self.stdout.write(f'Created bill for {lease.unit.number} - {bill_date.strftime("%Y-%m")}')
        
        # Create some manual payments
        payment_data = [
            {'user': tenants[0].user, 'reference_code': 'GCASH001', 'status': 'APPROVED'},
            {'user': tenants[1].user, 'reference_code': 'GCASH002', 'status': 'APPROVED'},
            {'user': tenants[2].user, 'reference_code': 'GCASH003', 'status': 'PENDING'},
        ]
        
        for payment_info in payment_data:
            payment, created = ManualPayment.objects.get_or_create(
                reference_code=payment_info['reference_code'],
                defaults={
                    'user': payment_info['user'],
                    'status': payment_info['status'],
                    'bill_ids': ''  # Empty string for now
                }
            )
            if created:
                self.stdout.write(f'Created payment {payment.reference_code}')
        
        self.stdout.write(self.style.SUCCESS('Dummy data created successfully!'))
        self.stdout.write('Login credentials:')
        self.stdout.write('  Admin: admin / admin123')
        self.stdout.write('  Tenants: tenant1@example.com / tenant123, etc.')
