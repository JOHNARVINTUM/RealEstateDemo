# Email Setup Guide for REALESTATE360+ Tenant Credentials

## Current Issue
The email sending failed with Gmail authentication error. This is because Gmail requires an "App Password" for third-party applications instead of the regular account password.

## Solution: Set Up Gmail App Password

### Step 1: Enable 2-Factor Authentication
1. Go to your Google Account: https://myaccount.google.com/
2. Go to Security tab
3. Enable 2-Step Verification if not already enabled

### Step 2: Generate App Password
1. Go to: https://myaccount.google.com/apppasswords
2. Select "Mail" for the app
3. Select "Other (Custom name)" for the device
4. Name it: "REALESTATE360+ Tenant System"
5. Click "Generate"
6. Copy the 16-character password (without spaces)

### Step 3: Update Settings
Update your `settings.py` with the App Password:

```python
EMAIL_HOST_USER = 'your-email@gmail.com'
EMAIL_HOST_PASSWORD = 'your-16-character-app-password'  # Use the generated app password
DEFAULT_FROM_EMAIL = 'REALESTATE360+ <your-email@gmail.com>'
```

## Alternative Email Providers

If you prefer not to use Gmail, you can configure other SMTP providers:

### Outlook/Hotmail
```python
EMAIL_HOST = 'smtp-mail.outlook.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
```

### SendGrid (Recommended for Production)
```python
EMAIL_HOST = 'smtp.sendgrid.net'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'apikey'
EMAIL_HOST_PASSWORD = 'your-sendgrid-api-key'
```

## Test Email Functionality

After updating settings, run:
```bash
python test_email_send.py
```

## Security Notes
- Never commit actual passwords to version control
- Use environment variables in production
- Consider using a dedicated email account for the system
- Enable SPF/DKIM records for better deliverability

## Sample Email Content

The system will send emails like this:

```
Dear John Arvin Tumbagahon,

Welcome to REALESTATE360+! Your tenant account has been successfully created.

Below are your login credentials:

Email: demorip9@gmail.com
Password: JATumbagahon

You can now log in to your tenant portal to:
- View your billing statements
- Make payments
- Request maintenance
- Access announcements and updates

Please keep your credentials secure and do not share them with others.

If you have any questions or need assistance, please contact our support team.

Best regards,
REALESTATE360+ Team
```
