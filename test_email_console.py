#!/usr/bin/env python
"""
Test script to show email content without actually sending (for testing)
"""

import os
import sys
import django

# Add project root to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RealEstateDemo.settings')
django.setup()

from rentals.services import generate_tenant_password

def show_email_preview():
    """Show the email that would be sent"""
    
    tenant_email = "demorip9@gmail.com"
    tenant_name = "John Arvin Tumbagahon"
    
    # Generate password using the implemented logic
    try:
        password = generate_tenant_password("John Arvin", "Tumbagahon")
        print(f"Generated password: {password}")
    except Exception as e:
        print(f"Error generating password: {e}")
        return
    
    print(f"Email would be sent to: {tenant_email}")
    print(f"Tenant name: {tenant_name}")
    print("=" * 60)
    
    # Email content
    email_content = f"""Subject: Welcome to REALESTATE360+ - Your Account Credentials

Dear {tenant_name},

Welcome to REALESTATE360+! Your tenant account has been successfully created.

Below are your login credentials:

Email: {tenant_email}
Password: {password}

You can now log in to your tenant portal to:
- View your billing statements
- Make payments
- Request maintenance
- Access announcements and updates

Please keep your credentials secure and do not share them with others.

If you have any questions or need assistance, please contact our support team.

Best regards,
REALESTATE360+ Team

---
From: REALESTATE360+ <johnarvint999@gmail.com>
To: {tenant_email}
"""
    
    print(email_content)
    print("=" * 60)
    
    # Instructions for setting up email
    print("TO ACTUALLY SEND THIS EMAIL:")
    print("1. Go to: https://myaccount.google.com/apppasswords")
    print("2. Generate a 16-character App Password")
    print("3. Update EMAIL_HOST_PASSWORD in settings.py")
    print("4. Run: python test_email_with_app_password.py")

if __name__ == "__main__":
    show_email_preview()
