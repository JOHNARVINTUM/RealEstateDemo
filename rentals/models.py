from django.conf import settings
from django.db import models
from django.utils import timezone

class Unit(models.Model):
    UNIT_TYPES = [
        ('STUDIO', 'Studio'),
        ('1BR', '1 Bedroom'),
        ('2BR', '2 Bedrooms'),
        ('3BR', '3 Bedrooms'),
        ('PENTHOUSE', 'Penthouse'),
    ]
    
    STATUS_CHOICES = [
        ('AVAILABLE', 'Available'),
        ('OCCUPIED', 'Occupied'),
        ('MAINTENANCE', 'Under Maintenance'),
        ('RESERVED', 'Reserved'),
    ]
    
    number = models.CharField(max_length=10, unique=True)
    unit_type = models.CharField(max_length=20, choices=UNIT_TYPES, default='STUDIO')
    floor_level = models.PositiveSmallIntegerField(default=1)
    size_sqm = models.DecimalField(max_digits=8, decimal_places=2, default=25.00, help_text="Size in square meters")
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2, default=10000.00)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='AVAILABLE')
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    amenities = models.TextField(blank=True, help_text="List amenities separated by commas")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['floor_level', 'number']

    def __str__(self):
        return f"Unit {self.number} ({self.get_unit_type_display()})"

    @property
    def is_occupied(self):
        return self.status == 'OCCUPIED'

    @property
    def is_available(self):
        return self.status == 'AVAILABLE'

    def get_amenities_list(self):
        """Return amenities as a list"""
        if self.amenities:
            return [item.strip() for item in self.amenities.split(',') if item.strip()]
        return []

    def get_current_tenant(self):
        """Get current tenant if unit is occupied"""
        if self.is_occupied:
            try:
                lease = Lease.objects.get(unit=self, is_active=True)
                return lease.tenant
            except Lease.DoesNotExist:
                return None
        return None

class TenantProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    full_name = models.CharField(max_length=120)
    contact_no = models.CharField(max_length=30, blank=True)

    def __str__(self):
        return self.full_name

class Lease(models.Model):
    tenant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, limit_choices_to={"role": "TENANT"})
    unit = models.OneToOneField(Unit, on_delete=models.PROTECT)  # one active tenant per unit
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2)
    due_day = models.PositiveSmallIntegerField(default=5)  # e.g. due every 5th
    start_date = models.DateField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.tenant.email} -> {self.unit.number}"

class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('INFO', 'Information'),
        ('WARNING', 'Warning'),
        ('SUCCESS', 'Success'),
        ('ERROR', 'Error'),
        ('LEASE', 'Lease Related'),
        ('PAYMENT', 'Payment Related'),
        ('MAINTENANCE', 'Maintenance Related'),
        ('UNIT', 'Unit Related'),
    ]
    
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default='INFO')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Optional relationships
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, null=True, blank=True, help_text="Specific user this notification is for (null means all admins)")
    related_unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True, help_text="Related unit if applicable")
    related_tenant = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='tenant_notifications', help_text="Related tenant if applicable")
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} - {self.get_notification_type_display()}"
    
    @classmethod
    def create_notification(cls, title, message, notification_type='INFO', user=None, related_unit=None, related_tenant=None):
        """Helper method to create notifications"""
        return cls.objects.create(
            title=title,
            message=message,
            notification_type=notification_type,
            user=user,
            related_unit=related_unit,
            related_tenant=related_tenant
        )

class TenantRiskClassification(models.Model):
    RISK_LEVELS = [
        ('LOW', 'Low Risk'),
        ('MEDIUM', 'Medium Risk'),
        ('HIGH', 'High Risk'),
    ]
    
    tenant = models.OneToOneField('accounts.User', on_delete=models.CASCADE, limit_choices_to={'role': 'TENANT'})
    risk_level = models.CharField(max_length=10, choices=RISK_LEVELS, default='MEDIUM')
    payment_score = models.IntegerField(default=50, help_text="Payment behavior score (0-100)")
    late_payment_count = models.IntegerField(default=0, help_text="Number of late payments")
    unpaid_bill_count = models.IntegerField(default=0, help_text="Current unpaid bills")
    last_payment_date = models.DateTimeField(null=True, blank=True, help_text="Last successful payment date")
    is_new_tenant = models.BooleanField(default=False, help_text="Tenant with less than 3 months of payment history")
    risk_factors = models.JSONField(default=dict, help_text="JSON object storing risk factors")
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-risk_level', 'tenant__email']
        verbose_name = "Tenant Risk Classification"
        verbose_name_plural = "Tenant Risk Classifications"
    
    def __str__(self):
        return f"{self.tenant.email} - {self.get_risk_level_display()}"
    
    def calculate_risk_level(self):
        """Calculate risk level based on payment score and other factors"""
        if self.payment_score >= 80:
            self.risk_level = 'LOW'
        elif self.payment_score >= 50:
            self.risk_level = 'MEDIUM'
        else:
            self.risk_level = 'HIGH'
        self.save()

# Create your models here.
