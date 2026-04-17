#!/usr/bin/env python
"""
Direct test to isolate the unit update issue
"""
import os
import sys
import django

# Setup Django
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RealEstateDemo.settings')
django.setup()

from rentals.models import Unit
from rentals.forms import UnitForm

def test_unit_update():
    print("=== DIRECT UNIT UPDATE TEST ===")
    
    # Get unit 09
    try:
        unit = Unit.objects.get(number='09')
        print(f"Unit 09 before update: PHP {unit.monthly_rent}")
    except Unit.DoesNotExist:
        print("Unit 09 not found")
        return
    
    # Test 1: Direct model update
    print("\n1. Testing direct model update...")
    unit.monthly_rent = 20000.00
    unit.save()
    print(f"Unit 09 after direct update: PHP {unit.monthly_rent}")
    
    # Test 2: Form update with manual data
    print("\n2. Testing form update...")
    unit.refresh_from_db()
    print(f"Unit 09 before form update: PHP {unit.monthly_rent}")
    
    form_data = {
        'number': '09',
        'unit_type': unit.unit_type,
        'floor_level': str(unit.floor_level),
        'monthly_rent': '25000.00',  # New value
        'status': unit.status,
        'description': unit.description or '',
        'amenities': unit.amenities or '',
        'size_sqm': '25.00'
    }
    
    form = UnitForm(form_data, instance=unit)
    print(f"Form is valid: {form.is_valid()}")
    
    if form.is_valid():
        print(f"Form cleaned monthly_rent: {form.cleaned_data['monthly_rent']}")
        updated_unit = form.save(commit=False)
        print(f"Unit after form.save(commit=False): PHP {updated_unit.monthly_rent}")
        updated_unit.is_active = True
        updated_unit.save()
        print(f"Unit after form.save(): PHP {updated_unit.monthly_rent}")
    else:
        print(f"Form errors: {form.errors}")
    
    # Test 3: Check final state
    print("\n3. Final check...")
    unit.refresh_from_db()
    print(f"Unit 09 final rent: PHP {unit.monthly_rent}")
    
    print("=== END TEST ===")

if __name__ == "__main__":
    test_unit_update()
