#!/usr/bin/env python
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RealEstateDemo.settings')
django.setup()

from rentals.models import Unit, TenantProfile, Lease
from django.contrib.auth.models import User

def check_current_state():
    print('=== EXISTING UNITS ===')
    units = Unit.objects.all()
    for unit in units:
        print(f'Unit {unit.number}: {unit.get_unit_type_display()} - Status: {unit.get_status_display()}')

    print('\n=== EXISTING TENANTS ===')
    tenants = TenantProfile.objects.all()
    for tenant in tenants:
        print(f'Tenant: {tenant.full_name} - Email: {tenant.user.email}')

    print('\n=== EXISTING LEASES ===')
    leases = Lease.objects.all()
    for lease in leases:
        print(f'Lease: {lease.tenant.email} -> Unit {lease.unit.number} (Active: {lease.is_active})')

def connect_units_to_tenants():
    print('\n=== CONNECTING UNITS TO TENANTS ===')
    
    # Get all available units
    available_units = Unit.objects.filter(status='AVAILABLE')
    print(f'Found {available_units.count()} available units')
    
    # Get all tenants without active leases
    tenants_without_leases = []
    for tenant in TenantProfile.objects.all():
        has_active_lease = Lease.objects.filter(tenant=tenant.user, is_active=True).exists()
        if not has_active_lease:
            tenants_without_leases.append(tenant)
    
    print(f'Found {len(tenants_without_leases)} tenants without active leases')
    
    # Connect tenants to units
    for i, tenant in enumerate(tenants_without_leases):
        if i >= available_units.count():
            print(f'Not enough units for all tenants. Connected {i} tenants.')
            break
            
        unit = available_units[i]
        
        # Create lease
        lease = Lease.objects.create(
            tenant=tenant.user,
            unit=unit,
            start_date=timezone.now().date(),
            is_active=True
        )
        
        # Update unit status
        unit.status = 'OCCUPIED'
        unit.save()
        
        print(f'Connected {tenant.full_name} to Unit {unit.number}')

if __name__ == '__main__':
    from django.utils import timezone
    
    print("Checking current database state...")
    check_current_state()
    
    response = input('\nDo you want to connect available units to tenants? (y/n): ')
    if response.lower() == 'y':
        connect_units_to_tenants()
        print('\n=== UPDATED STATE ===')
        check_current_state()
    else:
        print("No changes made.")
