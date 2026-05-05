#!/usr/bin/env python
"""
Test script to send sample email with proper Gmail App Password setup
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

def test_send_sample_email_with_app_password():
    """Send a sample email using proper Gmail App Password"""
    
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
    
    # Test email content preview
    email_content = f"""
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
"""
    
    print("Email Content Preview:")
    print(email_content)
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
            print("Note: Check spam folder if not received")
        else:
            print("❌ Failed to send email")
            print("Please check your email configuration:")
            print("1. Ensure you have a Gmail App Password (not regular password)")
            print("2. Go to: https://myaccount.google.com/apppasswords")
            print("3. Generate app password for 'REALESTATE360+ Tenant System'")
            print("4. Update EMAIL_HOST_PASSWORD in settings.py")
            
    except Exception as e:
        print(f"❌ Error sending email: {str(e)}")
        print("\nTroubleshooting steps:")
        print("1. Verify Gmail App Password is correctly set")
        print("2. Check if Gmail SMTP is accessible")
        print("3. Ensure firewall allows SMTP connections")
        print("4. Try with a different email provider")

if __name__ == "__main__":
    test_send_sample_email_with_app_password()
