"""
Management command to export ML-ready datasets for thesis research.
Exports CSV files for SARIMA forecasting, Random Forest prediction, and NLP classification.
"""

import csv
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List

from django.core.management.base import BaseCommand
from django.db.models import Sum, Avg, Count, Q, F, Min, Max
from django.conf import settings

from rentals.models import Unit, Lease
from maintenance.models import MaintenanceRequest
from billing.models import MonthlyBill
from payments.models import ManualPayment
from water.models import WaterReading


class Command(BaseCommand):
    help = "Export ML-ready datasets for thesis research"

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            type=str,
            default='exports/ml',
            help='Output directory for CSV files (default: exports/ml)'
        )
        parser.add_argument(
            '--months',
            type=int,
            default=36,
            help='Number of months of history to export (default: 36)'
        )

    def handle(self, *args, **options):
        self.output_dir = options['output_dir']
        self.months = options['months']
        
        self.stdout.write("=== ML Dataset Exporter ===")
        self.stdout.write(f"Output directory: {self.output_dir}")
        self.stdout.write(f"History months: {self.months}")
        
        # Create output directory
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Export datasets
        self.export_sarima_monthly_revenue()
        self.export_sarima_collections()
        self.export_sarima_water_consumption()
        self.export_random_forest_payment_risk()
        self.export_nlp_maintenance_requests()
        
        self.stdout.write(self.style.SUCCESS("\nAll ML datasets exported successfully"))

    def export_sarima_monthly_revenue(self):
        """Export monthly billing revenue for SARIMA forecasting"""
        self.stdout.write("\nExporting SARIMA monthly revenue dataset...")
        
        filename = os.path.join(self.output_dir, 'sarima_monthly_revenue.csv')
        
        # Get monthly billing data
        monthly_data = []
        for month_offset in range(self.months):
            month_date = (date.today().replace(day=1) - 
                         timedelta(days=month_offset * 30))
            
            # Calculate billed amounts
            bills = MonthlyBill.objects.filter(
                billing_month=month_date
            ).aggregate(
                total_billed=Sum(F('base_rent') + F('water_amount') + F('interest')),
                rent_billed=Sum('base_rent'),
                water_billed=Sum('water_amount'),
                interest_billed=Sum('interest')
            )
            
            # Get unit counts
            occupied_units = Unit.objects.filter(status='OCCUPIED').count()
            available_units = Unit.objects.filter(status='AVAILABLE').count()
            total_units = occupied_units + available_units
            occupancy_rate = (occupied_units / total_units * 100) if total_units > 0 else 0
            
            monthly_data.append({
                'month': month_date.strftime('%Y-%m-%d'),
                'total_billed': float(bills['total_billed'] or 0),
                'rent_billed': float(bills['rent_billed'] or 0),
                'water_billed': float(bills['water_billed'] or 0),
                'interest_billed': float(bills['interest_billed'] or 0),
                'occupied_units': occupied_units,
                'available_units': available_units,
                'occupancy_rate': round(occupancy_rate, 2)
            })
        
        # Sort by month
        monthly_data.sort(key=lambda x: x['month'])
        
        # Write CSV
        with open(filename, 'w', newline='') as csvfile:
            fieldnames = [
                'month', 'total_billed', 'rent_billed', 'water_billed', 
                'interest_billed', 'occupied_units', 'available_units', 'occupancy_rate'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(monthly_data)
        
        self.stdout.write(f"  Exported {len(monthly_data)} months to {filename}")

    def export_sarima_collections(self):
        """Export monthly payment collections for SARIMA forecasting"""
        self.stdout.write("\nExporting SARIMA collections dataset...")
        
        filename = os.path.join(self.output_dir, 'sarima_collections.csv')
        
        # Get monthly collection data
        monthly_data = []
        for month_offset in range(self.months):
            month_date = (date.today().replace(day=1) - 
                         timedelta(days=month_offset * 30))
            
            # Calculate collected amounts
            payments = ManualPayment.objects.filter(
                status='APPROVED',
                created_at__year=month_date.year,
                created_at__month=month_date.month
            ).aggregate(
                total_collected=Sum('amount'),
                gcash_collected=Sum('amount', filter=Q(payment_method='GCASH')),
                cash_collected=Sum('amount', filter=Q(payment_method='CASH'))
            )
            
            # Calculate on-time vs late collections
            on_time_collected = Decimal('0')
            late_collected = Decimal('0')
            partial_collected = Decimal('0')
            
            bills_paid = MonthlyBill.objects.filter(
                paid_at__year=month_date.year,
                paid_at__month=month_date.month,
                status='PAID'
            )
            
            for bill in bills_paid:
                if bill.paid_at and bill.due_date:
                    if bill.paid_at.date() <= bill.due_date:
                        on_time_collected += bill.total_due
                    else:
                        late_collected += bill.total_due
            
            # Partial payments
            partial_bills = MonthlyBill.objects.filter(
                billing_month=month_date,
                status='PARTIALLY_PAID'
            )
            for bill in partial_bills:
                partial_collected += bill.rent_paid + bill.water_paid
            
            monthly_data.append({
                'month': month_date.strftime('%Y-%m-%d'),
                'total_collected': float(payments['total_collected'] or 0),
                'gcash_collected': float(payments['gcash_collected'] or 0),
                'cash_collected': float(payments['cash_collected'] or 0),
                'on_time_collected': float(on_time_collected),
                'late_collected': float(late_collected),
                'partial_collected': float(partial_collected)
            })
        
        # Sort by month
        monthly_data.sort(key=lambda x: x['month'])
        
        # Write CSV
        with open(filename, 'w', newline='') as csvfile:
            fieldnames = [
                'month', 'total_collected', 'gcash_collected', 'cash_collected',
                'on_time_collected', 'late_collected', 'partial_collected'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(monthly_data)
        
        self.stdout.write(f"  Exported {len(monthly_data)} months to {filename}")

    def export_sarima_water_consumption(self):
        """Export monthly water consumption for SARIMA forecasting"""
        self.stdout.write("\nExporting SARIMA water consumption dataset...")
        
        filename = os.path.join(self.output_dir, 'sarima_water_consumption.csv')
        
        # Get monthly water consumption data
        monthly_data = []
        for month_offset in range(self.months):
            month_date = (date.today().replace(day=1) - 
                         timedelta(days=month_offset * 30))
            
            # Calculate consumption statistics
            readings = WaterReading.objects.filter(
                reading_month=month_date
            ).aggregate(
                total_consumption=Sum('consumption'),
                avg_consumption=Avg('consumption'),
                min_consumption=Min('consumption'),
                max_consumption=Max('consumption')
            )
            
            # Get occupied units count
            occupied_units = Unit.objects.filter(status='OCCUPIED').count()
            
            # Determine season
            month = month_date.month
            if month in [12, 1, 2]:
                season = 'Winter'
            elif month in [3, 4, 5]:
                season = 'Spring'
            elif month in [6, 7, 8]:
                season = 'Summer'
            else:
                season = 'Fall'
            
            monthly_data.append({
                'month': month_date.strftime('%Y-%m-%d'),
                'total_consumption': float(readings['total_consumption'] or 0),
                'average_consumption': float(readings['avg_consumption'] or 0),
                'min_consumption': float(readings['min_consumption'] or 0),
                'max_consumption': float(readings['max_consumption'] or 0),
                'occupied_units': occupied_units,
                'season': season
            })
        
        # Sort by month
        monthly_data.sort(key=lambda x: x['month'])
        
        # Write CSV
        with open(filename, 'w', newline='') as csvfile:
            fieldnames = [
                'month', 'total_consumption', 'average_consumption',
                'min_consumption', 'max_consumption', 'occupied_units', 'season'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(monthly_data)
        
        self.stdout.write(f"  Exported {len(monthly_data)} months to {filename}")

    def export_random_forest_payment_risk(self):
        """Export tenant-month payment risk data for Random Forest"""
        self.stdout.write("\nExporting Random Forest payment risk dataset...")
        
        filename = os.path.join(self.output_dir, 'random_forest_payment_risk.csv')
        
        # Get tenant-month data
        tenant_month_data = []
        leases = Lease.objects.filter(is_active=True).select_related('tenant', 'unit')
        
        for lease in leases:
            for month_offset in range(self.months):
                billing_month = (date.today().replace(day=1) - 
                               timedelta(days=month_offset * 30))
                
                # Get bill for this month
                try:
                    bill = MonthlyBill.objects.get(
                        lease=lease,
                        billing_month=billing_month
                    )
                except MonthlyBill.DoesNotExist:
                    continue
                
                # Calculate payment delay
                days_late = 0
                paid_on_time = False
                paid_within_7_days = False
                paid_within_30_days = False
                seriously_delayed = False
                
                if bill.paid_at:
                    days_late = (bill.paid_at.date() - bill.due_date).days
                    paid_on_time = days_late <= 0
                    paid_within_7_days = days_late <= 7
                    paid_within_30_days = days_late <= 30
                    seriously_delayed = days_late > 30
                else:
                    days_late = (date.today() - bill.due_date).days if date.today() > bill.due_date else 0
                    seriously_delayed = days_late > 30
                
                # Calculate historical payment behavior
                previous_bills = MonthlyBill.objects.filter(
                    lease=lease,
                    billing_month__lt=billing_month
                ).order_by('-billing_month')[:6]  # Last 6 months
                
                previous_late_count = 0
                previous_unpaid_count = 0
                delays = []
                
                for prev_bill in previous_bills:
                    if prev_bill.status == 'UNPAID':
                        previous_unpaid_count += 1
                    elif prev_bill.paid_at and prev_bill.due_date:
                        delay = (prev_bill.paid_at.date() - prev_bill.due_date).days
                        if delay > 0:
                            previous_late_count += 1
                            delays.append(delay)
                
                avg_delay_3m = sum(delays[:3]) / len(delays[:3]) if delays[:3] else 0
                avg_delay_6m = sum(delays) / len(delays) if delays else 0
                
                # Get payment method
                payment_method = 'UNKNOWN'
                if bill.paid_at:
                    payment = ManualPayment.objects.filter(
                        bill_ids__contains=str(bill.id),
                        status='APPROVED'
                    ).first()
                    if payment:
                        payment_method = payment.payment_method
                
                # Determine risk label
                if seriously_delayed or previous_unpaid_count >= 2:
                    risk_label = 'HIGH'
                elif previous_late_count >= 3 or avg_delay_6m > 14:
                    risk_label = 'MEDIUM'
                else:
                    risk_label = 'LOW'
                
                tenant_month_data.append({
                    'tenant_id': lease.tenant.id,
                    'unit_number': lease.unit.number,
                    'billing_month': billing_month.strftime('%Y-%m-%d'),
                    'monthly_rent': float(bill.base_rent),
                    'water_amount': float(bill.water_amount),
                    'total_due': float(bill.total_due),
                    'due_day': lease.due_day,
                    'days_late': days_late,
                    'paid_on_time': paid_on_time,
                    'paid_within_7_days': paid_within_7_days,
                    'paid_within_30_days': paid_within_30_days,
                    'seriously_delayed': seriously_delayed,
                    'previous_late_count': previous_late_count,
                    'previous_unpaid_count': previous_unpaid_count,
                    'average_delay_last_3_months': round(avg_delay_3m, 1),
                    'average_delay_last_6_months': round(avg_delay_6m, 1),
                    'payment_method': payment_method,
                    'partial_payment_flag': bill.status == 'PARTIALLY_PAID',
                    'risk_label': risk_label
                })
        
        # Sort by tenant and month
        tenant_month_data.sort(key=lambda x: (x['tenant_id'], x['billing_month']))
        
        # Write CSV
        with open(filename, 'w', newline='') as csvfile:
            fieldnames = [
                'tenant_id', 'unit_number', 'billing_month', 'monthly_rent', 'water_amount',
                'total_due', 'due_day', 'days_late', 'paid_on_time', 'paid_within_7_days',
                'paid_within_30_days', 'seriously_delayed', 'previous_late_count',
                'previous_unpaid_count', 'average_delay_last_3_months',
                'average_delay_last_6_months', 'payment_method', 'partial_payment_flag',
                'risk_label'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(tenant_month_data)
        
        self.stdout.write(f"  Exported {len(tenant_month_data)} tenant-months to {filename}")

    def export_nlp_maintenance_requests(self):
        """Export maintenance requests for NLP classification"""
        self.stdout.write("\nExporting NLP maintenance requests dataset...")
        
        filename = os.path.join(self.output_dir, 'nlp_maintenance_requests.csv')
        
        # Get maintenance requests
        requests = MaintenanceRequest.objects.select_related(
            'lease', 'lease__unit', 'tenant'
        ).order_by('created_at')
        
        # ML label mapping
        ml_label_mapping = {
            'PLUMBING': ['PLUMBING', 'WATER_ISSUE'],
            'ELECTRICAL': ['ELECTRICAL'],
            'STRUCTURAL': ['STRUCTURAL_DAMAGE'],
            'OTHER': ['HVAC_AC', 'NOISE_COMPLAINT', 'INTERNET_ISSUE', 'PEST_CONTROL']
        }
        
        request_data = []
        for req in requests:
            # Assign ML label (simple mapping for now)
            possible_labels = ml_label_mapping.get(req.category, ['OTHER'])
            ml_label = possible_labels[0]  # Take first possible label
            
            # More sophisticated mapping could be added here based on keywords
            description_lower = req.description.lower()
            if 'aircon' in description_lower or 'ac' in description_lower:
                ml_label = 'HVAC_AC'
            elif 'noise' in description_lower or 'noisy' in description_lower:
                ml_label = 'NOISE_COMPLAINT'
            elif 'internet' in description_lower or 'connection' in description_lower:
                ml_label = 'INTERNET_ISSUE'
            elif 'cockroach' in description_lower or 'pest' in description_lower:
                ml_label = 'PEST_CONTROL'
            elif 'crack' in description_lower or 'structural' in description_lower:
                ml_label = 'STRUCTURAL_DAMAGE'
            
            request_data.append({
                'request_id': req.id,
                'unit_number': req.lease.unit.number if req.lease else 'UNKNOWN',
                'description': req.description,
                'db_category': req.category,
                'ml_label': ml_label,
                'status': req.status,
                'priority': req.priority,
                'created_at': req.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'resolved_at': req.resolved_at.strftime('%Y-%m-%d %H:%M:%S') if req.resolved_at else ''
            })
        
        # Write CSV
        with open(filename, 'w', newline='') as csvfile:
            fieldnames = [
                'request_id', 'unit_number', 'description', 'db_category',
                'ml_label', 'status', 'priority', 'created_at', 'resolved_at'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(request_data)
        
        self.stdout.write(f"  Exported {len(request_data)} maintenance requests to {filename}")
