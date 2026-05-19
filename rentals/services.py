from django.utils import timezone
from datetime import timedelta, date
from django.db.models import Count, Q, Avg, Max, F
from django.core.mail import send_mail
from django.conf import settings
from rentals.models import TenantRiskClassification, Lease, CalendarEvent
from billing.models import MonthlyBill
from payments.models import ManualPayment
import logging

logger = logging.getLogger(__name__)

class TenantRiskService:
    """Service for calculating and managing tenant risk classifications"""
    
    @staticmethod
    def calculate_tenant_risk_score(tenant):
        """
        Calculate risk score based on payment behavior
        Score: 0-100 (higher = better, lower risk)
        """
        try:
            # Get tenant's leases
            leases = Lease.objects.filter(tenant=tenant, is_active=True)
            if not leases:
                return 50  # Default score for tenants without active leases
            
            # Initialize score components
            payment_timeliness_score = 0
            payment_consistency_score = 0
            current_payment_status_score = 0
            payment_method_score = 0
            
            # 1. Payment Timeliness (40% of total score)
            payment_timeliness_score = TenantRiskService._calculate_payment_timeliness(tenant)
            
            # 2. Payment Consistency (30% of total score)
            payment_consistency_score = TenantRiskService._calculate_payment_consistency(tenant)
            
            # 3. Current Payment Status (20% of total score)
            current_payment_status_score = TenantRiskService._calculate_current_payment_status(tenant)
            
            # 4. Payment Method Reliability (10% of total score)
            payment_method_score = TenantRiskService._calculate_payment_method_reliability(tenant)
            
            # Calculate weighted total score
            total_score = (
                payment_timeliness_score * 0.4 +
                payment_consistency_score * 0.3 +
                current_payment_status_score * 0.2 +
                payment_method_score * 0.1
            )
            
            # Ensure score is within 0-100 range
            total_score = max(0, min(100, int(total_score)))
            
            return total_score
            
        except Exception as e:
            logger.error(f"Error calculating risk score for tenant {tenant.email}: {e}")
            return 50  # Default score on error
    
    @staticmethod
    def _calculate_payment_timeliness(tenant):
        """Calculate payment timeliness score (0-100)"""
        try:
            today = timezone.now().date()
            six_months_ago = timezone.now() - timedelta(days=180)

            # All bills in last 6 months (paid and unpaid)
            all_bills = MonthlyBill.objects.filter(
                lease__tenant=tenant,
                billing_month__gte=six_months_ago.date().replace(day=1)
            )

            # Fall back to full history if no recent bills
            if all_bills.count() == 0:
                all_bills = MonthlyBill.objects.filter(lease__tenant=tenant)

            if all_bills.count() == 0:
                return 50

            on_time_count = 0
            total_count = 0

            for bill in all_bills:
                # Skip upcoming bills (not yet due)
                if bill.billing_month.replace(day=1) > today.replace(day=1):
                    continue

                total_count += 1

                if bill.status == 'PAID' and bill.paid_at and bill.due_date:
                    days_late = (bill.paid_at.date() - bill.due_date).days
                    if days_late <= 0:
                        on_time_count += 1
                    # else: paid late — counts as not on time
                elif bill.status in ('UNPAID', 'PARTIALLY_PAID'):
                    # Overdue unpaid bill counts as not on time — do NOT increment on_time_count
                    pass

            if total_count == 0:
                return 50

            on_time_percentage = (on_time_count / total_count) * 100

            if on_time_percentage >= 90:
                return 100
            elif on_time_percentage >= 75:
                return 85
            elif on_time_percentage >= 60:
                return 70
            elif on_time_percentage >= 40:
                return 50
            elif on_time_percentage >= 20:
                return 30
            else:
                return 10

        except Exception as e:
            logger.error(f"Error calculating payment timeliness: {e}")
            return 50
    
    @staticmethod
    def _calculate_payment_consistency(tenant):
        """Calculate payment consistency score (0-100)"""
        try:
            # Get bills from last 12 months
            twelve_months_ago = timezone.now() - timedelta(days=365)
            all_bills = MonthlyBill.objects.filter(
                lease__tenant=tenant,
                billing_month__gte=twelve_months_ago
            )
            
            if all_bills.count() == 0:
                return 50  # No billing history
            
            paid_bills = all_bills.filter(status='PAID')
            payment_rate = (paid_bills.count() / all_bills.count()) * 100
            
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
            current_bills = MonthlyBill.objects.filter(
                lease__tenant=tenant,
                billing_month=current_month
            )
            
            if current_bills.count() == 0:
                return 70  # No current bills
            
            unpaid_current = current_bills.filter(status='UNPAID').count()
            total_current = current_bills.count()
            
            # Also check overdue bills
            overdue_bills = MonthlyBill.objects.filter(
                lease__tenant=tenant,
                status='UNPAID',
                due_date__lt=timezone.now().date()
            )
            
            total_unpaid = unpaid_current + overdue_bills.count()
            
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
            # Get manual payments
            manual_payments = ManualPayment.objects.filter(user=tenant)
            
            if manual_payments.count() == 0:
                return 70  # No manual payment history
            
            # Calculate approval rate
            approved_payments = manual_payments.filter(status='APPROVED').count()
            total_payments = manual_payments.count()
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
            # Get tenant's paid bills sorted by date
            paid_bills = MonthlyBill.objects.filter(
                lease__tenant=tenant,
                status='PAID'
            ).order_by('paid_at')
            
            if paid_bills.count() == 0:
                return False  # No payment history, not considered new
            
            # Check first payment date
            first_payment = paid_bills.first()
            if not first_payment or not first_payment.paid_at:
                return False
            
            # Calculate months since first payment
            months_since_first_payment = (timezone.now().date().year - first_payment.paid_at.date().year) * 12 + \
                                      (timezone.now().date().month - first_payment.paid_at.date().month)
            
            # Check if less than 3 months of payment history
            if months_since_first_payment < 3:
                return True
            
            # Also check if they have less than 3 paid bills
            return paid_bills.count() < 3
            
        except Exception as e:
            logger.error(f"Error checking if tenant is new: {e}")
            return False
    
    @staticmethod
    def update_tenant_risk_classification(tenant):
        """Update or create tenant risk classification"""
        try:
            # Calculate risk score
            risk_score = TenantRiskService.calculate_tenant_risk_score(tenant)
            
            # Get additional risk factors
            late_payments = MonthlyBill.objects.filter(
                lease__tenant=tenant,
                status='PAID',
                paid_at__gt=F('due_date')
            ).count()
            
            unpaid_bills = MonthlyBill.objects.filter(
                lease__tenant=tenant,
                status='UNPAID'
            ).count()
            
            last_payment = MonthlyBill.objects.filter(
                lease__tenant=tenant,
                status='PAID'
            ).order_by('-paid_at').first()
            
            # Check if tenant is new (less than 3 months of payment history)
            is_new_tenant = TenantRiskService._is_new_tenant(tenant)
            rf_prediction = None
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
                    'risk_factors': {
                        'payment_timeliness': TenantRiskService._calculate_payment_timeliness(tenant),
                        'payment_consistency': TenantRiskService._calculate_payment_consistency(tenant),
                        'current_payment_status': TenantRiskService._calculate_current_payment_status(tenant),
                        'payment_method_reliability': TenantRiskService._calculate_payment_method_reliability(tenant)
                    },
                    'rf_risk_level': rf_prediction.get('risk_level') if rf_prediction else None,
                    'rf_risk_probability': rf_prediction.get('probability') if rf_prediction else None,
                    'rf_top_factors': rf_prediction.get('top_factors') if rf_prediction else [],
                    'rf_model_version': rf_prediction.get('model_version') if rf_prediction else "",
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
    def update_all_tenant_risks():
        """Update risk classifications for all tenants"""
        from accounts.models import User
        
        tenants = User.objects.filter(role='TENANT')
        updated_count = 0
        
        for tenant in tenants:
            if TenantRiskService.update_tenant_risk_classification(tenant):
                updated_count += 1
        
        logger.info(f"Updated risk classifications for {updated_count} tenants")
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
    if not first_name or not last_name:
        raise ValueError("Both first_name and last_name are required")
    
    # Clean and split first name into parts to handle middle names
    first_name_clean = first_name.strip()
    last_name_clean = last_name.strip()
    
    if not first_name_clean or not last_name_clean:
        raise ValueError("First name and last name cannot be empty or whitespace only")
    
    # Split first name into parts to handle middle names (split by whitespace, not hyphens)
    name_parts = first_name_clean.split()
    
    # Get first letter of each part of the first name (including middle names)
    # Filter out any empty parts that might result from multiple spaces
    initials = ''.join([part[0].upper() for part in name_parts if part and len(part) > 0])
    
    if not initials:
        raise ValueError("Unable to generate initials from first name")
    
    # Combine with last name (preserve original casing, but strip whitespace)
    password = initials + last_name_clean
    
    # Ensure password is not too short (minimum 6 characters)
    if len(password) < 6:
        # Add random digits to make it more secure if too short
        import secrets
        # Calculate how many digits needed to reach minimum 6 characters
        digits_needed = 6 - len(password)
        password += ''.join(str(secrets.randbelow(10)) for _ in range(digits_needed))
    
    return password


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
    
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[tenant_email],
            fail_silently=False,
        )
        logger.info(f"Credentials email sent successfully to {tenant_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send credentials email to {tenant_email}: {str(e)}")
        return False


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
        
        # Advance payment event
        if lease.advance_months > 0:
            advance_amount = lease.advance_payment_amount
            if advance_amount > 0:
                events.append(CalendarEvent.objects.create(
                    lease=lease,
                    tenant=lease.tenant,
                    event_type='ADVANCE_PAYMENT',
                    event_date=lease.start_date,
                    amount=advance_amount,
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
    
    def get_payment_schedule_preview(self, lease_data):
        """
        Generate a preview of payment schedule without saving events
        
        Args:
            lease_data: Dictionary with lease information
            
        Returns:
            dict: Payment schedule preview
        """
        from datetime import date, timedelta
        import calendar
        
        monthly_rent = lease_data.get('monthly_rent', 0)
        advance_months = lease_data.get('advance_months', 2)
        security_deposit = lease_data.get('security_deposit', monthly_rent)
        start_date = lease_data.get('start_date')
        due_day = lease_data.get('due_day', 5)
        
        if not start_date:
            return None
        
        # Calculate amounts
        advance_payment_amount = monthly_rent * advance_months
        total_move_in_cost = security_deposit + advance_payment_amount
        
        # Generate upcoming events preview
        events = []
        
        # Initial payments
        events.append({
            'date': start_date,
            'type': 'Security Deposit',
            'amount': security_deposit
        })
        
        if advance_months > 0:
            events.append({
                'date': start_date,
                'type': 'Advance Payment',
                'amount': advance_payment_amount
            })
        
        # Calculate first rent due date
        first_rent_month = start_date
        for _ in range(advance_months):
            if first_rent_month.month == 12:
                first_rent_month = date(first_rent_month.year + 1, 1, 1)
            else:
                first_rent_month = date(first_rent_month.year, first_rent_month.month + 1, 1)
        
        last_day_of_month = calendar.monthrange(first_rent_month.year, first_rent_month.month)[1]
        adjusted_due_day = min(due_day, last_day_of_month)
        first_rent_date = date(first_rent_month.year, first_rent_month.month, adjusted_due_day)
        
        # Add next few rent payments (up to 6 months for preview)
        current_date = first_rent_date
        for i in range(min(6, 12 - advance_months)):
            events.append({
                'date': current_date,
                'type': 'Rent Due',
                'amount': monthly_rent
            })
            
            # Move to next month
            if current_date.month == 12:
                next_year = current_date.year + 1
                next_month = 1
            else:
                next_year = current_date.year
                next_month = current_date.month + 1
            
            # Adjust for invalid dates (e.g., February 31st)
            last_day_of_month = calendar.monthrange(next_year, next_month)[1]
            adjusted_due_day = min(due_day, last_day_of_month)
            current_date = date(next_year, next_month, adjusted_due_day)
        
        return {
            'monthly_rent': monthly_rent,
            'advance_months': advance_months,
            'advance_payment_amount': advance_payment_amount,
            'security_deposit': security_deposit,
            'total_move_in_cost': total_move_in_cost,
            'events': events
        }


def create_tenant_with_credentials(first_name, last_name, email, contact_no=None, uploaded_by=None):
    """
    Create a new tenant with auto-generated password and send credentials email
    
    Args:
        first_name: Tenant's first name (may include middle names)
        last_name: Tenant's last name
        email: Tenant's email address
        contact_no: Optional contact number
        uploaded_by: Admin user who created the tenant
    
    Returns:
        tuple: (tenant_profile, generated_password, email_sent_status)
    """
    from django.contrib.auth import get_user_model
    from .models import TenantProfile
    
    User = get_user_model()
    
    try:
        # Generate password
        password = generate_tenant_password(first_name, last_name)
        
        # Generate username from full name
        full_name = f"{first_name} {last_name}"
        username = User.generate_username_from_name(full_name)
        
        # Create user account
        user = User.objects.create_user(
            email=email,
            username=username,
            password=password
        )
        user.role = "TENANT"
        user.save()
        
        # Create tenant profile
        tenant_profile = TenantProfile.objects.create(
            user=user,
            first_name=first_name,
            last_name=last_name,
            contact_no=contact_no or '',
            send_credentials=True,  # Default to True for new tenants
            password_change_required=False,  # Default to False for new tenants
            created_by=uploaded_by
        )
        
        # Send credentials email
        email_sent = send_tenant_credentials_email(
            tenant_email=email,
            tenant_name=full_name,
            password=password
        )
        
        return tenant_profile, password, email_sent
        
    except Exception as e:
        logger.error(f"Failed to create tenant with credentials: {str(e)}")
        raise
