#!/usr/bin/env python3
"""
Complete dataset migration: Django -> SQLite -> Supabase PostgreSQL
Exports all Django data and creates migration scripts
"""

import os
import sys
import django
import sqlite3
import pandas as pd
from datetime import datetime
import json

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RealEstateDemo.settings')
django.setup()

# Import Django models
from accounts.models import User
from rentals.models import Unit, TenantProfile, Lease
from billing.models import MonthlyBill
from payments.models import ManualPayment
from water.models import WaterRate, WaterReading
from maintenance.models import MaintenanceRequest
from announcements.models import Announcement

def export_django_data_to_csv():
    """Export all Django data to CSV files for migration"""
    
    print("Exporting Django data to CSV files...")
    
    # Create export directory
    os.makedirs('exports/complete_dataset', exist_ok=True)
    
    # Export Users
    print("  Exporting Users...")
    users = User.objects.all().values(
        'id', 'username', 'email', 'first_name', 'last_name', 
        'role', 'is_active', 'date_joined', 'last_login'
    )
    users_df = pd.DataFrame(list(users))
    users_df.to_csv('exports/complete_dataset/users.csv', index=False)
    print(f"    ✓ Exported {len(users_df)} users")
    
    # Export Units
    print("  Exporting Units...")
    units = Unit.objects.all().values(
        'id', 'number', 'unit_type', 'monthly_rent', 'status', 'is_active',
        'size_sqm', 'floor_level', 'description', 'amenities'
    )
    units_df = pd.DataFrame(list(units))
    units_df.to_csv('exports/complete_dataset/units.csv', index=False)
    print(f"    ✓ Exported {len(units_df)} units")
    
    # Export TenantProfiles
    print("  Exporting TenantProfiles...")
    tenants = TenantProfile.objects.all().values(
        'id', 'user_id', 'first_name', 'last_name', 'contact_no',
        'has_seen_unit_welcome', 'send_credentials', 'password_change_required',
        'created_by_id', 'created_at', 'updated_at'
    )
    tenants_df = pd.DataFrame(list(tenants))
    tenants_df.to_csv('exports/complete_dataset/tenant_profiles.csv', index=False)
    print(f"    ✓ Exported {len(tenants_df)} tenant profiles")
    
    # Export Leases
    print("  Exporting Leases...")
    leases = Lease.objects.all().values(
        'id', 'tenant_id', 'unit_id', 'monthly_rent', 'due_day',
        'start_date', 'end_date', 'security_deposit', 'advance_months', 'is_active'
    )
    leases_df = pd.DataFrame(list(leases))
    leases_df.to_csv('exports/complete_dataset/leases.csv', index=False)
    print(f"    ✓ Exported {len(leases_df)} leases")
    
    # Export WaterRates
    print("  Exporting WaterRates...")
    water_rates = WaterRate.objects.all().values(
        'id', 'rate_per_cu_m', 'effective_date', 'is_active'
    )
    water_rates_df = pd.DataFrame(list(water_rates))
    water_rates_df.to_csv('exports/complete_dataset/water_rates.csv', index=False)
    print(f"    ✓ Exported {len(water_rates_df)} water rates")
    
    # Export WaterReadings
    print("  Exporting WaterReadings...")
    water_readings = WaterReading.objects.all().values(
        'id', 'lease_id', 'reading_month', 'previous_reading',
        'current_reading', 'consumption', 'rate_used', 'computed_amount',
        'is_first_reading', 'read_by_id'
    )
    water_readings_df = pd.DataFrame(list(water_readings))
    water_readings_df.to_csv('exports/complete_dataset/water_readings.csv', index=False)
    print(f"    ✓ Exported {len(water_readings_df)} water readings")
    
    # Export MonthlyBills
    print("  Exporting MonthlyBills...")
    bills = MonthlyBill.objects.all().values(
        'id', 'lease_id', 'billing_month', 'due_date', 'base_rent',
        'water_amount', 'interest', 'total_due', 'status',
        'rent_paid', 'water_paid', 'rent_paid_at', 'water_paid_at',
        'paid_at', 'payment_reference', 'water_computed_from_system',
        'source_water_reading_id'
    )
    bills_df = pd.DataFrame(list(bills))
    bills_df.to_csv('exports/complete_dataset/monthly_bills.csv', index=False)
    print(f"    ✓ Exported {len(bills_df)} monthly bills")
    
    # Export ManualPayments
    print("  Exporting ManualPayments...")
    payments = ManualPayment.objects.all().values(
        'id', 'user_id', 'reference_code', 'bill_ids', 'payment_type',
        'payment_method', 'amount', 'status', 'tenant_note',
        'preferred_date', 'preferred_time', 'schedule_confirmed',
        'created_at'
    )
    payments_df = pd.DataFrame(list(payments))
    payments_df.to_csv('exports/complete_dataset/manual_payments.csv', index=False)
    print(f"    ✓ Exported {len(payments_df)} manual payments")
    
    # Export MaintenanceRequests
    print("  Exporting MaintenanceRequests...")
    maintenance = MaintenanceRequest.objects.all().values(
        'id', 'tenant_id', 'lease_id', 'category', 'title', 'description',
        'status', 'priority', 'created_at', 'updated_at', 'resolved_at'
    )
    maintenance_df = pd.DataFrame(list(maintenance))
    maintenance_df.to_csv('exports/complete_dataset/maintenance_requests.csv', index=False)
    print(f"    ✓ Exported {len(maintenance_df)} maintenance requests")
    
    # Export Announcements
    print("  Exporting Announcements...")
    announcements = Announcement.objects.all().values(
        'id', 'title', 'body', 'is_active', 'created_by_id', 'created_at'
    )
    announcements_df = pd.DataFrame(list(announcements))
    announcements_df.to_csv('exports/complete_dataset/announcements.csv', index=False)
    print(f"    ✓ Exported {len(announcements_df)} announcements")
    
    print("\n✓ All data exported to exports/complete_dataset/")

def create_sqlite_schema():
    """Create complete SQLite schema"""
    
    print("Creating SQLite database schema...")
    
    # Remove existing database
    if os.path.exists('complete_dataset.db'):
        os.remove('complete_dataset.db')
    
    conn = sqlite3.connect('complete_dataset.db')
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE auth_user (
            id INTEGER PRIMARY KEY,
            username VARCHAR(150) NOT NULL UNIQUE,
            email VARCHAR(254) NOT NULL,
            first_name VARCHAR(150),
            last_name VARCHAR(150),
            role VARCHAR(20),
            is_active BOOLEAN NOT NULL DEFAULT 1,
            date_joined DATETIME NOT NULL,
            last_login DATETIME
        )
    ''')
    
    # Units table
    cursor.execute('''
        CREATE TABLE rentals_unit (
            id INTEGER PRIMARY KEY,
            number VARCHAR(10) NOT NULL,
            unit_type VARCHAR(20) NOT NULL,
            monthly_rent DECIMAL(10,2) NOT NULL,
            status VARCHAR(20) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            size_sqm DECIMAL(8,2),
            floor_level INTEGER,
            description TEXT,
            amenities TEXT
        )
    ''')
    
    # TenantProfiles table
    cursor.execute('''
        CREATE TABLE rentals_tenantprofile (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            first_name VARCHAR(60),
            last_name VARCHAR(60),
            contact_no VARCHAR(30),
            has_seen_unit_welcome BOOLEAN DEFAULT 0,
            send_credentials BOOLEAN DEFAULT 1,
            password_change_required BOOLEAN DEFAULT 0,
            created_by_id INTEGER,
            created_at DATETIME,
            updated_at DATETIME,
            FOREIGN KEY (user_id) REFERENCES auth_user (id),
            FOREIGN KEY (created_by_id) REFERENCES auth_user (id)
        )
    ''')
    
    # Leases table
    cursor.execute('''
        CREATE TABLE rentals_lease (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL,
            unit_id INTEGER NOT NULL,
            monthly_rent DECIMAL(10,2) NOT NULL,
            due_day INTEGER NOT NULL,
            start_date DATE NOT NULL,
            end_date DATE,
            security_deposit DECIMAL(10,2),
            advance_months INTEGER DEFAULT 2,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            FOREIGN KEY (tenant_id) REFERENCES auth_user (id),
            FOREIGN KEY (unit_id) REFERENCES rentals_unit (id)
        )
    ''')
    
    # WaterRates table
    cursor.execute('''
        CREATE TABLE water_waterrate (
            id INTEGER PRIMARY KEY,
            rate_per_cu_m DECIMAL(8,2) NOT NULL,
            effective_date DATE NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT 1
        )
    ''')
    
    # WaterReadings table
    cursor.execute('''
        CREATE TABLE water_waterreading (
            id INTEGER PRIMARY KEY,
            lease_id INTEGER NOT NULL,
            reading_month DATE NOT NULL,
            previous_reading DECIMAL(10,2),
            current_reading DECIMAL(10,2),
            consumption DECIMAL(10,2),
            rate_used DECIMAL(8,2),
            computed_amount DECIMAL(10,2),
            is_first_reading BOOLEAN DEFAULT 0,
            read_by_id INTEGER,
            FOREIGN KEY (lease_id) REFERENCES rentals_lease (id),
            FOREIGN KEY (read_by_id) REFERENCES auth_user (id)
        )
    ''')
    
    # MonthlyBills table
    cursor.execute('''
        CREATE TABLE billing_monthlybill (
            id INTEGER PRIMARY KEY,
            lease_id INTEGER NOT NULL,
            billing_month DATE NOT NULL,
            due_date DATE NOT NULL,
            base_rent DECIMAL(10,2) NOT NULL,
            water_amount DECIMAL(10,2) NOT NULL,
            interest DECIMAL(10,2) NOT NULL,
            total_due DECIMAL(10,2) NOT NULL,
            status VARCHAR(20) NOT NULL,
            rent_paid DECIMAL(10,2) DEFAULT 0,
            water_paid DECIMAL(10,2) DEFAULT 0,
            rent_paid_at DATE,
            water_paid_at DATE,
            paid_at DATE,
            payment_reference VARCHAR(100),
            water_computed_from_system BOOLEAN DEFAULT 1,
            source_water_reading_id INTEGER,
            FOREIGN KEY (lease_id) REFERENCES rentals_lease (id),
            FOREIGN KEY (source_water_reading_id) REFERENCES water_waterreading (id)
        )
    ''')
    
    # ManualPayments table
    cursor.execute('''
        CREATE TABLE payments_manualpayment (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            reference_code VARCHAR(100) NOT NULL,
            bill_ids TEXT,
            payment_type VARCHAR(20),
            payment_method VARCHAR(20),
            amount DECIMAL(10,2) NOT NULL,
            status VARCHAR(20) NOT NULL,
            tenant_note TEXT,
            preferred_date DATE,
            preferred_time VARCHAR(20),
            schedule_confirmed BOOLEAN DEFAULT 0,
            created_at DATETIME NOT NULL,
            FOREIGN KEY (user_id) REFERENCES auth_user (id)
        )
    ''')
    
    # MaintenanceRequests table
    cursor.execute('''
        CREATE TABLE maintenance_maintenancerequest (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL,
            lease_id INTEGER NOT NULL,
            category VARCHAR(20) NOT NULL,
            title VARCHAR(200) NOT NULL,
            description TEXT NOT NULL,
            status VARCHAR(20) NOT NULL,
            priority VARCHAR(20) NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME,
            resolved_at DATETIME,
            FOREIGN KEY (tenant_id) REFERENCES rentals_tenantprofile (id),
            FOREIGN KEY (lease_id) REFERENCES rentals_lease (id)
        )
    ''')
    
    # Announcements table
    cursor.execute('''
        CREATE TABLE announcements_announcement (
            id INTEGER PRIMARY KEY,
            title VARCHAR(200) NOT NULL,
            body TEXT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            created_by_id INTEGER,
            created_at DATETIME NOT NULL,
            FOREIGN KEY (created_by_id) REFERENCES auth_user (id)
        )
    ''')
    
    # Create indexes
    indexes = [
        'CREATE INDEX idx_lease_tenant ON rentals_lease(tenant_id)',
        'CREATE INDEX idx_lease_unit ON rentals_lease(unit_id)',
        'CREATE INDEX idx_bill_lease ON billing_monthlybill(lease_id)',
        'CREATE INDEX idx_bill_month ON billing_monthlybill(billing_month)',
        'CREATE INDEX idx_payment_user ON payments_manualpayment(user_id)',
        'CREATE INDEX idx_water_lease ON water_waterreading(lease_id)',
        'CREATE INDEX idx_water_month ON water_waterreading(reading_month)',
        'CREATE INDEX idx_maintenance_tenant ON maintenance_maintenancerequest(tenant_id)',
        'CREATE INDEX idx_maintenance_lease ON maintenance_maintenancerequest(lease_id)',
    ]
    
    for index_sql in indexes:
        cursor.execute(index_sql)
    
    conn.commit()
    print("✓ SQLite schema created successfully!")
    
    return conn

def load_csv_to_sqlite(conn):
    """Load all CSV data into SQLite"""
    
    cursor = conn.cursor()
    
    print("\nLoading CSV data into SQLite...")
    
    # Load data in correct order (respecting foreign keys)
    tables = [
        ('users.csv', 'auth_user'),
        ('units.csv', 'rentals_unit'),
        ('tenant_profiles.csv', 'rentals_tenantprofile'),
        ('leases.csv', 'rentals_lease'),
        ('water_rates.csv', 'water_waterrate'),
        ('water_readings.csv', 'water_waterreading'),
        ('monthly_bills.csv', 'billing_monthlybill'),
        ('manual_payments.csv', 'payments_manualpayment'),
        ('maintenance_requests.csv', 'maintenance_maintenancerequest'),
        ('announcements.csv', 'announcements_announcement'),
    ]
    
    for csv_file, table_name in tables:
        try:
            df = pd.read_csv(f'exports/complete_dataset/{csv_file}')
            
            # Handle NaN values
            df = df.where(pd.notnull(df), None)
            
            # Insert data
            for _, row in df.iterrows():
                columns = ', '.join(df.columns)
                placeholders = ', '.join(['?' for _ in df.columns])
                sql = f'INSERT INTO {table_name} ({columns}) VALUES ({placeholders})'
                cursor.execute(sql, tuple(row))
            
            print(f"  ✓ Loaded {len(df)} records into {table_name}")
            
        except Exception as e:
            print(f"  ✗ Error loading {csv_file}: {e}")
    
    conn.commit()

def validate_sqlite_data(conn):
    """Validate data integrity in SQLite"""
    
    cursor = conn.cursor()
    
    print("\nValidating SQLite data...")
    
    # Check record counts
    tables = [
        ('auth_user', 'Users'),
        ('rentals_unit', 'Units'),
        ('rentals_tenantprofile', 'Tenant Profiles'),
        ('rentals_lease', 'Leases'),
        ('water_waterrate', 'Water Rates'),
        ('water_waterreading', 'Water Readings'),
        ('billing_monthlybill', 'Monthly Bills'),
        ('payments_manualpayment', 'Manual Payments'),
        ('maintenance_maintenancerequest', 'Maintenance Requests'),
        ('announcements_announcement', 'Announcements'),
    ]
    
    print("\nRecord Counts:")
    print("-" * 30)
    for table_name, display_name in tables:
        cursor.execute(f'SELECT COUNT(*) FROM {table_name}')
        count = cursor.fetchone()[0]
        print(f"{display_name:20} : {count:,}")
    
    # Check data relationships
    print("\nData Relationships:")
    print("-" * 30)
    
    # Check occupied vs vacant units
    cursor.execute('''
        SELECT 
            COUNT(*) as total_units,
            SUM(CASE WHEN status = 'OCCUPIED' THEN 1 ELSE 0 END) as occupied,
            SUM(CASE WHEN status = 'AVAILABLE' THEN 1 ELSE 0 END) as available
        FROM rentals_unit
    ''')
    unit_stats = cursor.fetchone()
    print(f"Units: {unit_stats[0]} total, {unit_stats[1]} occupied, {unit_stats[2]} available")
    
    # Check active leases
    cursor.execute('SELECT COUNT(*) FROM rentals_lease WHERE is_active = 1')
    active_leases = cursor.fetchone()[0]
    print(f"Active leases: {active_leases}")
    
    # Check billing summary
    cursor.execute('''
        SELECT 
            COUNT(*) as total_bills,
            SUM(total_due) as total_amount,
            AVG(total_due) as avg_amount
        FROM billing_monthlybill
    ''')
    bill_stats = cursor.fetchone()
    print(f"Bills: {bill_stats[0]} total, Total: ₱{bill_stats[1]:,.2f}, Avg: ₱{bill_stats[2]:,.2f}")
    
    # Check payment summary
    cursor.execute('''
        SELECT 
            COUNT(*) as total_payments,
            SUM(CASE WHEN status = 'APPROVED' THEN amount ELSE 0 END) as approved_amount,
            SUM(amount) as total_amount
        FROM payments_manualpayment
    ''')
    payment_stats = cursor.fetchone()
    print(f"Payments: {payment_stats[0]} total, Approved: ₱{payment_stats[1]:,.2f}, Total: ₱{payment_stats[2]:,.2f}")

def generate_postgresql_migration():
    """Generate PostgreSQL migration script for Supabase"""
    
    print("\nGenerating PostgreSQL migration script...")
    
    migration_sql = """
-- Complete Dataset Migration Script for Supabase PostgreSQL
-- Generated from Django SQLite structure

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table (auth_user)
CREATE TABLE auth_user (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(150) NOT NULL UNIQUE,
    email VARCHAR(254) NOT NULL,
    first_name VARCHAR(150),
    last_name VARCHAR(150),
    role VARCHAR(20),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    date_joined TIMESTAMP WITH TIME ZONE NOT NULL,
    last_login TIMESTAMP WITH TIME ZONE
);

-- Units table
CREATE TABLE rentals_unit (
    id BIGSERIAL PRIMARY KEY,
    number VARCHAR(10) NOT NULL,
    unit_type VARCHAR(20) NOT NULL,
    monthly_rent DECIMAL(10,2) NOT NULL,
    status VARCHAR(20) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    size_sqm DECIMAL(8,2),
    floor_level INTEGER,
    description TEXT,
    amenities TEXT
);

-- TenantProfiles table
CREATE TABLE rentals_tenantprofile (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    first_name VARCHAR(60),
    last_name VARCHAR(60),
    contact_no VARCHAR(30),
    has_seen_unit_welcome BOOLEAN DEFAULT FALSE,
    send_credentials BOOLEAN DEFAULT TRUE,
    password_change_required BOOLEAN DEFAULT FALSE,
    created_by_id BIGINT,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    FOREIGN KEY (user_id) REFERENCES auth_user (id),
    FOREIGN KEY (created_by_id) REFERENCES auth_user (id)
);

-- Leases table
CREATE TABLE rentals_lease (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    unit_id BIGINT NOT NULL,
    monthly_rent DECIMAL(10,2) NOT NULL,
    due_day INTEGER NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE,
    security_deposit DECIMAL(10,2),
    advance_months INTEGER DEFAULT 2,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    FOREIGN KEY (tenant_id) REFERENCES auth_user (id),
    FOREIGN KEY (unit_id) REFERENCES rentals_unit (id)
);

-- WaterRates table
CREATE TABLE water_waterrate (
    id BIGSERIAL PRIMARY KEY,
    rate_per_cu_m DECIMAL(8,2) NOT NULL,
    effective_date DATE NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- WaterReadings table
CREATE TABLE water_waterreading (
    id BIGSERIAL PRIMARY KEY,
    lease_id BIGINT NOT NULL,
    reading_month DATE NOT NULL,
    previous_reading DECIMAL(10,2),
    current_reading DECIMAL(10,2),
    consumption DECIMAL(10,2),
    rate_used DECIMAL(8,2),
    computed_amount DECIMAL(10,2),
    is_first_reading BOOLEAN DEFAULT FALSE,
    read_by_id BIGINT,
    FOREIGN KEY (lease_id) REFERENCES rentals_lease (id),
    FOREIGN KEY (read_by_id) REFERENCES auth_user (id)
);

-- MonthlyBills table
CREATE TABLE billing_monthlybill (
    id BIGSERIAL PRIMARY KEY,
    lease_id BIGINT NOT NULL,
    billing_month DATE NOT NULL,
    due_date DATE NOT NULL,
    base_rent DECIMAL(10,2) NOT NULL,
    water_amount DECIMAL(10,2) NOT NULL,
    interest DECIMAL(10,2) NOT NULL,
    total_due DECIMAL(10,2) NOT NULL,
    status VARCHAR(20) NOT NULL,
    rent_paid DECIMAL(10,2) DEFAULT 0,
    water_paid DECIMAL(10,2) DEFAULT 0,
    rent_paid_at DATE,
    water_paid_at DATE,
    paid_at DATE,
    payment_reference VARCHAR(100),
    water_computed_from_system BOOLEAN DEFAULT TRUE,
    source_water_reading_id BIGINT,
    FOREIGN KEY (lease_id) REFERENCES rentals_lease (id),
    FOREIGN KEY (source_water_reading_id) REFERENCES water_waterreading (id)
);

-- ManualPayments table
CREATE TABLE payments_manualpayment (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    reference_code VARCHAR(100) NOT NULL,
    bill_ids TEXT,
    payment_type VARCHAR(20),
    payment_method VARCHAR(20),
    amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(20) NOT NULL,
    tenant_note TEXT,
    preferred_date DATE,
    preferred_time VARCHAR(20),
    schedule_confirmed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    FOREIGN KEY (user_id) REFERENCES auth_user (id)
);

-- MaintenanceRequests table
CREATE TABLE maintenance_maintenancerequest (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    lease_id BIGINT NOT NULL,
    category VARCHAR(20) NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    priority VARCHAR(20) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE,
    resolved_at TIMESTAMP WITH TIME ZONE,
    FOREIGN KEY (tenant_id) REFERENCES rentals_tenantprofile (id),
    FOREIGN KEY (lease_id) REFERENCES rentals_lease (id)
);

-- Announcements table
CREATE TABLE announcements_announcement (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    body TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by_id BIGINT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    FOREIGN KEY (created_by_id) REFERENCES auth_user (id)
);

-- Create indexes for performance
CREATE INDEX idx_lease_tenant ON rentals_lease(tenant_id);
CREATE INDEX idx_lease_unit ON rentals_lease(unit_id);
CREATE INDEX idx_bill_lease ON billing_monthlybill(lease_id);
CREATE INDEX idx_bill_month ON billing_monthlybill(billing_month);
CREATE INDEX idx_payment_user ON payments_manualpayment(user_id);
CREATE INDEX idx_water_lease ON water_waterreading(lease_id);
CREATE INDEX idx_water_month ON water_waterreading(reading_month);
CREATE INDEX idx_maintenance_tenant ON maintenance_maintenancerequest(tenant_id);
CREATE INDEX idx_maintenance_lease ON maintenance_maintenancerequest(lease_id);

-- Add comments
COMMENT ON TABLE auth_user IS 'User accounts including admin and tenant users';
COMMENT ON TABLE rentals_unit IS 'Apartment units with pricing and availability';
COMMENT ON TABLE rentals_tenantprofile IS 'Tenant profile information';
COMMENT ON TABLE rentals_lease IS 'Lease agreements between tenants and units';
COMMENT ON TABLE water_waterrate IS 'Water billing rates';
COMMENT ON TABLE water_waterreading IS 'Monthly water meter readings';
COMMENT ON TABLE billing_monthlybill IS 'Monthly billing statements';
COMMENT ON TABLE payments_manualpayment IS 'Manual payment records';
COMMENT ON TABLE maintenance_maintenancerequest IS 'Maintenance request tickets';
COMMENT ON TABLE announcements_announcement IS 'System announcements';
"""
    
    with open('complete_dataset_migration_postgresql.sql', 'w') as f:
        f.write(migration_sql)
    
    print("✓ PostgreSQL migration script saved to: complete_dataset_migration_postgresql.sql")

def main():
    print("=== Complete Dataset Migration Setup ===\n")
    
    # Step 1: Export Django data to CSV
    export_django_data_to_csv()
    
    # Step 2: Create SQLite database
    conn = create_sqlite_schema()
    
    # Step 3: Load CSV data into SQLite
    load_csv_to_sqlite(conn)
    
    # Step 4: Validate data
    validate_sqlite_data(conn)
    
    # Step 5: Generate PostgreSQL migration
    generate_postgresql_migration()
    
    # Close connection
    conn.close()
    
    print(f"\n=== Migration Setup Complete ===")
    print(f"✓ SQLite database: complete_dataset.db")
    print(f"✓ CSV exports: exports/complete_dataset/")
    print(f"✓ PostgreSQL migration: complete_dataset_migration_postgresql.sql")
    print(f"\nNext steps:")
    print(f"1. Test the SQLite database")
    print(f"2. If data looks good, run the PostgreSQL script in Supabase")
    print(f"3. Use the CSV files to import data into Supabase")

if __name__ == "__main__":
    main()
