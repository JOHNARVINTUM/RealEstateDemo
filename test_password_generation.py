#!/usr/bin/env python
"""
Test script for tenant password generation functionality
"""

import os
import sys
import django

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RealEstateDemo.settings')
django.setup()

from rentals.services import generate_tenant_password

def test_password_generation():
    """Test the password generation function with various name formats"""
    
    test_cases = [
        ("John", "Doe", "JDoe"),  # Will have random digits added if too short
        ("John Michael", "Smith", "JMSmith"),
        ("Maria", "Garcia", "MGarcia"),
        ("John Andrew Michael", "Smith", "JAMSmith"),
        ("Alice", "Brown", "ABrown"),  # Will have random digits added if too short
        ("Robert James", "Wilson", "RJWilson"),
        ("Elizabeth Anne Marie", "Johnson", "EAMJohnson"),
    ]
    
    print("Testing Password Generation Function")
    print("=" * 50)
    
    all_passed = True
    
    for first_name, last_name, expected in test_cases:
        try:
            result = generate_tenant_password(first_name, last_name)
            
            # Check if result matches expected or starts with expected (for short passwords that get random digits)
            if len(expected) < 6:  # Short passwords will have random digits added
                status = "✓ PASS" if result.startswith(expected) and len(result) >= 6 else "✗ FAIL"
                expected_display = f"{expected} (with random digits)"
            else:
                status = "✓ PASS" if result == expected else "✗ FAIL"
                expected_display = expected
                
            print(f"{status} | '{first_name}' '{last_name}' -> '{result}' (expected: '{expected_display}')")
            
            if status == "✗ FAIL":
                all_passed = False
                
        except Exception as e:
            print(f"✗ ERROR | '{first_name}' '{last_name}' -> Exception: {str(e)}")
            all_passed = False
    
    print("=" * 50)
    if all_passed:
        print("✓ All tests passed!")
    else:
        print("✗ Some tests failed!")
    
    return all_passed

if __name__ == "__main__":
    test_password_generation()
