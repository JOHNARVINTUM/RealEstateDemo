from django.utils import timezone
from html import escape
from datetime import timedelta, date
from decimal import Decimal
from dataclasses import dataclass
from django.db import transaction
from django.db.models import Count, Q, Avg, Max, F, Min
from django.conf import settings
from rentals.models import TenantRiskClassification, Lease, CalendarEvent, Notification
from billing.models import MonthlyBill
from payments.models import ManualPayment
import logging

logger = logging.getLogger(__name__)


def _repair_get_lease_id_from_payment(payment):
    if isinstance(payment.metadata, dict):
        return payment.metadata.get("lease_id")
    return None


def _repair_candidate_leases(payment, lease_id=None):
    lease_qs = Lease.objects.select_for_update().filter(tenant=payment.user).select_related("unit")
    if lease_id:
        lease = lease_qs.filter(id=lease_id).first()
        if lease:
            return lease

    lease = lease_qs.filter(status=Lease.STATUS_ACTIVE).order_by("-start_date").first()
    if lease:
        return lease

    lease = lease_qs.filter(status=Lease.STATUS_PENDING_PAYMENT).order_by("-start_date", "-id").first()
    if lease:
        return lease

    return lease_qs.order_by("-start_date", "-id").first()


def _repair_activate_pending_lease(lease, payment):
    if lease.status != Lease.STATUS_PENDING_PAYMENT:
        return

    lease.activate(activated_at=payment.created_at or timezone.now())
    lease.unit.status = "OCCUPIED"
    lease.unit.save(update_fields=["status"])


def _repair_finalize_payment_record(payment, first_bill):
    update_fields = ["status"]
    payment.status = "APPROVED"
    if first_bill and payment.bill_ids != str(first_bill.id):
        payment.bill_ids = str(first_bill.id)
        update_fields.append("bill_ids")
    payment.save(update_fields=update_fields)


@transaction.atomic
def repair_historical_move_in_payment(payment):
    """
    Repair test-era move-in payments that were manually rejected even though the
    tenant really paid and the lease has already progressed.

    This preserves the original payment record and updates the lease/billing
    state through the existing lease and billing models.
    """
    from billing.services import ensure_bills_since_move_in, apply_move_in_payment_to_first_bill

    payment = ManualPayment.objects.select_for_update().select_related("user").get(pk=payment.pk)
    if payment.payment_type != "move_in":
        return False, "Only move-in payments can be repaired with this action."
    if payment.status == "APPROVED":
        return True, "Move-in payment is already approved."

    lease_id = _repair_get_lease_id_from_payment(payment)
    lease = _repair_candidate_leases(payment, lease_id=lease_id)
    if lease is None:
        return False, "No related lease was found for this move-in payment."

    _repair_activate_pending_lease(lease, payment)

    ensure_bills_since_move_in(lease)
    first_bill = apply_move_in_payment_to_first_bill(
        lease,
        payment_reference=payment.reference_code or "MOVE-IN-PAYMENT",
        paid_at=payment.created_at or timezone.now(),
    )

    _repair_finalize_payment_record(payment, first_bill)

    return True, "Historical move-in payment repaired successfully."


def is_resend_configured():
    return bool(getattr(settings, "RESEND_API_KEY", ""))


def _email_line_to_html(line):
    stripped = (line or "").strip()
    if not stripped:
        return ""
    if ":" in stripped and len(stripped.split(":", 1)[0]) <= 28:
        label, value = stripped.split(":", 1)
        value_html = escape(value.strip())
        if label.strip().lower() == "status" and value.strip().upper() == "PAID":
            value_html = (
                '<span style="display:inline-block;padding:5px 11px;border-radius:999px;'
                'border:1px solid #86efac;background:#dcfce7;color:#047857;'
                'font-size:12px;font-weight:900;letter-spacing:.04em;">PAID</span>'
            )
        return (
            '<tr>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;color:#64748b;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;">{escape(label.strip())}</td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;color:#0f172a;font-size:14px;font-weight:700;text-align:right;">{value_html}</td>'
            '</tr>'
        )
    return f'<p style="margin:0 0 14px;color:#334155;font-size:15px;line-height:1.6;">{escape(stripped)}</p>'


def render_realestate360_email_html(subject, message):
    lines = (message or "").splitlines()
    paragraphs = []
    detail_rows = []
    for line in lines:
        html_line = _email_line_to_html(line)
        if not html_line:
            continue
        if html_line.startswith("<tr>"):
            detail_rows.append(html_line)
        else:
            paragraphs.append(html_line)

    details_html = ""
    if detail_rows:
        details_html = (
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
            'style="border-collapse:collapse;margin:18px 0 20px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">'
            f"{''.join(detail_rows)}"
            '</table>'
        )

    return f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f3f6fb;font-family:Arial,Helvetica,sans-serif;color:#0f172a;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f3f6fb;padding:32px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;background:#ffffff;border:1px solid #dbe3ef;border-radius:18px;overflow:hidden;box-shadow:0 18px 45px rgba(15,23,42,.08);">
            <tr>
              <td style="padding:24px 28px;border-bottom:1px solid #e5e7eb;background:#ffffff;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    <td style="font-size:18px;font-weight:900;color:#0f172a;">RealEstate360+</td>
                    <td align="right" style="font-size:11px;font-weight:800;color:#2563eb;text-transform:uppercase;letter-spacing:.08em;">Tenant Portal</td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:30px 28px 10px;">
                <div style="display:inline-block;padding:7px 10px;border-radius:999px;background:#dcfce7;color:#047857;font-size:11px;font-weight:900;text-transform:uppercase;letter-spacing:.04em;">Official Notice</div>
                <h1 style="margin:16px 0 10px;color:#0f172a;font-size:26px;line-height:1.15;font-weight:900;">{escape(subject)}</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:0 28px 28px;">
                {''.join(paragraphs)}
                {details_html}
                <div style="margin-top:24px;padding:16px 18px;border-radius:14px;background:#eff6ff;border:1px solid #bfdbfe;color:#1e3a8a;font-size:13px;line-height:1.5;font-weight:700;">
                  Please sign in to your tenant portal for the latest account, billing, and appointment details.
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 28px;background:#0f172a;color:#cbd5e1;">
                <p style="margin:0;font-size:13px;font-weight:800;color:#ffffff;">RealEstate360+ Administration</p>
                <p style="margin:6px 0 0;font-size:12px;line-height:1.5;color:#94a3b8;">This is an automated service email. Keep this message for your records.</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def send_email_via_resend(to_email, subject, message):
    """
    Reusable helper to send email via Resend HTTP API.
    Returns True on success, False on failure (never raises).
    """
    if not is_resend_configured():
        logger.warning("Resend is not configured; skipped email to %s: %s", to_email, subject)
        return False

    try:
        import resend
        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send({
            'from': getattr(settings, "DEFAULT_FROM_EMAIL", "REALESTATE360+ <noreply@realestate360.site>"),
            'to': [to_email],
            'subject': subject,
            'text': message,
            'html': render_realestate360_email_html(subject, message),
        })
        logger.info(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        return False


class TenantRiskService:
    """Service for calculating and managing tenant risk classifications"""

    @staticmethod
    def _current_active_lease_queryset(tenant, today=None):
        if today is None:
            today = timezone.now().date()
        return Lease.objects.filter(
            tenant=tenant,
            status=Lease.STATUS_ACTIVE,
            start_date__lte=today,
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=today)
        )

    @staticmethod
    def _timeliness_bill_queryset(tenant, since_date):
        bills = MonthlyBill.objects.filter(
            lease__tenant=tenant,
            billing_month__gte=since_date,
        )
        if bills.count() == 0:
            return MonthlyBill.objects.filter(lease__tenant=tenant)
        return bills

    @staticmethod
    def _bill_is_future_month(bill, today):
        return bill.billing_month.replace(day=1) > today.replace(day=1)

    @staticmethod
    def _current_month_start():
        return timezone.now().date().replace(day=1)

    @staticmethod
    def _bill_paid_on_time(bill):
        if bill.status != 'PAID' or not bill.paid_at or not bill.due_date:
            return False
        return (bill.paid_at.date() - bill.due_date).days <= 0

    @staticmethod
    def _bill_paid_late(bill):
        if bill.status != 'PAID' or not bill.paid_at or not bill.due_date:
            return False
        return bill.paid_at.date() > bill.due_date

    @staticmethod
    def _timeliness_score_from_percentage(on_time_percentage):
        if on_time_percentage >= 90:
            return 100
        if on_time_percentage >= 75:
            return 85
        if on_time_percentage >= 60:
            return 70
        if on_time_percentage >= 40:
            return 50
        if on_time_percentage >= 20:
            return 30
        return 10

    @staticmethod
    def _build_risk_factors(tenant):
        return {
            'payment_timeliness': TenantRiskService._calculate_payment_timeliness(tenant),
            'payment_consistency': TenantRiskService._calculate_payment_consistency(tenant),
            'current_payment_status': TenantRiskService._calculate_current_payment_status(tenant),
            'payment_method_reliability': TenantRiskService._calculate_payment_method_reliability(tenant),
        }

    @staticmethod
    def _score_from_risk_factors(risk_factors):
        total_score = (
            risk_factors['payment_timeliness'] * 0.4 +
            risk_factors['payment_consistency'] * 0.3 +
            risk_factors['current_payment_status'] * 0.2 +
            risk_factors['payment_method_reliability'] * 0.1
        )
        return max(0, min(100, int(total_score)))
    
    @staticmethod
    def calculate_tenant_risk_score(tenant):
        """
        Calculate risk score based on payment behavior
        Score: 0-100 (higher = better, lower risk)
        """
        try:
            # Get tenant's leases
            leases = TenantRiskService._current_active_lease_queryset(tenant)
            if not leases:
                return 50  # Default score for tenants without active leases

            risk_factors = TenantRiskService._build_risk_factors(tenant)
            return TenantRiskService._score_from_risk_factors(risk_factors)
            
        except Exception as e:
            logger.error(f"Error calculating risk score for tenant {tenant.email}: {e}")
            return 50  # Default score on error
    
    @staticmethod
    def _calculate_payment_timeliness(tenant):
        """Calculate payment timeliness score (0-100)"""
        try:
            today = timezone.now().date()
            six_months_ago = timezone.now() - timedelta(days=180)

            all_bills = list(
                TenantRiskService._timeliness_bill_queryset(
                    tenant,
                    six_months_ago.date().replace(day=1),
                )
            )

            if not all_bills:
                return 50

            on_time_count = 0
            total_count = 0

            for bill in all_bills:
                if TenantRiskService._bill_is_future_month(bill, today) and bill.status != "PAID":
                    continue

                total_count += 1

                if TenantRiskService._bill_paid_on_time(bill):
                    on_time_count += 1

            if total_count == 0:
                return 50

            on_time_percentage = (on_time_count / total_count) * 100
            return TenantRiskService._timeliness_score_from_percentage(on_time_percentage)

        except Exception as e:
            logger.error(f"Error calculating payment timeliness: {e}")
            return 50

    @staticmethod
    def _calculate_payment_consistency(tenant):
        """Calculate payment consistency score (0-100)"""
        try:
            # Get bills from last 12 months
            twelve_months_ago = timezone.now() - timedelta(days=365)
            current_month = TenantRiskService._current_month_start()
            bill_counts = MonthlyBill.objects.filter(
                lease__tenant=tenant,
                billing_month__gte=twelve_months_ago,
            ).filter(
                Q(billing_month__lte=current_month) | Q(status="PAID"),
            ).aggregate(
                total_count=Count("id"),
                paid_count=Count("id", filter=Q(status="PAID")),
            )

            total_count = bill_counts["total_count"] or 0
            if total_count == 0:
                return 50  # No billing history

            paid_count = bill_counts["paid_count"] or 0
            payment_rate = (paid_count / total_count) * 100
            
            # Score based on payment rate
            if payment_rate >= 80:
                return 100
            elif payment_rate >= 70:
                return 85
            elif payment_rate >= 60:
                return 70
            elif payment_rate >= 50:
                return 50
            elif payment_rate >= 30:
                return 30
            else:
                return 10
                
        except Exception as e:
            logger.error(f"Error calculating payment consistency: {e}")
            return 50
    
    @staticmethod
    def _calculate_current_payment_status(tenant):
        """Calculate current payment status score (0-100)"""
        try:
            # Get current month bills
            current_month = timezone.now().date().replace(day=1)
            current_bill_counts = MonthlyBill.objects.filter(
                lease__tenant=tenant,
                billing_month=current_month
            ).aggregate(
                total_count=Count("id"),
                unpaid_count=Count("id", filter=Q(status="UNPAID")),
            )

            total_current = current_bill_counts["total_count"] or 0
            if total_current == 0:
                return 70  # No current bills

            unpaid_current = current_bill_counts["unpaid_count"] or 0

            # Also check overdue bills
            overdue_count = MonthlyBill.objects.filter(
                lease__tenant=tenant,
                status='UNPAID',
                due_date__lt=timezone.now().date(),
                billing_month__lte=current_month,
            ).exclude(
                billing_month=current_month,
            ).count()

            total_unpaid = unpaid_current + overdue_count
            
            # Score based on unpaid bills
            if total_unpaid == 0:
                return 100
            elif total_unpaid == 1:
                return 70
            elif total_unpaid == 2:
                return 40
            else:
                return 10
                
        except Exception as e:
            logger.error(f"Error calculating current payment status: {e}")
            return 50
    
    @staticmethod
    def _calculate_payment_method_reliability(tenant):
        """Calculate payment method reliability score (0-100)"""
        try:
            payment_counts = ManualPayment.objects.filter(user=tenant).aggregate(
                total_count=Count("id"),
                approved_count=Count("id", filter=Q(status="APPROVED")),
            )

            total_payments = payment_counts["total_count"] or 0
            if total_payments == 0:
                return 70  # No manual payment history

            approved_payments = payment_counts["approved_count"] or 0
            approval_rate = (approved_payments / total_payments) * 100
            
            # Score based on approval rate
            if approval_rate >= 95:
                return 100
            elif approval_rate >= 80:
                return 85
            elif approval_rate >= 60:
                return 70
            elif approval_rate >= 40:
                return 50
            else:
                return 30
                
        except Exception as e:
            logger.error(f"Error calculating payment method reliability: {e}")
            return 50
    
    @staticmethod
    def _is_new_tenant(tenant):
        """Check if tenant is new (less than 3 months of actual payment history)"""
        try:
            paid_bill_summary = MonthlyBill.objects.filter(
                lease__tenant=tenant,
                status='PAID'
            ).aggregate(
                total_count=Count("id"),
                first_paid_at=Min("paid_at"),
            )

            total_paid_bills = paid_bill_summary["total_count"] or 0
            first_paid_at = paid_bill_summary["first_paid_at"]

            if total_paid_bills == 0:
                return False  # No payment history, not considered new

            if not first_paid_at:
                return False

            # Calculate months since first payment
            months_since_first_payment = (timezone.now().date().year - first_paid_at.date().year) * 12 + \
                                      (timezone.now().date().month - first_paid_at.date().month)

            # Check if less than 3 months of payment history
            if months_since_first_payment < 3:
                return True

            # Also check if they have less than 3 paid bills
            return total_paid_bills < 3
            
        except Exception as e:
            logger.error(f"Error checking if tenant is new: {e}")
            return False
    
    @staticmethod
    def update_tenant_risk_classification(tenant, include_rf=True):
        """Update or create tenant risk classification"""
        try:
            risk_factors = TenantRiskService._build_risk_factors(tenant)
            risk_score = TenantRiskService._score_from_risk_factors(risk_factors)
            
            # Get additional risk factors
            paid_bills_for_late_count = MonthlyBill.objects.filter(
                lease__tenant=tenant,
                status='PAID',
                billing_month__lte=TenantRiskService._current_month_start(),
            ).only("status", "paid_at", "due_date")
            late_payments = sum(
                1
                for bill in paid_bills_for_late_count
                if TenantRiskService._bill_paid_late(bill)
            )
            
            unpaid_bills = MonthlyBill.objects.filter(
                lease__tenant=tenant,
                status='UNPAID',
                billing_month__lte=TenantRiskService._current_month_start(),
            ).count()
            
            last_payment = MonthlyBill.objects.filter(
                lease__tenant=tenant,
                status='PAID'
            ).order_by('-paid_at').first()
            
            # Check if tenant is new (less than 3 months of payment history)
            is_new_tenant = TenantRiskService._is_new_tenant(tenant)
            existing = TenantRiskClassification.objects.filter(tenant=tenant).first()
            rf_prediction = None
            if include_rf:
                try:
                    from accounts.ml.tenant_risk_model import predict_tenant_risk
                    rf_prediction = predict_tenant_risk(tenant)
                except Exception as e:
                    logger.warning(f"Random Forest tenant risk prediction unavailable for {tenant.email}: {e}")
            
            # Create or update risk classification
            risk_classification, created = TenantRiskClassification.objects.update_or_create(
                tenant=tenant,
                defaults={
                    'payment_score': risk_score,
                    'late_payment_count': late_payments,
                    'unpaid_bill_count': unpaid_bills,
                    'last_payment_date': last_payment.paid_at if last_payment else None,
                    'is_new_tenant': is_new_tenant,
                    'risk_factors': risk_factors,
                    'rf_risk_level': rf_prediction.get('risk_level') if rf_prediction else (existing.rf_risk_level if existing else None),
                    'rf_risk_probability': rf_prediction.get('probability') if rf_prediction else (existing.rf_risk_probability if existing else None),
                    'rf_top_factors': rf_prediction.get('top_factors') if rf_prediction else (existing.rf_top_factors if existing else []),
                    'rf_model_version': rf_prediction.get('model_version') if rf_prediction else (existing.rf_model_version if existing else ""),
                }
            )
            
            # Calculate and set risk level
            risk_classification.calculate_risk_level()
            
            logger.info(f"Updated risk classification for {tenant.email}: {risk_classification.get_risk_level_display()} ({risk_score}) - New Tenant: {is_new_tenant}")
            return risk_classification
            
        except Exception as e:
            logger.error(f"Error updating risk classification for tenant {tenant.email}: {e}")
            return None
    
    @staticmethod
    def update_all_tenant_risks(include_rf=True):
        """Update risk classifications for all tenants"""
        from accounts.models import User
        
        tenants = User.objects.filter(role='TENANT').only("id", "email")
        updated_count = 0
        
        for tenant in tenants:
            try:
                if TenantRiskService.update_tenant_risk_classification(tenant, include_rf=include_rf):
                    updated_count += 1
            except Exception as exc:
                logger.exception("Failed to update tenant risk for %s: %s", tenant.email, exc)
        
        logger.info(f"Updated risk classifications for {updated_count} tenants")
        return updated_count

    @staticmethod
    def refresh_missing_rf_predictions(classifications):
        """Fill RF predictions only for classifications that are still in checking state."""
        try:
            from accounts.ml.tenant_risk_model import predict_tenant_risk
        except Exception as exc:
            logger.warning("Random Forest tenant risk model unavailable during RF-only refresh: %s", exc)
            return 0

        updated_count = 0
        for classification in classifications.select_related("tenant"):
            try:
                prediction = predict_tenant_risk(classification.tenant)
                if not prediction:
                    continue
                classification.rf_risk_level = prediction.get("risk_level")
                classification.rf_risk_probability = prediction.get("probability")
                classification.rf_top_factors = prediction.get("top_factors") or []
                classification.rf_model_version = prediction.get("model_version") or ""
                classification.save(update_fields=[
                    "rf_risk_level",
                    "rf_risk_probability",
                    "rf_top_factors",
                    "rf_model_version",
                    "updated_at",
                ])
                updated_count += 1
            except Exception as exc:
                logger.warning(
                    "RF-only tenant risk refresh failed for tenant %s: %s",
                    getattr(classification.tenant, "email", None),
                    exc,
                )
        return updated_count


def generate_tenant_password(first_name, last_name):
    """
    Generate password based on tenant's full name.
    
    Format: First letters of first and middle names (if any) in uppercase + 
    full last name in lowercase (or original casing as stored)
    
    Examples:
    - John Doe -> JDoe
    - John Michael Smith -> JMSmith
    - Maria Garcia -> MGarcia
    - John Andrew Michael Smith -> JAMSmith
    """
    first_name_clean, last_name_clean = _normalize_tenant_name_parts(first_name, last_name)
    initials = _extract_tenant_initials(first_name_clean)
    password = _assemble_tenant_password(initials, last_name_clean)
    return _pad_tenant_password(password)


def _normalize_tenant_name_parts(first_name, last_name):
    if not first_name or not last_name:
        raise ValueError("Both first_name and last_name are required")

    first_name_clean = first_name.strip()
    last_name_clean = last_name.strip()
    if not first_name_clean or not last_name_clean:
        raise ValueError("First name and last name cannot be empty or whitespace only")
    return first_name_clean, last_name_clean


def _extract_tenant_initials(first_name_clean):
    initials = ''.join(part[0].upper() for part in first_name_clean.split() if part)
    if not initials:
        raise ValueError("Unable to generate initials from first name")
    return initials


def _assemble_tenant_password(initials, last_name_clean):
    return initials + last_name_clean


def _pad_tenant_password(password):
    if len(password) >= 6:
        return password

    import secrets
    digits_needed = 6 - len(password)
    return password + ''.join(str(secrets.randbelow(10)) for _ in range(digits_needed))


def send_tenant_credentials_email(tenant_email, tenant_name, password):
    """
    Send email with tenant login credentials
    
    Args:
        tenant_email: Tenant's email address
        tenant_name: Tenant's full name
        password: Generated password
    """
    subject = "Welcome to REALESTATE360+ - Your Account Credentials"
    
    message = f"""
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
    
    email_sent = send_email_via_resend(tenant_email, subject, message)
    if email_sent:
        logger.info(f"Credentials email sent successfully to {tenant_email}")
    else:
        logger.warning(f"Credentials email was not sent to {tenant_email}")
    return email_sent


@dataclass(frozen=True)
class TenantCreationRequest:
    first_name: str
    last_name: str
    email: str
    contact_no: str | None = None
    uploaded_by: object | None = None


def _coerce_tenant_creation_request(*args, **kwargs):
    if len(args) == 1 and isinstance(args[0], TenantCreationRequest):
        return args[0]
    if len(args) == 1 and isinstance(args[0], dict):
        return TenantCreationRequest(**args[0])

    values = {
        "first_name": kwargs.get("first_name", args[0] if len(args) > 0 else None),
        "last_name": kwargs.get("last_name", args[1] if len(args) > 1 else None),
        "email": kwargs.get("email", args[2] if len(args) > 2 else None),
        "contact_no": kwargs.get("contact_no", args[3] if len(args) > 3 else None),
        "uploaded_by": kwargs.get("uploaded_by", args[4] if len(args) > 4 else None),
    }
    return TenantCreationRequest(**values)


class LeaseSchedulingService:
    """Service for generating lease calendar events and managing payment schedules"""
    
    def generate_lease_events(self, lease):
        """
        Generate all calendar events for a lease
        
        Args:
            lease: Lease instance
            
        Returns:
            list: Created calendar events
        """
        from django.db import transaction
        
        events_created = []
        
        with transaction.atomic():
            # Delete existing events for this lease to avoid duplicates
            CalendarEvent.objects.filter(lease=lease).delete()
            
            # Generate one-time events
            events_created.extend(self._generate_one_time_events(lease))
            
            # Generate recurring rent events
            events_created.extend(self._generate_rent_events(lease))
            
            logger.info(f"Generated {len(events_created)} calendar events for lease {lease.id}")
        
        return events_created
    
    def _generate_one_time_events(self, lease):
        """Generate one-time events (security deposit, advance payment, contract dates)"""
        events = []
        
        # Security deposit event
        if lease.security_deposit > 0:
            events.append(CalendarEvent.objects.create(
                lease=lease,
                tenant=lease.tenant,
                event_type='SECURITY_DEPOSIT',
                event_date=lease.start_date,
                amount=lease.security_deposit,
                status='PENDING'
            ))
        
        # Contract deposit event, stored under the legacy ADVANCE_PAYMENT event type.
        contract_deposit = lease.contract_deposit
        if contract_deposit > 0:
            events.append(CalendarEvent.objects.create(
                lease=lease,
                tenant=lease.tenant,
                event_type='ADVANCE_PAYMENT',
                event_date=lease.start_date,
                amount=contract_deposit,
                status='PENDING'
            ))
        
        # Contract start event
        events.append(CalendarEvent.objects.create(
            lease=lease,
            tenant=lease.tenant,
            event_type='CONTRACT_START',
            event_date=lease.start_date,
            amount=None,
            status='PENDING'
        ))
        
        # Contract end event (if end_date is set)
        if lease.end_date:
            events.append(CalendarEvent.objects.create(
                lease=lease,
                tenant=lease.tenant,
                event_type='CONTRACT_END',
                event_date=lease.end_date,
                amount=None,
                status='PENDING'
            ))
        
        return events
    
    def _generate_rent_events(self, lease):
        """Generate recurring rent events"""
        events = []
        
        # Calculate first rent due date (after advance payment period)
        first_rent_date = lease.first_rent_due_date
        
        # Determine end date for rent generation
        end_date = lease.end_date
        if not end_date:
            # Default to 12 months from first rent date
            end_date = first_rent_date.replace(year=first_rent_date.year + 1)
        
        # Generate rent events from first_rent_date to end_date (max 12 months)
        current_date = first_rent_date
        months_generated = 0
        max_months = 12
        
        while current_date <= end_date and months_generated < max_months:
            events.append(CalendarEvent.objects.create(
                lease=lease,
                tenant=lease.tenant,
                event_type='RENT_DUE',
                event_date=current_date,
                amount=lease.monthly_rent,
                status='PENDING'
            ))
            
            # Move to next month
            if current_date.month == 12:
                next_year = current_date.year + 1
                next_month = 1
            else:
                next_year = current_date.year
                next_month = current_date.month + 1
            
            # Adjust for invalid dates (e.g., February 30th)
            import calendar
            last_day_of_month = calendar.monthrange(next_year, next_month)[1]
            adjusted_due_day = min(lease.due_day, last_day_of_month)
            current_date = date(next_year, next_month, adjusted_due_day)
            
            months_generated += 1
        
        return events
    
    def get_upcoming_events(self, tenant=None, limit=10):
        """Get upcoming pending events for dashboard"""
        return CalendarEvent.get_upcoming_events(tenant=tenant, limit=limit)

    @staticmethod
    def _schedule_next_month_date(current_date, due_day):
        if current_date.month == 12:
            next_year = current_date.year + 1
            next_month = 1
        else:
            next_year = current_date.year
            next_month = current_date.month + 1

        import calendar
        last_day_of_month = calendar.monthrange(next_year, next_month)[1]
        adjusted_due_day = min(due_day, last_day_of_month)
        return date(next_year, next_month, adjusted_due_day)

    @staticmethod
    def _build_payment_schedule_events(
        start_date,
        monthly_rent,
        advance_months,
        security_deposit,
        due_day,
        end_date=None,
    ):
        import calendar

        events = [
            {
                'date': start_date,
                'type': 'Security Deposit',
                'amount': security_deposit
            }
        ]

        if advance_months > 0:
            events.append({
                'date': start_date,
                'type': 'Advance Payment',
                'amount': monthly_rent * advance_months
            })

        first_rent_month = start_date
        for _ in range(advance_months):
            if first_rent_month.month == 12:
                first_rent_month = date(first_rent_month.year + 1, 1, 1)
            else:
                first_rent_month = date(first_rent_month.year, first_rent_month.month + 1, 1)

        last_day_of_month = calendar.monthrange(first_rent_month.year, first_rent_month.month)[1]
        adjusted_due_day = min(due_day, last_day_of_month)
        first_rent_date = date(first_rent_month.year, first_rent_month.month, adjusted_due_day)

        if end_date:
            month_diff = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
            cycle_count = 12 if month_diff >= 12 else max(month_diff + 1, 1)
        else:
            cycle_count = advance_months + min(6, max(12 - advance_months, 0))

        current_date = first_rent_date
        for _ in range(max(cycle_count - advance_months, 0)):
            events.append({
                'date': current_date,
                'type': 'Rent Due',
                'amount': monthly_rent
            })
            current_date = LeaseSchedulingService._schedule_next_month_date(current_date, due_day)

        return events

    def get_payment_schedule_preview(self, lease_data):
        """
        Generate a preview of payment schedule without saving events
        
        Args:
            lease_data: Dictionary with lease information
            
        Returns:
            dict: Payment schedule preview
        """
        monthly_rent = lease_data.get('monthly_rent', 0)
        advance_months = lease_data.get('advance_months', 2)
        security_deposit = lease_data.get('security_deposit', monthly_rent)
        start_date = lease_data.get('start_date')
        end_date = lease_data.get('end_date')
        due_day = lease_data.get('due_day', 5)
        
        if not start_date:
            return None

        advance_payment_amount = monthly_rent * advance_months
        total_move_in_cost = security_deposit + advance_payment_amount
        events = self._build_payment_schedule_events(
            start_date=start_date,
            monthly_rent=monthly_rent,
            advance_months=advance_months,
            security_deposit=security_deposit,
            due_day=due_day,
            end_date=end_date,
        )

        return {
            'monthly_rent': monthly_rent,
            'advance_months': advance_months,
            'advance_payment_amount': advance_payment_amount,
            'security_deposit': security_deposit,
            'total_move_in_cost': total_move_in_cost,
            'events': events
        }


def create_tenant_with_credentials(*args, **kwargs):
    """
    Create a new tenant with auto-generated password and send credentials email
    
    Args:
        Accepts either a TenantCreationRequest, a dict, or legacy positional fields.
    
    Returns:
        tuple: (tenant_profile, generated_password, email_sent_status)
    """
    from django.contrib.auth import get_user_model
    from .models import TenantProfile

    User = get_user_model()
    request = _coerce_tenant_creation_request(*args, **kwargs)
    
    try:
        password = generate_tenant_password(request.first_name, request.last_name)

        full_name = f"{request.first_name} {request.last_name}"
        username = User.generate_username_from_name(full_name)

        user = User.objects.create_user(
            email=request.email,
            username=username,
            password=password
        )
        user.role = "TENANT"
        user.save()

        tenant_profile = TenantProfile.objects.create(
            user=user,
            first_name=request.first_name,
            last_name=request.last_name,
            contact_no=request.contact_no or '',
            send_credentials=True,  # Default to True for new tenants
            password_change_required=False,  # Default to False for new tenants
            created_by=request.uploaded_by
        )

        email_sent = send_tenant_credentials_email(
            tenant_email=request.email,
            tenant_name=full_name,
            password=password
        )

        return tenant_profile, password, email_sent
        
    except Exception as e:
        logger.error(f"Failed to create tenant with credentials: {str(e)}")
        raise


class LeaseActivationService:
    """
    CENTRALIZED service for lease activation after payment verification.
    
    ALL payment methods (PayMongo webhook, GCash approval, Cash approval)
    must call this service to activate a lease.
    
    This ensures:
    - Consistent activation logic
    - No duplicate activation
    - Proper billing generation
    - Unit occupancy update
    - Audit trail
    """

    @staticmethod
    def _get_pending_or_active_lease(lease_id: int):
        try:
            return Lease.objects.select_for_update().get(
                id=lease_id,
                status=Lease.STATUS_PENDING_PAYMENT
            ), None
        except Lease.DoesNotExist:
            try:
                lease = Lease.objects.get(id=lease_id, status=Lease.STATUS_ACTIVE)
                logger.info(f"Lease {lease_id} already active, skipping activation")
                return lease, (True, "Lease already active")
            except Lease.DoesNotExist:
                logger.error(f"Lease {lease_id} not found or not in PENDING_PAYMENT status")
                return None, (False, "Lease not found or invalid status")

    @staticmethod
    def _activate_pending_lease(lease, lease_id: int, activated_at):
        activated = lease.activate(activated_at=activated_at)
        if not activated:
            logger.warning(f"Lease {lease_id} activation returned False (already active?)")
            return False, "Lease already active"
        return True, ""

    @staticmethod
    def _mark_unit_occupied(lease):
        unit = lease.unit
        unit.status = "OCCUPIED"
        unit.save(update_fields=['status'])

    @staticmethod
    def _generate_initial_billing(lease, payment_reference: str, activated_at):
        from billing.services import ensure_bills_since_move_in, set_bill_status, month_start

        ensure_bills_since_move_in(lease)

        first_bill_month = month_start(lease.start_date)
        first_bill = MonthlyBill.objects.filter(
            lease=lease,
            billing_month=first_bill_month
        ).first()

        if first_bill:
            set_bill_status(
                first_bill,
                status="PAID",
                payment_reference=payment_reference,
                paid_at=activated_at or timezone.now()
            )
        return first_bill

    @staticmethod
    def _record_move_in_payment(
        *,
        lease,
        payment_method: str,
        payment_reference: str,
        amount: Decimal,
        first_bill,
        existing_payment=None,
    ):
        bill_ids = str(first_bill.id) if first_bill else ""

        if existing_payment is not None:
            payment = ManualPayment.objects.select_for_update().get(pk=existing_payment.pk)
            payment.payment_type = "move_in"
            payment.payment_method = payment_method
            payment.amount = amount
            payment.reference_code = payment_reference
            payment.status = "APPROVED"
            payment.bill_ids = bill_ids
            if not payment.tenant_note:
                payment.tenant_note = f"Move-in payment via {payment_method}"
            payment.save(
                update_fields=[
                    "payment_type",
                    "payment_method",
                    "amount",
                    "reference_code",
                    "status",
                    "bill_ids",
                    "tenant_note",
                ]
            )
            return payment

        return ManualPayment.objects.create(
            user=lease.tenant,
            payment_type="move_in",
            payment_method=payment_method,
            amount=amount,
            reference_code=payment_reference,
            status="APPROVED",
            bill_ids=bill_ids,
            tenant_note=f"Move-in payment via {payment_method}",
        )

    @staticmethod
    def _send_activation_welcome(lease):
        try:
            profile = lease.tenant.tenantprofile
            tenant_name = profile.full_name
            profile.has_seen_unit_welcome = False
            profile.save(update_fields=["has_seen_unit_welcome"])

            email_sent = send_email_via_resend(
                to_email=lease.tenant.email,
                subject=f"[REALESTATE360+] Lease Activated for Unit {lease.unit.number}",
                message=(
                    f"Dear {tenant_name},\n\n"
                    "Your move-in payment has been confirmed and your lease is now active.\n\n"
                    f"Unit: {lease.unit.number}\n"
                    f"Monthly Rent: PHP {lease.monthly_rent:,.2f}\n"
                    f"Lease Start: {lease.start_date}\n"
                    f"Rent Due Day: Every {lease.due_day} of the month\n\n"
                    "Please use the tenant account credentials previously sent to your email to access your portal.\n\n"
                    "REALESTATE360+ Administration"
                ),
            )
            if not email_sent:
                logger.warning("Activation confirmation email failed for tenant %s", lease.tenant.email)

            Notification.create_tenant_notification(
                title=f"Welcome to Unit {lease.unit.number}",
                message=(
                    "Your move-in payment has been confirmed and your lease is now active.\n\n"
                    f"Unit: {lease.unit.number}\n"
                    f"Monthly Rent: PHP {lease.monthly_rent:,.2f}\n"
                    f"Lease Start: {lease.start_date}\n"
                    f"Rent Due Day: Every {lease.due_day} of the month\n\n"
                    "Your tenant portal is ready. Use the credentials previously sent to your email."
                ),
                notification_type="SYSTEM",
                tenant_user=lease.tenant,
                related_unit=lease.unit,
            )
        except Exception as exc:
            logger.exception("Failed to send activation welcome for lease %s: %s", lease.id, exc)
    
    @staticmethod
    def activate_lease_after_payment(
        lease_id: int,
        payment_method: str,
        payment_reference: str,
        amount: Decimal,
        activated_at=None,
        skip_billing_generation: bool = False,
        existing_payment=None,
    ) -> tuple[bool, str]:
        """
        Centralized lease activation after payment verification.
        
        Args:
            lease_id: The lease ID to activate
            payment_method: 'PAYMONGO', 'GCASH', or 'CASH'
            payment_reference: Reference code or transaction ID
            amount: Payment amount
            activated_at: Optional timestamp (defaults to now)
            skip_billing_generation: If True, don't generate bills (for edge cases)
        
        Returns:
            tuple: (success: bool, message: str)
        """
        from django.db import transaction
        
        try:
            with transaction.atomic():
                lease, early_result = LeaseActivationService._get_pending_or_active_lease(lease_id)
                if early_result:
                    if early_result[0] and lease and existing_payment is not None:
                        first_bill = None
                        if not skip_billing_generation:
                            first_bill = LeaseActivationService._generate_initial_billing(
                                lease,
                                payment_reference,
                                activated_at,
                            )
                        LeaseActivationService._record_move_in_payment(
                            lease=lease,
                            payment_method=payment_method,
                            payment_reference=payment_reference,
                            amount=amount,
                            first_bill=first_bill,
                            existing_payment=existing_payment,
                        )
                    return early_result

                activated, activation_message = LeaseActivationService._activate_pending_lease(
                    lease,
                    lease_id,
                    activated_at,
                )
                if not activated:
                    return True, activation_message

                LeaseActivationService._mark_unit_occupied(lease)

                first_bill = None
                if not skip_billing_generation:
                    first_bill = LeaseActivationService._generate_initial_billing(
                        lease,
                        payment_reference,
                        activated_at,
                    )

                payment_record = LeaseActivationService._record_move_in_payment(
                    lease=lease,
                    payment_method=payment_method,
                    payment_reference=payment_reference,
                    amount=amount,
                    first_bill=first_bill,
                    existing_payment=existing_payment,
                )
                if payment_record and first_bill:
                    from billing.services import create_and_send_invoice_for_payment

                    move_in_line = {
                        "bill_id": first_bill.id,
                        "billing_month": first_bill.billing_month.strftime("%B %Y"),
                        "unit": getattr(lease.unit, "number", ""),
                        "rent_charge": f"{lease.monthly_rent.quantize(Decimal('0.01'))}",
                        "water_charge": "0.00",
                        "parking_charge": f"{lease.parking_fee.quantize(Decimal('0.01'))}",
                        "security_deposit": f"{lease.security_deposit.quantize(Decimal('0.01'))}",
                        "contract_deposit": f"{lease.contract_deposit.quantize(Decimal('0.01'))}",
                        "late_fee": "0.00",
                        "total_due_before_payment": f"{Decimal(amount or 0).quantize(Decimal('0.01'))}",
                        "amount_paid": f"{Decimal(amount or 0).quantize(Decimal('0.01'))}",
                        "status_before_payment": "PENDING_PAYMENT",
                    }
                    create_and_send_invoice_for_payment(
                        payment_record,
                        [first_bill],
                        "move_in",
                        activated_at or timezone.now(),
                        lines=[move_in_line],
                        logger=logger,
                    )
                LeaseActivationService._send_activation_welcome(lease)
                
                logger.info(
                    f"Lease {lease_id} activated successfully. "
                    f"Payment: {payment_method} {payment_reference}, "
                    f"Amount: {amount}"
                )
                
                return True, f"Lease activated successfully. Payment recorded."
                
        except Exception as e:
            logger.exception(f"Failed to activate lease {lease_id}: {e}")
            return False, f"Activation failed: {str(e)}"




