#!/usr/bin/env python
"""
Test script to send sample tenant credentials email
"""

import os
import sys
import django

# Add project root to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RealEstateDemo.settings')
django.setup()

from rentals.services import send_tenant_credentials_email, generate_tenant_password

def test_send_sample_email():
    """Send a sample email to test the email functionality"""
    
    tenant_email = "demorip9@gmail.com"
    tenant_name = "John Arvin Tumbagahon"
    
    # Generate password using the implemented logic
    try:
        password = generate_tenant_password("John Arvin", "Tumbagahon")
        print(f"Generated password: {password}")
    except Exception as e:
        print(f"Error generating password: {e}")
        return
    
    print(f"Sending email to: {tenant_email}")
    print(f"Tenant name: {tenant_name}")
    print(f"Password: {password}")
    print("-" * 50)
    
    # Send the email
    try:
        success = send_tenant_credentials_email(
            tenant_email=tenant_email,
            tenant_name=tenant_name,
            password=password
        )
        
        if success:
            print("✅ Email sent successfully!")
            print(f"Check your inbox at {tenant_email}")
        else:
            print("❌ Failed to send email")
            
    except Exception as e:
        print(f"❌ Error sending email: {str(e)}")
        print("Please check your email configuration in settings.py")

if __name__ == "__main__":
    test_send_sample_email()
