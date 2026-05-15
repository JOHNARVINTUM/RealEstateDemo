
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
