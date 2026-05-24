import logging
from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.db import transaction
from rentals.models import TenantProfile, Lease, Unit, UnitImage, TenantAttachment
from rentals.services import generate_tenant_password, send_tenant_credentials_email
from announcements.models import Announcement
from billing.models import MonthlyBill

User = get_user_model()
logger = logging.getLogger(__name__)


def _ordinal(n):
    """Return ordinal string for an integer: 1->'1st', 2->'2nd', 3->'3rd', etc."""
    n = int(n)
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{['th','st','nd','rd','th'][min(n % 10, 4)]}"


class TenantProfileForm(forms.ModelForm):
    # Create a new tenant user with profile
    email = forms.EmailField(required=True, label="Email address")
    # Password fields removed - passwords will be auto-generated and sent via email
    
    # File upload fields for attachments (optional)
    contract_file = forms.FileField(
        required=False,
        label="Contract Document",
        help_text="Upload contract document (PDF, JPG, PNG - max 10MB)"
    )
    contract_description = forms.CharField(
        required=False,
        max_length=200,
        label="Contract Description",
        help_text="Brief description of the contract"
    )
    valid_id_file = forms.FileField(
        required=False,
        label="Valid ID",
        help_text="Upload valid ID (PDF, JPG, PNG - max 10MB)"
    )
    valid_id_description = forms.CharField(
        required=False,
        max_length=200,
        label="Valid ID Description",
        help_text="Brief description of the ID document"
    )

    class Meta:
        model = TenantProfile
        fields = ["first_name", "last_name", "contact_no"]

    def clean_contract_file(self):
        contract_file = self.cleaned_data.get('contract_file')
        if contract_file:
            # Check file size (max 10MB)
            if contract_file.size > 10 * 1024 * 1024:
                raise ValidationError("Contract file size must be less than 10MB.")
            
            # Check file type
            valid_extensions = ['.pdf', '.jpg', '.jpeg', '.png']
            file_extension = contract_file.name.split('.')[-1].lower()
            if f'.{file_extension}' not in valid_extensions:
                raise ValidationError("Invalid file type. Please upload PDF, JPG, or PNG files.")
        return contract_file
    
    def clean_valid_id_file(self):
        valid_id_file = self.cleaned_data.get('valid_id_file')
        if valid_id_file:
            # Check file size (max 10MB)
            if valid_id_file.size > 10 * 1024 * 1024:
                raise ValidationError("Valid ID file size must be less than 10MB.")
            
            # Check file type
            valid_extensions = ['.pdf', '.jpg', '.jpeg', '.png']
            file_extension = valid_id_file.name.split('.')[-1].lower()
            if f'.{file_extension}' not in valid_extensions:
                raise ValidationError("Invalid file type. Please upload PDF, JPG, or PNG files.")
        return valid_id_file

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("email")

        # Email is required
        if not email:
            raise ValidationError("Email address is required.")
        
        # Email must be unique
        if User.objects.filter(email=email).exists():
            raise ValidationError({"email": "A user with that email already exists."})

        return cleaned

    def save(self, commit=True, uploaded_by=None):
        # Always create a new user with the provided information
        email = self.cleaned_data.get("email")
        first_name = self.cleaned_data.get("first_name", "")
        last_name = self.cleaned_data.get("last_name", "")

        # Generate password based on tenant name
        try:
            generated_password = generate_tenant_password(first_name, last_name)
        except ValueError as e:
            logger.error(f"Password generation failed: {e}")
            # Fallback to secure random password if generation fails
            import secrets
            import string
            generated_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))

        # Generate username from first and last name
        if first_name and last_name:
            full_name = f"{first_name} {last_name}"
            username = User.generate_username_from_name(full_name)
        else:
            username = User.generate_username_from_name(email)

        # Use database transaction to ensure atomicity
        with transaction.atomic():
            # Create user with generated username and password
            user = User.objects.create_user(email=email, username=username, password=generated_password)
            user.role = "TENANT"
            user.save()

            instance = super().save(commit=False)
            instance.user = user
            instance.created_by = uploaded_by
            if commit:
                instance.save()
                
                # Handle file uploads
                contract_file = self.cleaned_data.get('contract_file')
                if contract_file:
                    TenantAttachment.objects.create(
                        tenant=user,
                        attachment_type='CONTRACT',
                        file=contract_file,
                        description=self.cleaned_data.get('contract_description', ''),
                        uploaded_by=uploaded_by
                    )
                
                valid_id_file = self.cleaned_data.get('valid_id_file')
                if valid_id_file:
                    TenantAttachment.objects.create(
                        tenant=user,
                        attachment_type='VALID_ID',
                        file=valid_id_file,
                        description=self.cleaned_data.get('valid_id_description', ''),
                        uploaded_by=uploaded_by
                    )
                
                # Send credentials email to tenant (with edge case handling)
                email_sent = False
                email_valid = True
                
                # Validate email format using Django's email validation
                from django.core.validators import validate_email
                from django.core.exceptions import ValidationError as DjangoValidationError
                
                try:
                    validate_email(email)
                except DjangoValidationError:
                    logger.warning(f"Invalid email format: {email}")
                    email_valid = False
                    email_sent = False
                
                # Send credentials email only if email is valid
                if email_valid:
                    try:
                        email_sent = send_tenant_credentials_email(
                            tenant_email=email,
                            tenant_name=full_name,
                            password=generated_password
                        )
                        if email_sent:
                            logger.info(f"Credentials email sent successfully to {email}")
                        else:
                            logger.warning(f"Failed to send credentials email to {email}")
                    except Exception as e:
                        logger.exception(f"Error sending credentials email to {email}: {e}")
                        email_sent = False
                
                # Create tenant welcome notification with unit details (prevent duplicates)
                unit_details = ""  # Initialize outside try block
                try:
                    # Check if welcome notification already exists for this tenant
                    from rentals.models import Notification
                    existing_notification = Notification.objects.filter(
                        recipient_type='TENANT',
                        user=instance.user,
                        title="Welcome to REALESTATE360+"
                    ).first()
                    
                    if not existing_notification:
                        # Get tenant's lease information if available
                        lease_info = ""
                        try:
                            from rentals.models import Lease
                            lease = Lease.objects.filter(tenant=instance.user, is_active=True).first()
                            if lease:
                                unit_details = f"""
Unit Details:
- Unit Number: {lease.unit.number}
- Unit Type: {lease.unit.get_unit_type_display()}
- Floor Level: {lease.unit.floor_level}
- Size: {lease.unit.size_sqm} sqm
- Monthly Rent: ₱{lease.monthly_rent:,.2f}
- Lease Start Date: {lease.start_date}
"""
                        except Exception as lease_error:
                            logger.warning(f"Could not fetch lease details for tenant notification: {lease_error}")
                        
                        # Create tenant welcome notification
                        welcome_message = f"""Welcome to REALESTATE360+!

Your tenant account has been successfully created.

{unit_details}
You can now access your tenant portal to:
- View your billing statements
- Make payments online
- Request maintenance services
- Access announcements and updates

Monthly Rent Reminder: Your rent is due on the {_ordinal(lease.due_day) if lease else '5th'} of each month.

Please keep your login credentials secure and do not share them with others."""
                        
                        Notification.create_tenant_notification(
                            title="Welcome to REALESTATE360+",
                            message=welcome_message,
                            notification_type='SYSTEM',
                            tenant_user=instance.user,
                            related_unit=lease.unit if lease else None
                        )
                    else:
                        logger.info(f"Welcome notification already exists for tenant {instance.user.email}")
                    
                    # Create admin confirmation notification (prevent duplicates)
                    admin_title = f"New Tenant Added - {instance.first_name} {instance.last_name}"
                    existing_admin_notification = Notification.objects.filter(
                        recipient_type='ADMIN',
                        user=uploaded_by,
                        title=admin_title
                    ).first()
                    
                    if not existing_admin_notification:
                        admin_message = f"""New tenant has been successfully added:

Tenant Name: {instance.first_name} {instance.last_name}
Email: {email}
{unit_details}
Status: Account created and credentials sent

Email notification: {'Sent successfully' if email_sent else 'Failed to send - contact support'}"""
                        
                        Notification.create_admin_notification(
                            title=admin_title,
                            message=admin_message,
                            notification_type='SYSTEM',
                            admin_user=uploaded_by
                        )
                    else:
                        logger.info(f"Admin notification already exists for tenant creation")
                    
                except Exception as e:
                    logger.exception("Failed to create notifications: %s", e)
            
        return instance


class ComprehensiveTenantEditForm(forms.Form):
    """
    Comprehensive form for editing tenant information including user account details
    """
    # User Account Fields
    email = forms.EmailField(
        label="Email Address",
        help_text="User's login email (must be unique)"
    )
    username = forms.CharField(
        label="Username",
        max_length=150,
        help_text="System username (auto-generated from full name if empty)"
    )
    role = forms.ChoiceField(
        label="User Role",
        choices=User.Role.choices,
        help_text="Assign user role (Tenant or Admin)"
    )
    is_active = forms.BooleanField(
        label="Account Active",
        required=False,
        help_text="Enable/disable user account access"
    )
    
    # Password Fields (optional)
    new_password = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput,
        required=False,
        help_text="Leave blank to keep current password"
    )
    confirm_password = forms.CharField(
        label="Confirm New Password",
        widget=forms.PasswordInput,
        required=False,
        help_text="Re-enter new password to confirm"
    )
    
    # Profile Fields
    first_name = forms.CharField(
        label="First Name",
        max_length=60,
        help_text="Tenant's first name"
    )
    last_name = forms.CharField(
        label="Last Name",
        max_length=60,
        help_text="Tenant's last name"
    )
    contact_no = forms.CharField(
        label="Contact Number",
        max_length=30,
        required=False,
        help_text="Phone number for contact"
    )
    
    # File upload fields for attachments (optional)
    contract_file = forms.FileField(
        required=False,
        label="Contract Document",
        help_text="Upload contract document (PDF, JPG, PNG - max 10MB)"
    )
    contract_description = forms.CharField(
        required=False,
        max_length=200,
        label="Contract Description",
        help_text="Brief description of the contract"
    )
    valid_id_file = forms.FileField(
        required=False,
        label="Valid ID",
        help_text="Upload valid ID (PDF, JPG, PNG - max 10MB)"
    )
    valid_id_description = forms.CharField(
        required=False,
        max_length=200,
        label="Valid ID Description",
        help_text="Brief description of the ID document"
    )
    
    def __init__(self, tenant_profile, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant_profile = tenant_profile
        self.user = tenant_profile.user
        
        # Pre-populate form with existing data
        self.fields['email'].initial = self.user.email
        self.fields['username'].initial = self.user.username
        self.fields['role'].initial = self.user.role
        self.fields['is_active'].initial = self.user.is_active
        self.fields['first_name'].initial = tenant_profile.first_name
        self.fields['last_name'].initial = tenant_profile.last_name
        self.fields['contact_no'].initial = tenant_profile.contact_no
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.exclude(pk=self.user.pk).filter(email=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email
    
    def clean_username(self):
        username = self.cleaned_data.get('username')
        if not username:
            # Auto-generate from first and last name if empty
            first_name = self.cleaned_data.get('first_name', '')
            last_name = self.cleaned_data.get('last_name', '')
            if first_name and last_name:
                full_name = f"{first_name} {last_name}"
                username = User.generate_username_from_name(full_name)
        
        if User.objects.exclude(pk=self.user.pk).filter(username=username).exists():
            raise forms.ValidationError("A user with this username already exists.")
        return username
    
    def clean_contract_file(self):
        contract_file = self.cleaned_data.get('contract_file')
        if contract_file:
            # Check file size (max 10MB)
            if contract_file.size > 10 * 1024 * 1024:
                raise ValidationError("Contract file size must be less than 10MB.")
            
            # Check file type
            valid_extensions = ['.pdf', '.jpg', '.jpeg', '.png']
            file_extension = contract_file.name.split('.')[-1].lower()
            if f'.{file_extension}' not in valid_extensions:
                raise ValidationError("Invalid file type. Please upload PDF, JPG, or PNG files.")
        return contract_file
    
    def clean_valid_id_file(self):
        valid_id_file = self.cleaned_data.get('valid_id_file')
        if valid_id_file:
            # Check file size (max 10MB)
            if valid_id_file.size > 10 * 1024 * 1024:
                raise ValidationError("Valid ID file size must be less than 10MB.")
            
            # Check file type
            valid_extensions = ['.pdf', '.jpg', '.jpeg', '.png']
            file_extension = valid_id_file.name.split('.')[-1].lower()
            if f'.{file_extension}' not in valid_extensions:
                raise ValidationError("Invalid file type. Please upload PDF, JPG, or PNG files.")
        return valid_id_file

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')
        
        if new_password and new_password != confirm_password:
            raise forms.ValidationError("New passwords do not match.")
        
        return cleaned_data
    
    def save(self, uploaded_by=None):
        # Update User model
        self.user.email = self.cleaned_data['email']
        self.user.username = self.cleaned_data['username']
        self.user.role = self.cleaned_data['role']
        self.user.is_active = self.cleaned_data['is_active']
        
        # Update password if provided
        new_password = self.cleaned_data.get('new_password')
        if new_password:
            self.user.set_password(new_password)
        
        self.user.save()
        
        # Update TenantProfile
        self.tenant_profile.first_name = self.cleaned_data['first_name']
        self.tenant_profile.last_name = self.cleaned_data['last_name']
        self.tenant_profile.contact_no = self.cleaned_data['contact_no']
        self.tenant_profile.save()
        
        # Handle file uploads
        contract_file = self.cleaned_data.get('contract_file')
        if contract_file:
            TenantAttachment.objects.create(
                tenant=self.user,
                attachment_type='CONTRACT',
                file=contract_file,
                description=self.cleaned_data.get('contract_description', ''),
                uploaded_by=uploaded_by
            )
        
        valid_id_file = self.cleaned_data.get('valid_id_file')
        if valid_id_file:
            TenantAttachment.objects.create(
                tenant=self.user,
                attachment_type='VALID_ID',
                file=valid_id_file,
                description=self.cleaned_data.get('valid_id_description', ''),
                uploaded_by=uploaded_by
            )
        
        return self.tenant_profile


class TenantProfileEditForm(forms.ModelForm):
    class Meta:
        model = TenantProfile
        fields = ["first_name", "last_name", "contact_no"]


class LeaseForm(forms.ModelForm):
    # Additional fields for payment calculations
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "text", "class": "flatpickr", "autocomplete": "off"}),
        help_text="Lease end date (optional)"
    )
    
    # Move-in payment fields (not saved to Lease model)
    move_in_payment_method = forms.ChoiceField(
        choices=[("GCASH", "GCash QR"), ("CASH", "Cash")],
        initial="GCASH",
        widget=forms.RadioSelect,
        label="Move-in Payment Method",
    )
    move_in_reference_code = forms.CharField(
        max_length=80,
        required=False,
        label="Reference / Receipt No.",
        widget=forms.TextInput(attrs={"placeholder": "e.g. REF-1023456789012"}),
    )
    
    class Meta:
        model = Lease
        fields = ["tenant", "unit", "monthly_rent", "due_day", "start_date", "end_date", "security_deposit", "deposit_multiplier", "is_active", "motorcycle_slots", "car_slots"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "text", "class": "flatpickr", "autocomplete": "off"}),
            "end_date": forms.DateInput(attrs={"type": "text", "class": "flatpickr", "autocomplete": "off"}),
            "monthly_rent": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "security_deposit": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "deposit_multiplier": forms.NumberInput(attrs={"min": "1", "max": "12"}),
        }

    def clean(self):
        cleaned = super().clean()
        unit = cleaned.get("unit")
        start_date = cleaned.get("start_date")
        end_date = cleaned.get("end_date")
        monthly_rent = cleaned.get("monthly_rent")
        security_deposit = cleaned.get("security_deposit")
        deposit_multiplier = cleaned.get("deposit_multiplier")
        
        # Validate unit availability
        if unit:
            qs = Lease.objects.filter(unit=unit, is_active=True)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError({"unit": "Selected unit already has an active lease."})
        
        # Validate date logic
        if start_date and end_date:
            if start_date > end_date:
                raise ValidationError({"end_date": "End date must be after start date."})
        
        # Validate payment fields
        if monthly_rent and monthly_rent <= 0:
            raise ValidationError({"monthly_rent": "Monthly rent must be greater than 0."})
        
        if security_deposit and security_deposit < 0:
            raise ValidationError({"security_deposit": "Security deposit cannot be negative."})
        
        if deposit_multiplier is not None and (deposit_multiplier < 1 or deposit_multiplier > 12):
            raise ValidationError({"deposit_multiplier": "Contract deposit multiplier must be between 1 and 12."})
        
        # Validate move-in payment
        payment_method = cleaned.get("move_in_payment_method")
        reference_code = cleaned.get("move_in_reference_code", "").strip()
        if payment_method == "GCASH" and not reference_code:
            raise ValidationError({"move_in_reference_code": "GCash reference number is required."})
        
        return cleaned

    def save(self, commit=True):
        # Get the instance without saving yet
        instance = super().save(commit=False)
        
        # Auto-populate monthly rent from unit if not provided
        if instance.unit and not instance.monthly_rent:
            instance.monthly_rent = instance.unit.monthly_rent
        
        # Auto-populate security deposit if not provided
        if not instance.security_deposit and instance.monthly_rent:
            instance.security_deposit = instance.monthly_rent * instance.deposit_multiplier
        
        # Set smart status based on start date
        from django.utils import timezone
        if instance.start_date <= timezone.now().date():
            instance.is_active = True
        else:
            instance.is_active = False
        
        if commit:
            instance.save()
            # Generate calendar events after lease is saved
            self._generate_calendar_events(instance)
        
        return instance
    
    def _generate_calendar_events(self, lease):
        """Generate calendar events for the lease"""
        from rentals.services import LeaseSchedulingService
        
        try:
            service = LeaseSchedulingService()
            service.generate_lease_events(lease)
        except Exception as e:
            logger.error(f"Failed to generate calendar events for lease {lease.id}: {e}")
    
    def get_payment_summary(self):
        """Get payment summary for preview"""
        cleaned_data = getattr(self, 'cleaned_data', {})
        if not cleaned_data:
            return None
        
        monthly_rent = cleaned_data.get('monthly_rent', 0)
        advance_months = cleaned_data.get('advance_months', 2)
        security_deposit = cleaned_data.get('security_deposit', monthly_rent)
        
        advance_payment_amount = monthly_rent * advance_months
        total_move_in_cost = security_deposit + advance_payment_amount
        
        return {
            'monthly_rent': monthly_rent,
            'advance_months': advance_months,
            'advance_payment_amount': advance_payment_amount,
            'security_deposit': security_deposit,
            'total_move_in_cost': total_move_in_cost
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # only allow selecting users with tenant role
        try:
            self.fields["tenant"].queryset = User.objects.filter(role="TENANT")
        except Exception as e:
            logger.exception("Failed to set tenant queryset: %s", e)
        
        # only allow selecting available units (active, not under maintenance, without active leases)
        try:
            # Get units that are active, not under maintenance, and don't have active leases
            occupied_units = Lease.objects.filter(is_active=True).values_list('unit_id', flat=True)
            self.fields["unit"].queryset = Unit.objects.filter(
                is_active=True,
                status__in=['AVAILABLE', 'OCCUPIED']  # Exclude MAINTENANCE/Being Fixed units
            ).exclude(id__in=occupied_units)
        except Exception as e:
            logger.exception("Failed to set unit queryset: %s", e)


class UnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        fields = [
            "number", 
            "unit_type", 
            "floor_level", 
            "size_sqm", 
            "monthly_rent", 
            "status", 
            "is_active", 
            "description", 
            "amenities"
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Describe the unit features, layout, and highlights'}),
            'amenities': forms.Textarea(attrs={'rows': 2, 'placeholder': 'List amenities separated by commas (e.g., Air Conditioning, WiFi, Parking)'}),
        }


class UnitImageForm(forms.ModelForm):
    class Meta:
        model = UnitImage
        fields = ["image", "caption", "is_primary", "order"]
        widgets = {
            'caption': forms.TextInput(attrs={'placeholder': 'Add a caption for this image (optional)'}),
            'order': forms.NumberInput(attrs={'min': 0, 'max': 4, 'placeholder': 'Display order (0-4)'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['image'].widget.attrs.update({
            'accept': 'image/*',
            'class': 'form-control'
        })
        
    def clean_image(self):
        image = self.cleaned_data.get('image')
        if image:
            # Check file size (max 5MB)
            if image.size > 5 * 1024 * 1024:
                raise ValidationError("Image file size must be less than 5MB.")
            
            # Check file type
            valid_extensions = ['jpg', 'jpeg', 'png', 'gif', 'webp']
            file_extension = image.name.split('.')[-1].lower()
            if file_extension not in valid_extensions:
                raise ValidationError("Invalid file type. Please upload JPG, PNG, GIF, or WebP images.")
        
        return image


class UnitImageFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        
        # Check maximum of 5 images
        total_forms = sum(1 for form in self.forms if form.cleaned_data and not form.cleaned_data.get('DELETE'))
        if total_forms > 5:
            raise ValidationError("You can upload a maximum of 5 images per unit.")
        
        # Check for primary image selection
        primary_count = sum(1 for form in self.forms if form.cleaned_data and form.cleaned_data.get('is_primary') and not form.cleaned_data.get('DELETE'))
        if primary_count > 1:
            raise ValidationError("Only one image can be set as primary/featured.")


UnitImageFormSet = forms.inlineformset_factory(
    Unit, 
    UnitImage, 
    form=UnitImageForm,
    formset=UnitImageFormSet,
    extra=5,  # Allow up to 5 images
    max_num=5,
    can_delete=True
)


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ["title", "body", "is_active"]

    def save(self, commit=True, user=None):
        instance = super().save(commit=False)
        if user:
            instance.created_by = user
        if commit:
            instance.save()
        return instance


class MonthlyBillForm(forms.ModelForm):
    class Meta:
        model = MonthlyBill
        fields = [
            "lease",
            "billing_month",
            "due_date",
            "base_rent",
            "water_amount",
            "interest",
            "total_due",
            "status",
            "paid_at",
            "payment_reference",
        ]