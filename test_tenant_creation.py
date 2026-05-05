#!/usr/bin/env python
"""
Test script for complete tenant creation with auto-generated password and email notification
"""

import os
import sys
import django
from unittest.mock import patch, MagicMock

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RealEstateDemo.settings')
django.setup()

from rentals.services import create_tenant_with_credentials, generate_tenant_password, send_tenant_credentials_email
from django.contrib.auth import get_user_model
from rentals.models import TenantProfile

User = get_user_model()

def test_complete_tenant_creation():
    """Test the complete tenant creation workflow"""
    
    print("Testing Complete Tenant Creation Workflow")
    print("=" * 60)
    
    import uuid
    
    test_data = [
        {
            "first_name": "John",
            "last_name": "Doe",
            "email": f"john.doe.{uuid.uuid4().hex[:8]}@test.com",
            "contact_no": "1234567890",
            "expected_password": "JDoe"
        },
        {
            "first_name": "Maria",
            "last_name": "Garcia",
            "email": f"maria.garcia.{uuid.uuid4().hex[:8]}@test.com",
            "contact_no": "0987654321",
            "expected_password": "MGarcia"
        },
        {
            "first_name": "John Michael",
            "last_name": "Smith",
            "email": f"john.smith.{uuid.uuid4().hex[:8]}@test.com",
            "contact_no": "5551234567",
            "expected_password": "JMSmith"
        }
    ]
    
    all_passed = True
    
    for i, data in enumerate(test_data):
        print(f"\nTest Case {i+1}: {data['first_name']} {data['last_name']}")
        print("-" * 40)
        
        try:
            # Mock the email sending to avoid actual email sending during tests
            with patch('rentals.services.send_mail') as mock_send_mail:
                mock_send_mail.return_value = True
                
                # Create tenant with credentials
                tenant_profile, generated_password, email_sent = create_tenant_with_credentials(
                    first_name=data['first_name'],
                    last_name=data['last_name'],
                    email=data['email'],
                    contact_no=data['contact_no'],
                    uploaded_by=None
                )
                
                # Verify tenant profile was created
                assert tenant_profile is not None, "Tenant profile should not be None"
                assert tenant_profile.first_name == data['first_name'], f"First name mismatch: {tenant_profile.first_name} != {data['first_name']}"
                assert tenant_profile.last_name == data['last_name'], f"Last name mismatch: {tenant_profile.last_name} != {data['last_name']}"
                assert tenant_profile.contact_no == data['contact_no'], f"Contact number mismatch: {tenant_profile.contact_no} != {data['contact_no']}"
                
                # Verify user account was created
                user = tenant_profile.user
                assert user is not None, "User should not be None"
                assert user.email == data['email'], f"Email mismatch: {user.email} != {data['email']}"
                assert user.role == "TENANT", f"Role mismatch: {user.role} != TENANT"
                assert user.check_password(generated_password), "Generated password should be valid"
                
                # Verify password generation (account for random digits added to short passwords)
                expected = data['expected_password']
                if len(expected) < 6:  # Short passwords will have random digits added
                    assert generated_password.startswith(expected) and len(generated_password) >= 6, f"Password mismatch: {generated_password} should start with {expected} and be at least 6 characters"
                else:
                    assert generated_password == expected, f"Password mismatch: {generated_password} != {expected}"
                
                # Verify email was sent
                assert email_sent == True, "Email should have been sent"
                mock_send_mail.assert_called_once()
                
                # Verify email content
                call_args = mock_send_mail.call_args
                assert data['email'] in call_args[1]['recipient_list'], "Recipient email should match"
                assert "REALESTATE360+" in call_args[1]['subject'], "Subject should contain REALESTATE360+"
                assert generated_password in call_args[1]['message'], "Password should be in email message"
                assert data['email'] in call_args[1]['message'], "Email should be in email message"
                
                print(f"✓ Tenant profile created: {tenant_profile}")
                print(f"✓ User account created: {user.email} (role: {user.role})")
                print(f"✓ Password generated: {generated_password}")
                print(f"✓ Email sent successfully")
                
                # Clean up - delete test data
                user.delete()
                print(f"✓ Test data cleaned up")
                
        except Exception as e:
            print(f"✗ ERROR: {str(e)}")
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All tenant creation tests passed!")
    else:
        print("✗ Some tenant creation tests failed!")
    
    return all_passed

def test_password_generation_edge_cases():
    """Test password generation with edge cases"""
    
    print("\nTesting Password Generation Edge Cases")
    print("=" * 50)
    
    edge_cases = [
        {
            "first_name": "A",
            "last_name": "B",
            "expected": "AB",  # Will have random digits added since it's too short
            "description": "Single character names"
        },
        {
            "first_name": "  John  Michael  ",
            "last_name": "  Smith  ",
            "expected": "JMSmith",
            "description": "Names with extra whitespace"
        },
        {
            "first_name": "mary-jane",
            "last_name": "o'connor",
            "expected": "Mo'connor",
            "description": "Names with special characters"
        }
    ]
    
    all_passed = True
    
    for case in edge_cases:
        try:
            result = generate_tenant_password(case['first_name'], case['last_name'])
            expected = case['expected']
            
            # Check if result matches expected or starts with expected (for short passwords that get random digits)
            if len(expected) < 6:  # Short passwords will have random digits added
                status = "✓ PASS" if result.startswith(expected) and len(result) >= 6 else "✗ FAIL"
                expected_display = f"{expected} (with random digits)"
            else:
                status = "✓ PASS" if result == expected else "✗ FAIL"
                expected_display = expected
                
            print(f"{status} | {case['description']}: '{result}' (expected: '{expected_display}')")
            
            if status == "✗ FAIL":
                all_passed = False
                
        except Exception as e:
            print(f"✗ ERROR | {case['description']}: Exception: {str(e)}")
            all_passed = False
    
    return all_passed

if __name__ == "__main__":
    success1 = test_complete_tenant_creation()
    success2 = test_password_generation_edge_cases()
    
    if success1 and success2:
        print("\n🎉 ALL TESTS PASSED! Tenant creation feature is working correctly.")
    else:
        print("\n❌ Some tests failed. Please check the implementation.")
