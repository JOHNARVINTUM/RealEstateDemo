from django.conf import settings
from django.db import models
from django.utils import timezone
import os

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

    def get_primary_image(self):
        """Get primary image or first image as fallback"""
        primary_image = self.images.filter(is_primary=True).first()
        if primary_image:
            return primary_image
        return self.images.first()
    
    def get_image_url(self):
        """Return primary image URL or placeholder"""
        primary_image = self.get_primary_image()
        if primary_image and primary_image.image:
            return primary_image.image.url
        return "https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D&auto=format&fit=crop&w=2070&q=80"
    
    def get_all_images(self):
        """Get all images ordered by primary first then by order"""
        return self.images.all().order_by('-is_primary', 'order', 'created_at')
    
    def get_image_count(self):
        """Get total number of images"""
        return self.images.count()

class TenantProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    first_name = models.CharField(max_length=60)
    last_name = models.CharField(max_length=60)
    contact_no = models.CharField(max_length=30, blank=True)
    has_seen_unit_welcome = models.BooleanField(default=False, help_text="Track if tenant has seen the unit welcome popup")
    send_credentials = models.BooleanField(default=True, help_text="Whether to send login credentials via email")
    password_change_required = models.BooleanField(default=True, help_text="Whether tenant should change password on first login")
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='created_tenants', help_text="Admin who created this tenant profile")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def full_name(self):
        """Get the full name as a property for backward compatibility"""
        return f"{self.first_name} {self.last_name}"
    
    def get_first_name(self):
        """Get the first name for display purposes"""
        return self.first_name if self.first_name else "User"

class Lease(models.Model):
    MOTORCYCLE_FEE = 350
    CAR_FEE = 2500

    # Lease status choices
    STATUS_PENDING_PAYMENT = "PENDING_PAYMENT"
    STATUS_ACTIVE = "ACTIVE"
    STATUS_TERMINATED = "TERMINATED"
    STATUS_EXPIRED = "EXPIRED"
    
    STATUS_CHOICES = [
        (STATUS_PENDING_PAYMENT, "Pending Payment"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_TERMINATED, "Terminated"),
        (STATUS_EXPIRED, "Expired"),
    ]

    tenant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, limit_choices_to={"role": "TENANT"})
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)  # one active tenant per unit
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2)
    due_day = models.PositiveSmallIntegerField(default=5)  # e.g. due every 5th
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True, help_text="Lease end date (optional)")
    security_deposit = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Security deposit amount")
    deposit_multiplier = models.PositiveSmallIntegerField(default=2, help_text="Contract deposit multiplier (security deposit = monthly_rent × this value)")
    
    # Status and activation tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING_PAYMENT, help_text="Lease lifecycle status")
    is_active = models.BooleanField(default=False, help_text="Whether lease is currently active (backward compatibility)")
    activated_at = models.DateTimeField(null=True, blank=True, help_text="When lease was activated after payment")
    
    motorcycle_slots = models.PositiveSmallIntegerField(default=0, help_text="Number of motorcycle parking slots (₱350 each/mo)")
    car_slots = models.PositiveSmallIntegerField(default=0, help_text="Number of car parking slots (₱2,500 each/mo)")

    def __str__(self):
        return f"{self.tenant.email} -> {self.unit.number}"

    @property
    def parking_fee(self):
        """Monthly parking fee based on slot counts"""
        from decimal import Decimal
        return Decimal(self.motorcycle_slots * self.MOTORCYCLE_FEE + self.car_slots * self.CAR_FEE)

    @property
    def contract_deposit(self):
        """Contract deposit = monthly_rent × deposit_multiplier"""
        return self.monthly_rent * self.deposit_multiplier

    @property
    def advance_payment_amount(self):
        """Alias for backward compatibility"""
        return self.contract_deposit

    @property
    def total_move_in_cost(self):
        """Total move-in = 1st month rent + security deposit + parking fee"""
        return self.monthly_rent + self.security_deposit + self.parking_fee

    @property
    def first_rent_due_date(self):
        """First rent due on the due_day of the start month"""
        import calendar
        from datetime import date
        last_day = calendar.monthrange(self.start_date.year, self.start_date.month)[1]
        return date(self.start_date.year, self.start_date.month, min(self.due_day, last_day))
    
    def save(self, *args, **kwargs):
        """Override save to handle smart status setting"""
        from django.utils import timezone
        
        # Auto-populate security deposit = monthly_rent × deposit_multiplier if not set
        if self.security_deposit == 0 and self.monthly_rent:
            self.security_deposit = self.monthly_rent * self.deposit_multiplier
        
        # Sync is_active with status for backward compatibility
        # But respect manual status changes
        if self.status == self.STATUS_ACTIVE and not self.is_active:
            self.is_active = True
        elif self.status != self.STATUS_ACTIVE and self.is_active:
            self.is_active = False
        
        super().save(*args, **kwargs)
    
    def activate(self, activated_at=None):
        """
        Centralized lease activation.
        Call this ONLY after successful payment verification.
        """
        from django.utils import timezone
        
        if self.status == self.STATUS_ACTIVE:
            return False  # Already active, prevent duplicate activation
        
        self.status = self.STATUS_ACTIVE
        self.is_active = True
        self.activated_at = activated_at or timezone.now()
        self.save(update_fields=['status', 'is_active', 'activated_at'])
        return True
    
    def deactivate(self, end_date=None):
        """Deactivate lease (for termination or expiration)"""
        from django.utils import timezone
        
        self.status = self.STATUS_TERMINATED
        self.is_active = False
        if end_date:
            self.end_date = end_date
        self.save(update_fields=['status', 'is_active', 'end_date'])
    
    @property
    def is_pending_payment(self):
        """Check if lease is waiting for move-in payment"""
        return self.status == self.STATUS_PENDING_PAYMENT
    
    @property
    def display_status(self):
        """Human-readable status for UI"""
        status_map = {
            self.STATUS_PENDING_PAYMENT: "Pending Payment",
            self.STATUS_ACTIVE: "Active",
            self.STATUS_TERMINATED: "Terminated",
            self.STATUS_EXPIRED: "Expired",
        }
        return status_map.get(self.status, self.status)

class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('INFO', 'Information'),
        ('SYSTEM', 'System'),
        ('BILLING', 'Billing'),
        ('MAINTENANCE', 'Maintenance'),
        ('UNIT', 'Unit Related'),
        ('PAYMENT', 'Payment'),
        ('LEASE', 'Lease'),
    ]
    
    RECIPIENT_TYPES = [
        ('ADMIN', 'Admin'),
        ('TENANT', 'Tenant'),
        ('SPECIFIC_USER', 'Specific User'),
    ]
    
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default='INFO')
    recipient_type = models.CharField(max_length=20, choices=RECIPIENT_TYPES, default='SPECIFIC_USER', help_text="Type of recipient for role-based filtering")
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Optional relationships
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, null=True, blank=True, help_text="Specific user this notification is for (null means all admins)")
    related_unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True, help_text="Related unit if applicable")
    related_tenant = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='tenant_notifications', help_text="Related tenant if applicable")
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['user', 'recipient_type', 'is_read', 'created_at'],
                name='notif_user_read_created_idx',
            ),
            models.Index(
                fields=['is_read', 'read_at'],
                name='notif_read_at_idx',
            ),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.get_notification_type_display()}"
    
    @classmethod
    def create_notification(cls, title, message, notification_type='INFO', user=None, related_unit=None, related_tenant=None, recipient_type='SPECIFIC_USER'):
        """Helper method to create notifications"""
        return cls.objects.create(
            title=title,
            message=message,
            notification_type=notification_type,
            recipient_type=recipient_type,
            user=user,
            related_unit=related_unit,
            related_tenant=related_tenant
        )
    
    @classmethod
    def create_tenant_notification(cls, title, message, notification_type='SYSTEM', tenant_user=None, related_unit=None):
        """Helper method to create tenant-specific notifications"""
        return cls.create_notification(
            title=title,
            message=message,
            notification_type=notification_type,
            user=tenant_user,
            related_unit=related_unit,
            related_tenant=tenant_user,
            recipient_type='TENANT'
        )
    
    @classmethod
    def create_admin_notification(cls, title, message, notification_type='SYSTEM', admin_user=None):
        """Helper method to create admin-specific notifications"""
        return cls.create_notification(
            title=title,
            message=message,
            notification_type=notification_type,
            user=admin_user,
            recipient_type='ADMIN'
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
    rf_risk_level = models.CharField(max_length=10, choices=RISK_LEVELS, null=True, blank=True)
    rf_risk_probability = models.FloatField(null=True, blank=True)
    rf_top_factors = models.JSONField(default=list, blank=True)
    rf_model_version = models.CharField(max_length=50, blank=True, default="")
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

class UnitImage(models.Model):
    """Model for unit gallery images"""
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='units/', help_text="Unit image")
    caption = models.CharField(max_length=200, blank=True, help_text="Image caption (optional)")
    is_primary = models.BooleanField(default=False, help_text="Set as primary/featured image")
    created_at = models.DateTimeField(auto_now_add=True)
    order = models.PositiveSmallIntegerField(default=0, help_text="Display order")
    
    class Meta:
        ordering = ['order', 'created_at']
        verbose_name = "Unit Image"
        verbose_name_plural = "Unit Images"
    
    def __str__(self):
        return f"Image for {self.unit.number} - {self.id}"
    
    def save(self, *args, **kwargs):
        # Ensure only one primary image per unit
        if self.is_primary:
            UnitImage.objects.filter(unit=self.unit, is_primary=True).update(is_primary=False)
        super().save(*args, **kwargs)


class TenantAttachment(models.Model):
    """Model for tenant attachments like contracts and valid IDs"""
    ATTACHMENT_TYPES = [
        ('CONTRACT', 'Contract'),
        ('VALID_ID', 'Valid ID'),
        ('OTHER', 'Other Document'),
    ]
    
    tenant = models.ForeignKey('accounts.User', on_delete=models.CASCADE, limit_choices_to={'role': 'TENANT'})
    attachment_type = models.CharField(max_length=20, choices=ATTACHMENT_TYPES, default='OTHER')
    file = models.FileField(upload_to='tenant_attachments/', help_text="Upload contract or valid ID")
    description = models.CharField(max_length=200, blank=True, help_text="Brief description of the attachment")
    uploaded_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='uploaded_attachments')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = "Tenant Attachment"
        verbose_name_plural = "Tenant Attachments"
    
    def __str__(self):
        return f"{self.tenant.email} - {self.get_attachment_type_display()} - {self.file.name}"
    
    @property
    def filename(self):
        """Return just the filename without path"""
        return os.path.basename(self.file.name) if self.file else ""
    
    @property
    def file_extension(self):
        """Return file extension"""
        if self.file:
            return os.path.splitext(self.file.name)[1].lower()
        return ""
    
    @property
    def is_image(self):
        """Check if file is an image"""
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
        return self.file_extension in image_extensions
    
    @property
    def is_pdf(self):
        """Check if file is a PDF"""
        return self.file_extension == '.pdf'
    
    def get_file_size_display(self):
        """Return human-readable file size"""
        if self.file:
            try:
                size = self.file.size
            except (FileNotFoundError, OSError):
                return "File missing"
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size < 1024.0:
                    return f"{size:.1f} {unit}"
                size /= 1024.0
            return f"{size:.1f} TB"
        return "0 B"


class Room(models.Model):
    STATUS_CHOICES = [
        ('AVAILABLE', 'Available'),
        ('OCCUPIED', 'Occupied'),
        ('MAINTENANCE', 'Under Maintenance'),
    ]
    
    name = models.CharField(max_length=100, unique=True, help_text="Room name/number")
    price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Room price per month")
    description = models.TextField(blank=True, help_text="Room description and features")
    image = models.ImageField(upload_to='rooms/', blank=True, null=True, help_text="Room image")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='AVAILABLE', help_text="Room status")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
        verbose_name = "Room"
        verbose_name_plural = "Rooms"
    
    def __str__(self):
        return f"{self.name} - {self.get_status_display()}"
    
    def get_image_url(self):
        """Return room image URL or placeholder"""
        if self.image:
            return self.image.url
        return "https://via.placeholder.com/400x300/6366f1/ffffff?text=Room+Image"

class CalendarEvent(models.Model):
    """Calendar events for lease payments and important dates"""
    
    EVENT_TYPES = [
        ('RENT_DUE', 'Rent Due'),
        ('ADVANCE_PAYMENT', 'Advance Payment'),
        ('SECURITY_DEPOSIT', 'Security Deposit'),
        ('CONTRACT_START', 'Contract Start'),
        ('CONTRACT_END', 'Contract End'),
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('OVERDUE', 'Overdue'),
    ]
    
    lease = models.ForeignKey('Lease', on_delete=models.CASCADE, related_name='calendar_events')
    tenant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, limit_choices_to={"role": "TENANT"})
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    event_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['event_date']
        indexes = [
            models.Index(fields=['event_date', 'status']),
            models.Index(fields=['tenant', 'event_date']),
            models.Index(fields=['lease', 'event_type']),
        ]
    
    def __str__(self):
        return f"{self.get_event_type_display()} - {self.event_date} - {self.tenant.email}"
    
    @classmethod
    def get_upcoming_events(cls, tenant=None, limit=10):
        """Get upcoming pending events for dashboard and notifications"""
        from django.utils import timezone
        
        queryset = cls.objects.filter(
            event_date__gte=timezone.now().date(),
            status='PENDING'
        ).order_by('event_date')
        
        if tenant:
            queryset = queryset.filter(tenant=tenant)
        
        return queryset[:limit]
    
    @classmethod
    def update_overdue_events(cls):
        """Update status of overdue events"""
        from django.utils import timezone
        
        today = timezone.now().date()
        overdue_events = cls.objects.filter(
            event_date__lt=today,
            status='PENDING'
        )
        
        count = overdue_events.update(status='OVERDUE')
        return count
    
    def mark_as_paid(self):
        """Mark event as paid"""
        self.status = 'PAID'
        self.save()


class ArchivedTenant(models.Model):
    """
    Archive table for deleted/deactivated tenants.
    Stores complete tenant data for audit trail and potential recovery.
    """
    ARCHIVE_TYPE_CHOICES = [
        ('DEACTIVATED', 'Deactivated - Records Preserved'),
        ('DELETED_SOFT', 'Soft Deleted - Archived Only'),
        ('DELETED_HARD', 'Hard Deleted - With Records'),
    ]
    
    # Original identifiers
    original_user_id = models.IntegerField(help_text="Original User ID")
    original_tenant_id = models.IntegerField(help_text="Original TenantProfile ID")
    email = models.EmailField(help_text="Original email address")
    
    # Tenant data snapshot (JSON for flexibility)
    tenant_data = models.JSONField(
        help_text="Complete snapshot of tenant data including profile, leases, payments, etc.",
        encoder=None,
        decoder=None,
    )
    
    # Deletion metadata
    archive_type = models.CharField(
        max_length=20,
        choices=ARCHIVE_TYPE_CHOICES,
        default='DEACTIVATED',
        help_text="Type of deletion/archive action performed"
    )
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='archived_tenants',
        help_text="Admin who performed the deletion"
    )
    deleted_at = models.DateTimeField(auto_now_add=True)
    deletion_reason = models.TextField(blank=True, help_text="Optional reason for deletion")
    
    # Recovery info
    can_be_restored = models.BooleanField(default=True, help_text="Whether this tenant can be restored")
    restored_at = models.DateTimeField(null=True, blank=True, help_text="When restored if applicable")
    restored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='restored_tenants',
        help_text="Admin who restored the tenant"
    )
    
    class Meta:
        ordering = ['-deleted_at']
        verbose_name = 'Archived Tenant'
        verbose_name_plural = 'Archived Tenants'
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['deleted_at']),
            models.Index(fields=['archive_type']),
        ]
    
    def __str__(self):
        name = self.tenant_data.get('full_name', 'Unknown') if self.tenant_data else 'Unknown'
        return f"{name} ({self.archive_type}) - {self.deleted_at.strftime('%Y-%m-%d')}"
    
    @property
    def full_name(self):
        """Get full name from archived data"""
        if self.tenant_data:
            return self.tenant_data.get('full_name', 'Unknown Tenant')
        return 'Unknown Tenant'
    
    @property
    def is_restorable(self):
        """Check if tenant can be restored"""
        return self.can_be_restored and not self.restored_at
    
    def get_summary(self):
        """Get brief summary of archived tenant"""
        return {
            'id': self.id,
            'full_name': self.full_name,
            'email': self.email,
            'archive_type': self.archive_type,
            'deleted_at': self.deleted_at,
            'deleted_by': self.deleted_by.get_full_name() if self.deleted_by else 'System',
            'is_restorable': self.is_restorable,
        }
