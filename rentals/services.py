from django.utils import timezone
from datetime import timedelta
from django.db.models import Count, Q, Avg, Max, F
from rentals.models import TenantRiskClassification, Lease
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
            # Get paid bills from last 6 months
            six_months_ago = timezone.now() - timedelta(days=180)
            paid_bills = MonthlyBill.objects.filter(
                lease__tenant=tenant,
                status='PAID',
                paid_at__gte=six_months_ago
            )
            
            # If no recent payments, check all payment history
            if paid_bills.count() == 0:
                all_paid_bills = MonthlyBill.objects.filter(
                    lease__tenant=tenant,
                    status='PAID'
                )
                
                # If no payment history at all, give medium score
                if all_paid_bills.count() == 0:
                    return 50
                
                # Use all payment history instead
                paid_bills = all_paid_bills
            
            # Calculate average days late
            total_days_late = 0
            on_time_count = 0
            
            for bill in paid_bills:
                if bill.paid_at and bill.due_date:
                    days_late = (bill.paid_at.date() - bill.due_date).days
                    if days_late <= 0:  # On time or early
                        on_time_count += 1
                    else:
                        total_days_late += days_late
            
            total_bills = paid_bills.count()
            on_time_percentage = (on_time_count / total_bills) * 100
            
            # Score based on on-time percentage
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
                    }
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
