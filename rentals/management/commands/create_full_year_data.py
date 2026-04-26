from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
from rentals.models import Unit, Lease, TenantProfile, Notification
from billing.models import MonthlyBill
from payments.models import ManualPayment
from maintenance.models import MaintenanceRequest
from announcements.models import Announcement
import random

User = get_user_model()

class Command(BaseCommand):
    help = 'Create comprehensive dummy data set for 1 year period'

    def handle(self, *args, **options):
        self.stdout.write('Creating comprehensive dummy data for 1 year...')
        
        # Clear existing data
        self.clear_existing_data()
        
        # Create admin user
        self.create_admin_user()
        
        # Create comprehensive units
        units = self.create_units()
        
        # Create comprehensive tenants
        tenants = self.create_tenants()
        
        # Create leases with realistic timeline
        leases = self.create_leases(units, tenants)
        
        # Create comprehensive billing data
        self.create_billing_data(leases)
        
        # Create payment records
        self.create_payment_records(tenants)
        
        # Create maintenance requests
        self.create_maintenance_requests(tenants, units)
        
        # Create announcements
        self.create_announcements()
        
        # Create notifications
        self.create_notifications()
        
        self.stdout.write(self.style.SUCCESS('Full year dummy data created successfully!'))
        self.display_summary()

    def clear_existing_data(self):
        """Clear all existing data"""
        self.stdout.write('Clearing existing data...')
        Notification.objects.all().delete()
        MaintenanceRequest.objects.all().delete()
        ManualPayment.objects.all().delete()
        MonthlyBill.objects.all().delete()
        Lease.objects.all().delete()
        TenantProfile.objects.all().delete()
        Unit.objects.all().delete()
        User.objects.filter(role='TENANT').delete()
        self.stdout.write('Existing data cleared')

    def create_admin_user(self):
        """Create admin user"""
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

    def create_units(self):
        """Create comprehensive units"""
        self.stdout.write('Creating units...')
        
        units_data = [
            # Studio units
            {'number': 'A101', 'unit_type': 'STUDIO', 'floor_level': 1, 'monthly_rent': 7500, 'bedrooms': 0, 'bathrooms': 1},
            {'number': 'A102', 'unit_type': 'STUDIO', 'floor_level': 1, 'monthly_rent': 7800, 'bedrooms': 0, 'bathrooms': 1},
            {'number': 'A103', 'unit_type': 'STUDIO', 'floor_level': 1, 'monthly_rent': 8000, 'bedrooms': 0, 'bathrooms': 1},
            {'number': 'A201', 'unit_type': 'STUDIO', 'floor_level': 2, 'monthly_rent': 8200, 'bedrooms': 0, 'bathrooms': 1},
            {'number': 'A202', 'unit_type': 'STUDIO', 'floor_level': 2, 'monthly_rent': 8500, 'bedrooms': 0, 'bathrooms': 1},
            
            # One bedroom units
            {'number': 'B101', 'unit_type': 'ONE_BEDROOM', 'floor_level': 1, 'monthly_rent': 11000, 'bedrooms': 1, 'bathrooms': 1},
            {'number': 'B102', 'unit_type': 'ONE_BEDROOM', 'floor_level': 1, 'monthly_rent': 11500, 'bedrooms': 1, 'bathrooms': 1},
            {'number': 'B103', 'unit_type': 'ONE_BEDROOM', 'floor_level': 1, 'monthly_rent': 12000, 'bedrooms': 1, 'bathrooms': 1},
            {'number': 'B201', 'unit_type': 'ONE_BEDROOM', 'floor_level': 2, 'monthly_rent': 12500, 'bedrooms': 1, 'bathrooms': 1},
            {'number': 'B202', 'unit_type': 'ONE_BEDROOM', 'floor_level': 2, 'monthly_rent': 13000, 'bedrooms': 1, 'bathrooms': 1},
            {'number': 'B301', 'unit_type': 'ONE_BEDROOM', 'floor_level': 3, 'monthly_rent': 13500, 'bedrooms': 1, 'bathrooms': 1},
            {'number': 'B302', 'unit_type': 'ONE_BEDROOM', 'floor_level': 3, 'monthly_rent': 14000, 'bedrooms': 1, 'bathrooms': 1},
            
            # Two bedroom units
            {'number': 'C101', 'unit_type': 'TWO_BEDROOM', 'floor_level': 1, 'monthly_rent': 17000, 'bedrooms': 2, 'bathrooms': 2},
            {'number': 'C102', 'unit_type': 'TWO_BEDROOM', 'floor_level': 1, 'monthly_rent': 17500, 'bedrooms': 2, 'bathrooms': 2},
            {'number': 'C201', 'unit_type': 'TWO_BEDROOM', 'floor_level': 2, 'monthly_rent': 18000, 'bedrooms': 2, 'bathrooms': 2},
            {'number': 'C202', 'unit_type': 'TWO_BEDROOM', 'floor_level': 2, 'monthly_rent': 18500, 'bedrooms': 2, 'bathrooms': 2},
            {'number': 'C301', 'unit_type': 'TWO_BEDROOM', 'floor_level': 3, 'monthly_rent': 19000, 'bedrooms': 2, 'bathrooms': 2},
            {'number': 'C302', 'unit_type': 'TWO_BEDROOM', 'floor_level': 3, 'monthly_rent': 19500, 'bedrooms': 2, 'bathrooms': 2},
            
            # Three bedroom units
            {'number': 'D101', 'unit_type': 'THREE_BEDROOM', 'floor_level': 1, 'monthly_rent': 22000, 'bedrooms': 3, 'bathrooms': 2},
            {'number': 'D201', 'unit_type': 'THREE_BEDROOM', 'floor_level': 2, 'monthly_rent': 23000, 'bedrooms': 3, 'bathrooms': 2},
            {'number': 'D301', 'unit_type': 'THREE_BEDROOM', 'floor_level': 3, 'monthly_rent': 24000, 'bedrooms': 3, 'bathrooms': 2},
        ]
        
        units = []
        for unit_data in units_data:
            unit, created = Unit.objects.get_or_create(
                number=unit_data['number'],
                defaults={
                    'unit_type': unit_data['unit_type'],
                    'floor_level': unit_data['floor_level'],
                    'monthly_rent': unit_data['monthly_rent'],
                    'status': 'AVAILABLE',
                    'is_active': True
                }
            )
            units.append(unit)
            if created:
                self.stdout.write(f'  Created unit {unit.number} - {unit.get_unit_type_display()} (₱{unit.monthly_rent:,})')
        
        return units

    def create_tenants(self):
        """Create comprehensive tenants"""
        self.stdout.write('Creating tenants...')
        
        tenants_data = [
            {'email': 'john.smith@email.com', 'full_name': 'John Smith', 'contact_no': '09123456789'},
            {'email': 'jane.doe@email.com', 'full_name': 'Jane Doe', 'contact_no': '09234567890'},
            {'email': 'bob.johnson@email.com', 'full_name': 'Bob Johnson', 'contact_no': '09345678901'},
            {'email': 'alice.brown@email.com', 'full_name': 'Alice Brown', 'contact_no': '09456789012'},
            {'email': 'charlie.wilson@email.com', 'full_name': 'Charlie Wilson', 'contact_no': '09567890123'},
            {'email': 'diana.miller@email.com', 'full_name': 'Diana Miller', 'contact_no': '09678901234'},
            {'email': 'edward.davis@email.com', 'full_name': 'Edward Davis', 'contact_no': '09789012345'},
            {'email': 'fiona.garcia@email.com', 'full_name': 'Fiona Garcia', 'contact_no': '09890123456'},
            {'email': 'george.martinez@email.com', 'full_name': 'George Martinez', 'contact_no': '09901234567'},
            {'email': 'helen.rodriguez@email.com', 'full_name': 'Helen Rodriguez', 'contact_no': '09012345678'},
            {'email': 'ivan.lee@email.com', 'full_name': 'Ivan Lee', 'contact_no': '09123456789'},
            {'email': 'julia.white@email.com', 'full_name': 'Julia White', 'contact_no': '09234567890'},
            {'email': 'kevin.harris@email.com', 'full_name': 'Kevin Harris', 'contact_no': '09345678901'},
            {'email': 'laura.clark@email.com', 'full_name': 'Laura Clark', 'contact_no': '09456789012'},
            {'email': 'michael.lewis@email.com', 'full_name': 'Michael Lewis', 'contact_no': '09567890123'},
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
                self.stdout.write(f'  Created tenant {tenant_profile.full_name}')
        
        return tenants

    def create_leases(self, units, tenants):
        """Create leases with realistic timeline"""
        self.stdout.write('Creating leases...')
        
        today = timezone.now().date()
        leases = []
        
        # Create leases throughout the year with different start dates
        lease_schedule = [
            # Long-term tenants (started early 2025)
            {'unit_idx': 0, 'tenant_idx': 0, 'start_date': today - timedelta(days=400), 'is_active': True},
            {'unit_idx': 1, 'tenant_idx': 1, 'start_date': today - timedelta(days=380), 'is_active': True},
            {'unit_idx': 2, 'tenant_idx': 2, 'start_date': today - timedelta(days=360), 'is_active': True},
            
            # Mid-year tenants
            {'unit_idx': 3, 'tenant_idx': 3, 'start_date': today - timedelta(days=200), 'is_active': True},
            {'unit_idx': 4, 'tenant_idx': 4, 'start_date': today - timedelta(days=180), 'is_active': True},
            {'unit_idx': 5, 'tenant_idx': 5, 'start_date': today - timedelta(days=160), 'is_active': True},
            {'unit_idx': 6, 'tenant_idx': 6, 'start_date': today - timedelta(days=140), 'is_active': True},
            {'unit_idx': 7, 'tenant_idx': 7, 'start_date': today - timedelta(days=120), 'is_active': True},
            
            # Recent tenants
            {'unit_idx': 8, 'tenant_idx': 8, 'start_date': today - timedelta(days=80), 'is_active': True},
            {'unit_idx': 9, 'tenant_idx': 9, 'start_date': today - timedelta(days=60), 'is_active': True},
            {'unit_idx': 10, 'tenant_idx': 10, 'start_date': today - timedelta(days=40), 'is_active': True},
            
            # Some inactive leases (moved out)
            {'unit_idx': 11, 'tenant_idx': 11, 'start_date': today - timedelta(days=300), 'end_date': today - timedelta(days=30), 'is_active': False},
            {'unit_idx': 12, 'tenant_idx': 12, 'start_date': today - timedelta(days=250), 'end_date': today - timedelta(days=60), 'is_active': False},
        ]
        
        for schedule in lease_schedule:
            unit = units[schedule['unit_idx']]
            tenant = tenants[schedule['tenant_idx']]
            
            lease, created = Lease.objects.get_or_create(
                unit=unit,
                tenant=tenant.user,
                defaults={
                    'start_date': schedule['start_date'],
                    'monthly_rent': unit.monthly_rent,
                    'is_active': schedule['is_active']
                }
            )
            
            if created:
                # Update unit status based on lease activity
                if schedule['is_active']:
                    unit.status = 'OCCUPIED'
                    unit.save()
                
                self.stdout.write(f'  Created lease for {unit.number} - {tenant.full_name} ({unit.get_unit_type_display()})')
                leases.append(lease)
        
        return leases

    def create_billing_data(self, leases):
        """Create comprehensive billing data for the year"""
        self.stdout.write('Creating billing data...')
        
        today = timezone.now().date()
        
        # Create bills for each month of the year
        for i in range(12):
            # Calculate month from current date going back
            if i == 0:
                month_date = today.replace(day=1)
            else:
                month_year = today.year
                month_month = today.month - i
                while month_month <= 0:
                    month_month += 12
                    month_year -= 1
                month_date = datetime(month_year, month_month, 1).date()
            
            # Create bills for all active leases
            for lease in Lease.objects.filter(is_active=True):
                # Determine payment status based on month
                if i < 8:  # First 8 months - mostly paid
                    payment_status = 'PAID' if random.random() > 0.1 else 'UNPAID'
                else:  # Recent months - some unpaid
                    payment_status = 'PAID' if random.random() > 0.3 else 'UNPAID'
                
                bill, created = MonthlyBill.objects.get_or_create(
                    lease=lease,
                    billing_month=month_date,
                    defaults={
                        'total_due': lease.monthly_rent,
                        'due_date': month_date.replace(day=15),
                        'status': payment_status,
                        'paid_at': month_date.replace(day=random.randint(16, 28)) if payment_status == 'PAID' else None
                    }
                )
                
                if created and i == 0:  # Only show for current month
                    self.stdout.write(f'  Created bill for {lease.unit.number} - {month_date.strftime("%Y-%m")} ({payment_status})')

    def create_payment_records(self, tenants):
        """Create payment records"""
        self.stdout.write('Creating payment records...')
        
        payment_data = [
            {'tenant_idx': 0, 'amount': 7500, 'reference_code': 'GCASH001', 'status': 'APPROVED'},
            {'tenant_idx': 1, 'amount': 7800, 'reference_code': 'GCASH002', 'status': 'APPROVED'},
            {'tenant_idx': 2, 'amount': 8000, 'reference_code': 'GCASH003', 'status': 'APPROVED'},
            {'tenant_idx': 3, 'amount': 8200, 'reference_code': 'GCASH004', 'status': 'APPROVED'},
            {'tenant_idx': 4, 'amount': 8500, 'reference_code': 'GCASH005', 'status': 'PENDING'},
            {'tenant_idx': 5, 'amount': 11000, 'reference_code': 'GCASH006', 'status': 'APPROVED'},
            {'tenant_idx': 6, 'amount': 11500, 'reference_code': 'GCASH007', 'status': 'REJECTED'},
            {'tenant_idx': 7, 'amount': 12000, 'reference_code': 'GCASH008', 'status': 'APPROVED'},
        ]
        
        for payment_info in payment_data:
            tenant = tenants[payment_info['tenant_idx']]
            payment, created = ManualPayment.objects.get_or_create(
                reference_code=payment_info['reference_code'],
                defaults={
                    'user': tenant.user,
                    'status': payment_info['status'],
                    'bill_ids': ''
                }
            )
            if created:
                self.stdout.write(f'  Created payment {payment.reference_code} - ₱{payment_info["amount"]:,}')

    def create_maintenance_requests(self, tenants, units):
        """Create maintenance requests"""
        self.stdout.write('Creating maintenance requests...')
        
        request_categories = ['PLUMBING', 'ELECTRICAL', 'STRUCTURAL', 'OTHER']
        request_statuses = ['OPEN', 'IN_PROGRESS', 'RESOLVED', 'CLOSED']
        
        requests_data = [
            {'tenant_idx': 0, 'unit_idx': 0, 'category': 'PLUMBING', 'title': 'Leaking faucet', 'description': 'Kitchen faucet is leaking and needs repair', 'status': 'RESOLVED'},
            {'tenant_idx': 1, 'unit_idx': 1, 'category': 'ELECTRICAL', 'title': 'Light bulb issue', 'description': 'Bedroom light bulb needs replacement', 'status': 'RESOLVED'},
            {'tenant_idx': 2, 'unit_idx': 2, 'category': 'STRUCTURAL', 'title': 'Wall crack', 'description': 'Small crack in living room wall', 'status': 'IN_PROGRESS'},
            {'tenant_idx': 3, 'unit_idx': 3, 'category': 'PLUMBING', 'title': 'Drainage issue', 'description': 'Bathroom sink draining slowly', 'status': 'OPEN'},
            {'tenant_idx': 4, 'unit_idx': 4, 'category': 'ELECTRICAL', 'title': 'Power outlet', 'description': 'Power outlet not working in bedroom', 'status': 'CLOSED'},
        ]
        
        for req_info in requests_data:
            tenant = tenants[req_info['tenant_idx']]
            unit = units[req_info['unit_idx']]
            
            # Find the lease for this tenant and unit
            lease = Lease.objects.filter(tenant=tenant.user, unit=unit).first()
            
            request, created = MaintenanceRequest.objects.get_or_create(
                tenant=tenant.user,
                lease=lease,
                defaults={
                    'category': req_info['category'],
                    'title': req_info['title'],
                    'description': req_info['description'],
                    'status': req_info['status'],
                    'priority': 'MEDIUM',
                    'created_at': timezone.now() - timedelta(days=random.randint(1, 30))
                }
            )
            if created:
                self.stdout.write(f'  Created maintenance request: {req_info["title"]}')

    def create_announcements(self):
        """Create announcements"""
        self.stdout.write('Creating announcements...')
        
        announcements_data = [
            {'title': 'Welcome to RealEstate360+', 'body': 'We are excited to have you as part of our community!', 'is_active': True},
            {'title': 'Rent Payment Reminder', 'body': 'Please remember to pay your rent on time to avoid late fees.', 'is_active': True},
            {'title': 'Maintenance Schedule', 'body': 'Elevator maintenance scheduled for next week.', 'is_active': True},
            {'title': 'Community Event', 'body': 'Join us for our monthly community meeting this Friday.', 'is_active': False},
        ]
        
        for ann_data in announcements_data:
            announcement, created = Announcement.objects.get_or_create(
                title=ann_data['title'],
                defaults={
                    'body': ann_data['body'],
                    'is_active': ann_data['is_active'],
                    'created_at': timezone.now() - timedelta(days=random.randint(1, 60))
                }
            )
            if created:
                self.stdout.write(f'  Created announcement: {ann_data["title"]}')

    def create_notifications(self):
        """Create notifications"""
        self.stdout.write('Creating notifications...')
        
        # Create some sample notifications
        notifications_data = [
            {'title': 'New Lease Created', 'message': 'Lease created for John Smith in Unit A101', 'type': 'LEASE'},
            {'title': 'Payment Received', 'message': 'Payment of ₱7,500 received from Jane Doe', 'type': 'PAYMENT'},
            {'title': 'Unit Available', 'message': 'Unit B102 is now available for rent', 'type': 'UNIT'},
            {'title': 'Maintenance Request', 'message': 'New maintenance request from Bob Johnson', 'type': 'MAINTENANCE'},
        ]
        
        for notif_data in notifications_data:
            notification = Notification.create_notification(
                title=notif_data['title'],
                message=notif_data['message'],
                notification_type=notif_data['type']
            )
            self.stdout.write(f'  Created notification: {notif_data["title"]}')

    def display_summary(self):
        """Display summary of created data"""
        self.stdout.write('\n' + '='*50)
        self.stdout.write('DATA CREATION SUMMARY')
        self.stdout.write('='*50)
        self.stdout.write(f'Users: {User.objects.count()}')
        self.stdout.write(f'Tenants: {TenantProfile.objects.count()}')
        self.stdout.write(f'Units: {Unit.objects.count()}')
        self.stdout.write(f'  - Studio: {Unit.objects.filter(unit_type="STUDIO").count()}')
        self.stdout.write(f'  - One Bedroom: {Unit.objects.filter(unit_type="ONE_BEDROOM").count()}')
        self.stdout.write(f'  - Two Bedroom: {Unit.objects.filter(unit_type="TWO_BEDROOM").count()}')
        self.stdout.write(f'  - Three Bedroom: {Unit.objects.filter(unit_type="THREE_BEDROOM").count()}')
        self.stdout.write(f'Leases: {Lease.objects.count()}')
        self.stdout.write(f'  - Active: {Lease.objects.filter(is_active=True).count()}')
        self.stdout.write(f'  - Inactive: {Lease.objects.filter(is_active=False).count()}')
        self.stdout.write(f'Monthly Bills: {MonthlyBill.objects.count()}')
        self.stdout.write(f'  - Paid: {MonthlyBill.objects.filter(status="PAID").count()}')
        self.stdout.write(f'  - Unpaid: {MonthlyBill.objects.filter(status="UNPAID").count()}')
        self.stdout.write(f'Payments: {ManualPayment.objects.count()}')
        self.stdout.write(f'Maintenance Requests: {MaintenanceRequest.objects.count()}')
        self.stdout.write(f'Announcements: {Announcement.objects.count()}')
        self.stdout.write(f'Notifications: {Notification.objects.count()}')
        self.stdout.write('\nLogin Credentials:')
        self.stdout.write('  Admin: admin / admin123')
        self.stdout.write('  Tenants: [email] / tenant123')
        self.stdout.write('='*50)
