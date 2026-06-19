"""
Management command to seed realistic thesis demo data for apartment rental system.
Creates 58 units (39 occupied, 19 vacant) with 36 months of history for ML forecasting.
"""

import random
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Tuple

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.contrib.auth import get_user_model

from rentals.models import Unit, TenantProfile, Lease
from billing.models import MonthlyBill
from payments.models import ManualPayment
from water.models import WaterRate, WaterReading, WaterComputationLog
from maintenance.models import MaintenanceRequest

User = get_user_model()

logger = logging.getLogger(__name__)

# Fixed tenant/unit mapping from user
FIXED_TENANT_UNITS = [
    ("201", "Rafael Carlo Gutierrez"),
    ("202", "Margarita Jolipas"),
    ("203", "Juastine Borja"),
    ("204", "Arlene Bueno"),
    ("205", "Alice Prado"),
    ("206", "Symon F. Dizon"),
    ("207", "Maria Concepcion Bitagon"),
    ("208", "Erijane Abella"),
    ("209", "Anthony Hermitanio"),
    ("210", "Anna Liza R. Tiongco"),
    ("301", "Clifford Bravo"),
    ("302", "Emmanuel R. Robles"),
    ("303", "Ma. Lucia delos Santo"),
    ("304", "Harissa Sacbayana"),
    ("305", "Candy Talens"),
    ("306", "Mary Ann Perez"),
    ("307", "Rea Solo"),
    ("308", "Mark Jason Tuazon"),
    ("309", "Ranelfo R. Velasquez"),
    ("310", "Ivan de Monteverde"),
    ("401", "Helen Santor"),
    ("402", "JB Christian M. Cano"),
    ("403", "Edgardo Santor"),
    ("404", "Nestor de Dios II"),
    ("405", "Donnabel Balanquit"),
    ("406", "Sophia Kimura"),
    ("407", "Abegail dela Cruz"),
    ("408", "Prince Zildjan Bartolome"),
    ("409", "Jacob Sindayen"),
    ("410", "Irish Jane Bensurto"),
    ("501", "Glee Zel Italia"),
    ("502", "Ralph Ramirez"),
    ("503", "Maria Evelyn Bismar"),
    ("504", "Ralph Rae Aquilar"),
    ("505", "Keithlyn Ann Gutierrez"),
    ("506", "Jason San Juan"),
    ("507", "Daniel C. Tolentino"),
    ("508", "Solomon Inomiesa"),
    ("509", "Jana Grace Vergara"),
]

# Additional vacant units to reach 58 total
VACANT_UNITS = [
    "101", "102", "103", "104", "105", "106", "107", "108", "109", "110",
    "510", "601", "602", "603", "604", "605", "606", "607", "608"
]

# Unit type distribution
UNIT_TYPES = {
    "Studio": 20,
    "1BR": 25,
    "2BR": 13
}

# Rent ranges
RENT_RANGES = {
    "Studio": (8000, 12000),
    "1BR": (12000, 18000),
    "2BR": (18000, 25000)
}

# Unit sizes
UNIT_SIZES = {
    "Studio": (22, 30),
    "1BR": (31, 45),
    "2BR": (46, 65)
}

# Maintenance categories and ML labels
MAINTENANCE_CATEGORIES = ["PLUMBING", "ELECTRICAL", "STRUCTURAL", "OTHER"]
ML_MAINTENANCE_LABELS = [
    "PLUMBING", "ELECTRICAL", "HVAC_AC", "NOISE_COMPLAINT", 
    "WATER_ISSUE", "INTERNET_ISSUE", "PEST_CONTROL", "STRUCTURAL_DAMAGE"
]

# Maintenance description templates
MAINTENANCE_TEMPLATES = {
    "PLUMBING": [
        "Bathroom sink clogged in Unit {unit}",
        "Water leaking under kitchen sink in Unit {unit}",
        "Low water pressure in shower of Unit {unit}",
        "Toilet won't stop running in Unit {unit}",
        "Faucet dripping in Unit {unit} bathroom",
    ],
    "ELECTRICAL": [
        "Bedroom outlet sparks when plugging in charger in Unit {unit}",
        "Light fixture flickering in Unit {unit} living room",
        "Circuit breaker keeps tripping in Unit {unit}",
        "Power outlet not working in Unit {unit}",
        "Bathroom light burned out in Unit {unit}",
    ],
    "STRUCTURAL": [
        "Crack near window in Unit {unit} after heavy rain",
        "Door frame damaged in Unit {unit}",
        "Wall crack appearing in Unit {unit} bedroom",
        "Ceiling water stain in Unit {unit}",
        "Floor tiles loose in Unit {unit} kitchen",
    ],
    "OTHER": [
        "Aircon leaking in Unit {unit} bedroom",
        "Internet connection unstable in Unit {unit}",
        "Neighbors too noisy during midnight in Unit {unit}",
        "Cockroaches seen near kitchen cabinet in Unit {unit}",
        "Bad smell in hallway near Unit {unit}",
    ]
}


class Command(BaseCommand):
    help = "Seed realistic thesis demo data for ML forecasting"

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Required to delete existing demo data before generation'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without making changes'
        )
        parser.add_argument(
            '--months',
            type=int,
            default=36,
            help='Number of months of history to generate (default: 36)'
        )
        parser.add_argument(
            '--seed',
            type=int,
            default=360,
            help='Random seed for reproducible output (default: 360)'
        )
        parser.add_argument(
            '--units-only',
            action='store_true',
            help='Only create units and tenants, skip billing/payments/maintenance'
        )
        parser.add_argument(
            '--billing-only',
            action='store_true',
            help='Only generate billing data (requires existing units/leases)'
        )
        parser.add_argument(
            '--payments-only',
            action='store_true',
            help='Only generate payment data (requires existing bills)'
        )
        parser.add_argument(
            '--maintenance-only',
            action='store_true',
            help='Only generate maintenance data (requires existing units/leases)'
        )

    def handle(self, *args, **options):
        self.options = options
        self.dry_run = options['dry_run']
        self.reset = options['reset']
        self.months = options['months']
        self.seed = options['seed']
        
        # Set random seed for reproducible output
        random.seed(self.seed)
        
        self.stdout.write("=== Thesis Data Seeder ===")
        self.stdout.write(f"Dry run: {self.dry_run}")
        self.stdout.write(f"Reset mode: {self.reset}")
        self.stdout.write(f"History months: {self.months}")
        self.stdout.write(f"Random seed: {self.seed}")
        
        if self.dry_run:
            self.stdout.write("\nDRY RUN MODE - No database changes will be made")
        
        try:
            with transaction.atomic():
                if self.reset:
                    self.reset_demo_data()
                
                self.create_units_and_tenants()
                
                if not self.options['units_only']:
                    self.create_water_rates()
                    self.create_water_readings()
                    self.create_monthly_bills()
                    self.create_payment_history()
                    self.create_maintenance_requests()
                
                self.validate_dataset()
                
                if self.dry_run:
                    self.stdout.write("\nDRY RUN COMPLETED - No changes made to database")
                    raise CommandError("Dry run completed successfully")
                else:
                    self.stdout.write(self.style.SUCCESS("\nDataset seeding completed successfully"))
        
        except CommandError as e:
            if "Dry run completed successfully" in str(e):
                # This is expected for dry run
                pass
            else:
                raise
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error during seeding: {e}"))
            raise

    def reset_demo_data(self):
        """Safely delete demo data while preserving admin users"""
        if self.dry_run:
            self.stdout.write("\n[DRY RUN] Would reset demo data (preserving admin users)")
            return
        
        self.stdout.write("\nResetting demo data...")
        
        # Count admin users before deletion
        admin_count = User.objects.filter(role='ADMIN').count()
        self.stdout.write(f"Preserving {admin_count} admin user(s)")
        
        # Delete in dependency order
        models_to_delete = [
            (WaterComputationLog, "Water computation logs"),
            (MonthlyBill, "Monthly bills"),
            (WaterReading, "Water readings"),
            (ManualPayment, "Manual payments"),
            (MaintenanceRequest, "Maintenance requests"),
            (Lease, "Leases"),
            (TenantProfile, "Tenant profiles"),
            (Unit, "Units"),
        ]
        
        for model, description in models_to_delete:
            count = model.objects.count()
            if count > 0:
                model.objects.all().delete()
                self.stdout.write(f"  Deleted {count} {description}")
        
        # Delete only tenant users (preserve admins)
        tenant_users = User.objects.filter(role='TENANT')
        tenant_count = tenant_users.count()
        if tenant_count > 0:
            tenant_users.delete()
            self.stdout.write(f"  Deleted {tenant_count} tenant users")
        
        self.stdout.write("Demo data reset completed")

    def create_units_and_tenants(self):
        """Create 58 units with 39 occupied and 19 vacant"""
        self.stdout.write("\nCreating units and tenants...")
        
        # Prepare unit types distribution
        unit_type_list = []
        for unit_type, count in UNIT_TYPES.items():
            unit_type_list.extend([unit_type] * count)
        random.shuffle(unit_type_list)
        
        created_units = []
        created_tenants = []
        
        # Create occupied units with fixed tenant names
        for i, (unit_number, tenant_name) in enumerate(FIXED_TENANT_UNITS):
            unit_type = unit_type_list[i]
            rent_range = RENT_RANGES[unit_type]
            size_range = UNIT_SIZES[unit_type]
            
            unit_data = {
                'number': unit_number,
                'unit_type': unit_type,
                'floor_level': int(unit_number[0]),
                'size_sqm': Decimal(str(random.randint(size_range[0], size_range[1]))),
                'monthly_rent': Decimal(str(random.randint(rent_range[0], rent_range[1]))),
                'status': 'OCCUPIED',
                'is_active': True,
            }
            
            if self.dry_run:
                self.stdout.write(f"  [DRY RUN] Would create occupied unit: {unit_number} ({unit_type}) - ₱{unit_data['monthly_rent']}")
            else:
                unit = Unit.objects.create(**unit_data)
                created_units.append(unit)
            
            # Create tenant
            first_name, last_name = tenant_name.rsplit(' ', 1) if ' ' in tenant_name else (tenant_name, '')
            email = f"{first_name.lower().replace(' ', '.')}.{last_name.lower().replace(' ', '')}@gmail.com"
            
            # Ensure unique email
            counter = 1
            base_email = email
            while User.objects.filter(email=email).exists():
                email = f"{base_email}.{counter}"
                counter += 1
            
            tenant_data = {
                'email': email,
                'username': f"{first_name[0].lower()}{last_name.lower()}",
                'role': 'TENANT',
            }
            
            if self.dry_run:
                self.stdout.write(f"  [DRY RUN] Would create tenant: {tenant_name} ({email})")
            else:
                user = User.objects.create_user(
                    email=tenant_data['email'],
                    username=tenant_data['username'],
                    password='demo123',  # Fixed password for demo
                    role=tenant_data['role']
                )
                
                tenant_profile = TenantProfile.objects.create(
                    user=user,
                    first_name=first_name,
                    last_name=last_name,
                    contact_no=f"09{random.randint(10000000, 99999999)}"
                )
                created_tenants.append((user, unit))
        
        # Create vacant units
        for i, unit_number in enumerate(VACANT_UNITS):
            unit_type = unit_type_list[i + len(FIXED_TENANT_UNITS)]
            rent_range = RENT_RANGES[unit_type]
            size_range = UNIT_SIZES[unit_type]
            
            unit_data = {
                'number': unit_number,
                'unit_type': unit_type,
                'floor_level': int(unit_number[0]),
                'size_sqm': Decimal(str(random.randint(size_range[0], size_range[1]))),
                'monthly_rent': Decimal(str(random.randint(rent_range[0], rent_range[1]))),
                'status': 'AVAILABLE',
                'is_active': True,
            }
            
            if self.dry_run:
                self.stdout.write(f"  [DRY RUN] Would create vacant unit: {unit_number} ({unit_type}) - ₱{unit_data['monthly_rent']}")
            else:
                unit = Unit.objects.create(**unit_data)
                created_units.append(unit)
        
        # Create leases for occupied units
        if not self.dry_run:
            start_date = date(2023, 6, 1)  # Start from June 2023
            due_days = [5, 10, 15]
            
            for user, unit in created_tenants:
                Lease.objects.create(
                    tenant=user,
                    unit=unit,
                    monthly_rent=unit.monthly_rent,
                    due_day=random.choice(due_days),
                    start_date=start_date,
                    security_deposit=unit.monthly_rent,
                    advance_months=random.choice([1, 2]),
                    is_active=True
                )
        
        self.stdout.write(f"Created {len(FIXED_TENANT_UNITS)} occupied units and {len(VACANT_UNITS)} vacant units")

    def create_water_rates(self):
        """Create water rate for billing"""
        self.stdout.write("\nCreating water rates...")
        
        rate_data = {
            'rate_per_cu_m': Decimal('45.00'),
            'effective_date': date.today() - timedelta(days=40 * 30),  # Before history starts
            'is_active': True,
            'notes': 'Thesis demo water rate'
        }
        
        if self.dry_run:
            self.stdout.write(f"  [DRY RUN] Would create water rate: ₱45.00/m³")
        else:
            WaterRate.objects.create(**rate_data)
            self.stdout.write("  Created water rate: ₱45.00/m³")

    def create_water_readings(self):
        """Generate water readings for occupied units"""
        self.stdout.write("\nCreating water readings...")
        
        if self.dry_run:
            self.stdout.write("  [DRY RUN] Would generate water readings for all occupied units")
            return
        
        leases = Lease.objects.filter(is_active=True).select_related('unit', 'tenant')
        water_rate = WaterRate.objects.filter(is_active=True).latest('effective_date')
        rate = water_rate.rate_per_cu_m
        
        for lease in leases:
            current_reading = Decimal('0')
            
            for month_offset in range(self.months):
                # Proper monthly increment: add months, not 30-day chunks
                year = 2023 + (month_offset // 12)
                month = 6 + (month_offset % 12)
                if month > 12:
                    year += 1
                    month -= 12
                billing_month = date(year, month, 1)
                
                # Generate realistic consumption
                consumption = self.generate_water_consumption()
                new_reading = current_reading + consumption
                
                # Create water reading
                WaterReading.objects.create(
                    lease=lease,
                    reading_month=billing_month,
                    previous_reading=current_reading,
                    current_reading=new_reading,
                    consumption=consumption,
                    rate_used=rate,
                    computed_amount=(consumption * rate).quantize(Decimal('0.01')),
                    is_first_reading=(month_offset == 0),
                    read_by=User.objects.filter(role='ADMIN').first()
                )
                
                current_reading = new_reading
        
        self.stdout.write(f"  Created water readings for {leases.count()} leases × {self.months} months (excluding Jan-Feb 2026)")

    def generate_water_consumption(self) -> Decimal:
        """Generate realistic water consumption under 100 m³"""
        # Normal distribution around 45-55 m³
        consumption = random.gauss(50, 12)
        consumption = max(30, min(85, consumption))  # Cap between 30-85 m³
        return Decimal(str(round(consumption, 2)))

    def create_monthly_bills(self):
        """Generate monthly bills from water readings"""
        self.stdout.write("\nCreating monthly bills...")
        
        if self.dry_run:
            self.stdout.write("  [DRY RUN] Would generate monthly bills from water readings")
            return
        
        leases = Lease.objects.filter(is_active=True).select_related('unit')
        
        for lease in leases:
            for month_offset in range(self.months):
                # Proper monthly increment: add months, not 30-day chunks
                year = 2023 + (month_offset // 12)
                month = 6 + (month_offset % 12)
                if month > 12:
                    year += 1
                    month -= 12
                billing_month = date(year, month, 1)
                
                # Get water reading for this month
                water_reading = WaterReading.objects.get(
                    lease=lease,
                    reading_month=billing_month
                )
                
                # Calculate due date
                due_day = min(lease.due_day, 28)  # Safe for all months
                due_date = date(billing_month.year, billing_month.month, due_day)
                
                # Calculate interest (3% per week late based on payment date vs due date)
                interest = Decimal('0')
                # Interest will be calculated during payment generation
                
                # Create monthly bill
                MonthlyBill.objects.create(
                    lease=lease,
                    billing_month=billing_month,
                    due_date=due_date,
                    base_rent=lease.monthly_rent,
                    water_amount=water_reading.computed_amount,
                    interest=interest,
                    total_due=lease.monthly_rent + water_reading.computed_amount + interest,
                    status='UNPAID',  # Will be updated by payment generation
                    water_computed_from_system=True,
                    source_water_reading=water_reading
                )
        
        self.stdout.write(f"  Created monthly bills for {leases.count()} leases × {self.months} months")

    def create_payment_history(self):
        """Generate realistic payment history"""
        self.stdout.write("\nCreating payment history...")
        
        if self.dry_run:
            self.stdout.write("  [DRY RUN] Would generate payment history with realistic behavior")
            return
        
        bills = MonthlyBill.objects.select_related('lease', 'lease__tenant').order_by('billing_month')
        
        for bill in bills:
            # Determine payment behavior based on realistic distribution
            rand = random.random()
            
            if rand < 0.76:  # 76% pay on time
                days_delay = random.randint(0, 0)
            elif rand < 0.93:  # 17% pay slightly late (1-7 days)
                days_delay = random.randint(1, 7)
            elif rand < 0.98:  # 5% pay late (2-4 weeks)
                days_delay = random.randint(8, 28)
            else:  # 2% seriously delayed
                days_delay = random.randint(29, 60)
            
            # Calculate payment date based on billing month
            payment_date = bill.due_date + timedelta(days=days_delay)
            
            # Calculate interest if payment is late
            interest = Decimal('0')
            if days_delay > 0:
                weeks_late = days_delay // 7 + 1
                interest = (bill.base_rent * Decimal('0.03') * weeks_late).quantize(Decimal('0.01'))
            
            # Most recent months have more unpaid bills
            months_ago = (date(2026, 5, 1) - bill.billing_month).days // 30
            if months_ago < 3 and random.random() < 0.3:  # 30% of recent bills unpaid
                continue  # Skip payment creation for unpaid bills
            
            payment_method = random.choice(['GCASH', 'CASH'])
            
            payment = ManualPayment.objects.create(
                user=bill.lease.tenant,
                reference_code=f"REF-{payment_date.strftime('%Y%m%d')}-{bill.id}",
                bill_ids=str(bill.id),
                payment_type='full',
                payment_method=payment_method,
                amount=bill.base_rent + bill.water_amount + interest,
                status='APPROVED',
                created_at=payment_date
            )
            
            # Update bill status
            bill.status = 'PAID'
            bill.paid_at = payment_date
            bill.payment_reference = payment.reference_code
            bill.rent_paid = bill.base_rent
            bill.water_paid = bill.water_amount
            bill.interest = interest
            bill.total_due = bill.base_rent + bill.water_amount + interest
            bill.save()
        
        self.stdout.write(f"  Created payment history for {bills.count()} bills")

    def create_maintenance_requests(self):
        """Generate maintenance requests with NLP-ready descriptions"""
        self.stdout.write("\nCreating maintenance requests...")
        
        if self.dry_run:
            self.stdout.write("  [DRY RUN] Would generate maintenance requests with NLP descriptions")
            return
        
        leases = Lease.objects.filter(is_active=True).select_related('unit')
        request_count = random.randint(150, 250)
        
        for _ in range(request_count):
            lease = random.choice(leases)
            category = random.choice(MAINTENANCE_CATEGORIES)
            
            # Get description template
            template = random.choice(MAINTENANCE_TEMPLATES[category])
            description = template.format(unit=lease.unit.number)
            
            # Create maintenance request
            MaintenanceRequest.objects.create(
                tenant=lease.tenant,
                lease=lease,
                category=category,
                title=f"{category} Issue - Unit {lease.unit.number}",
                description=description,
                status=random.choice(['OPEN', 'IN_PROGRESS', 'RESOLVED']),
                priority=random.choice(['LOW', 'MEDIUM', 'HIGH']),
                created_at=date.today() - timedelta(days=random.randint(0, 365))
            )
        
        self.stdout.write(f"  Created {request_count} maintenance requests")

    def validate_dataset(self):
        """Validate created dataset and print summary"""
        self.stdout.write("\nValidating dataset...")
        
        # Count records
        units_count = Unit.objects.count()
        occupied_units = Unit.objects.filter(status='OCCUPIED').count()
        available_units = Unit.objects.filter(status='AVAILABLE').count()
        tenants_count = TenantProfile.objects.count()
        leases_count = Lease.objects.filter(is_active=True).count()
        water_readings_count = WaterReading.objects.count()
        bills_count = MonthlyBill.objects.count()
        payments_count = ManualPayment.objects.count()
        maintenance_count = MaintenanceRequest.objects.count()
        
        # Validation checks
        validations = [
            (units_count == 58, f"Units count: {units_count} (expected 58)"),
            (occupied_units == 39, f"Occupied units: {occupied_units} (expected 39)"),
            (available_units == 19, f"Available units: {available_units} (expected 19)"),
            (tenants_count == 39, f"Tenants count: {tenants_count} (expected 39)"),
            (leases_count == 39, f"Active leases: {leases_count} (expected 39)"),
            (water_readings_count == 39 * self.months, f"Water readings: {water_readings_count} (expected {39 * self.months})"),
            (bills_count == 39 * self.months, f"Monthly bills: {bills_count} (expected {39 * self.months})"),
        ]
        
        all_valid = True
        for is_valid, message in validations:
            status = "✓" if is_valid else "✗"
            self.stdout.write(f"  {status} {message}")
            if not is_valid:
                all_valid = False
        
        # Additional checks
        self.stdout.write(f"\nDataset Summary:")
        self.stdout.write(f"  Total units: {units_count}")
        self.stdout.write(f"  Occupied units: {occupied_units}")
        self.stdout.write(f"  Available units: {available_units}")
        self.stdout.write(f"  Tenants: {tenants_count}")
        self.stdout.write(f"  Active leases: {leases_count}")
        self.stdout.write(f"  Water readings: {water_readings_count}")
        self.stdout.write(f"  Monthly bills: {bills_count}")
        self.stdout.write(f"  Payments: {payments_count}")
        self.stdout.write(f"  Maintenance requests: {maintenance_count}")
        
        if all_valid:
            self.stdout.write(self.style.SUCCESS("\nDataset validation passed"))
        else:
            self.stdout.write(self.style.ERROR("\nDataset validation failed"))
            if not self.dry_run:
                raise CommandError("Dataset validation failed")
