# Email Deliverability Checklist

Tenant credentials, lease assignment, payment, and admin emails are sent through Resend.

Production configuration:

- Set `RESEND_API_KEY` in the deployment environment.
- Set `DEFAULT_FROM_EMAIL=REALESTATE360+ <noreply@realestate360.site>`.
- Verify `realestate360.site` in Resend.
- Add the SPF record Resend provides.
- Add the DKIM records Resend provides.
- Add a DMARC TXT record for the domain.
- Keep the sender domain aligned with `DEFAULT_FROM_EMAIL`.
- Check Resend event logs for `sent`, `delivered`, `bounced`, and `complained` events when a tenant reports missing email.

Gmail and Yahoo inbox placement cannot be guaranteed from code alone. SPF, DKIM, DMARC, sender reputation, and recipient behavior determine whether messages land in inbox or spam.
