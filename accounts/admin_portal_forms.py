import logging
import re
from io import BytesIO
from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.db import transaction
from PIL import Image, UnidentifiedImageError
from rentals.models import TenantProfile, Lease, Unit, UnitImage, TenantAttachment, validate_tenant_attachment_upload
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


_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]*$")
_CONTACT_ALLOWED_RE = re.compile(r"^[0-9+()\-\s]+$")


def _clean_person_name(value: str, *, label: str) -> str:
    value = (value or "").strip()
    if not value:
        raise forms.ValidationError(f"{label} is required.")
    if not _NAME_RE.fullmatch(value):
        raise forms.ValidationError(
            f"{label} may contain letters, spaces, periods, apostrophes, and hyphens only."
        )
    if not re.search(r"[A-Za-z]", value):
        raise forms.ValidationError(f"{label} must contain at least one letter.")
    return re.sub(r"\s+", " ", value)



def _clean_contact_number(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if not _CONTACT_ALLOWED_RE.fullmatch(value):
        raise forms.ValidationError(
            "Contact number may contain digits, spaces, plus sign, parentheses, and hyphens only."
        )
    digits_only = re.sub(r"\D", "", value)
    if len(digits_only) < 7 or len(digits_only) > 15:
        raise forms.ValidationError("Contact number must contain between 7 and 15 digits.")
    return value


class TenantProfileForm(forms.ModelForm):
    # Create a new tenant user with profile
    email = forms.EmailField(required=True, label="Email address")
    # Password fields removed - passwords will be auto-generated and sent via email
    
    # File upload fields for attachments (optional)
    contract_file = forms.FileField(
        required=False,
        label="Contract Document",
        help_text="Accepted formats: PDF contracts, PNG, JPG/JPEG, HEIC/HEIF iPhone photos. Max 10MB."
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
        help_text="Accepted formats: PNG, JPG/JPEG, HEIC/HEIF iPhone photos, or PDF. Max 10MB."
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

    def clean_first_name(self):
        return _clean_person_name(self.cleaned_data.get("first_name"), label="First name")

    def clean_last_name(self):
        return _clean_person_name(self.cleaned_data.get("last_name"), label="Last name")

    def clean_contact_no(self):
        return _clean_contact_number(self.cleaned_data.get("contact_no"))

    def clean_contract_file(self):
        contract_file = self.cleaned_data.get('contract_file')
        return validate_tenant_attachment_upload(contract_file, label="Contract file")
    
    def clean_valid_id_file(self):
        valid_id_file = self.cleaned_data.get('valid_id_file')
        return validate_tenant_attachment_upload(valid_id_file, label="Valid ID file")

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("email")

        # Email is required
        if not email:
            raise ValidationError("Email address is required.")

        try:
            cleaned["email"] = User.validate_email_constraints(email)
        except ValidationError as exc:
            raise ValidationError({"email": exc.message_dict.get("email", exc.messages)})

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
                
                unit_details = ""
                try:
                    from rentals.models import Notification
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
Status: Account created; credentials email is sent immediately

Email notification: Sent during tenant creation"""
                        
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

        tenant_name = f"{first_name} {last_name}".strip() or email
        email_sent = send_tenant_credentials_email(
            tenant_email=email,
            tenant_name=tenant_name,
            password=generated_password,
        )
        instance.credentials_email_sent = email_sent

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
        help_text="Accepted formats: PDF contracts, PNG, JPG/JPEG, HEIC/HEIF iPhone photos. Max 10MB."
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
        help_text="Accepted formats: PNG, JPG/JPEG, HEIC/HEIF iPhone photos, or PDF. Max 10MB."
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
        try:
            return User.validate_email_constraints(email, exclude_pk=self.user.pk)
        except ValidationError as exc:
            raise forms.ValidationError(exc.message_dict.get("email", exc.messages))
    
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

    def clean_first_name(self):
        return _clean_person_name(self.cleaned_data.get("first_name"), label="First name")

    def clean_last_name(self):
        return _clean_person_name(self.cleaned_data.get("last_name"), label="Last name")

    def clean_contact_no(self):
        return _clean_contact_number(self.cleaned_data.get("contact_no"))
    
    def clean_contract_file(self):
        contract_file = self.cleaned_data.get('contract_file')
        return validate_tenant_attachment_upload(contract_file, label="Contract file")
    
    def clean_valid_id_file(self):
        valid_id_file = self.cleaned_data.get('valid_id_file')
        return validate_tenant_attachment_upload(valid_id_file, label="Valid ID file")

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

    def clean_first_name(self):
        return _clean_person_name(self.cleaned_data.get("first_name"), label="First name")

    def clean_last_name(self):
        return _clean_person_name(self.cleaned_data.get("last_name"), label="Last name")

    def clean_contact_no(self):
        return _clean_contact_number(self.cleaned_data.get("contact_no"))


class LeaseForm(forms.ModelForm):
    # Additional fields for payment calculations
    end_date = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={"type": "text", "class": "flatpickr", "autocomplete": "off"}),
        help_text="Lease end date"
    )
    
    class Meta:
        model = Lease
        fields = ["tenant", "unit", "monthly_rent", "due_day", "start_date", "end_date", "security_deposit", "motorcycle_slots", "car_slots"]
        # Note: is_active removed - status field now controls activation
        # Note: deposit_multiplier removed - security deposit is now fixed at 2x monthly rent
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "text", "class": "flatpickr", "autocomplete": "off"}),
            "end_date": forms.DateInput(attrs={"type": "text", "class": "flatpickr", "autocomplete": "off"}),
            "monthly_rent": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "security_deposit": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    def _get_locked_security_deposit(self):
        if not (self.instance and self.instance.pk):
            return self.instance.security_deposit

        if (
            self.instance.deposit_multiplier == 2
            and self.instance.monthly_rent
            and self.instance.security_deposit == self.instance.monthly_rent
        ):
            return self.instance.monthly_rent * 2
        return self.instance.security_deposit

    def clean(self):
        cleaned = super().clean()
        unit = cleaned.get("unit")
        start_date = cleaned.get("start_date")
        due_day = cleaned.get("due_day")
        end_date = cleaned.get("end_date")
        monthly_rent = cleaned.get("monthly_rent")
        security_deposit = cleaned.get("security_deposit")
        
        # Validate unit availability
        tenant = cleaned.get("tenant")
        if unit:
            from django.utils import timezone as tz
            from django.db.models import Q
            _today = tz.localdate()
            if unit.status == "MAINTENANCE" and not (
                self.instance and self.instance.pk and self.instance.unit_id == unit.id
            ):
                raise ValidationError({"unit": "Selected unit is not available for a new lease."})
            qs = Lease.objects.filter(
                unit=unit,
                status__in=[Lease.STATUS_ACTIVE, Lease.STATUS_PENDING_PAYMENT],
            )
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError({"unit": "Selected unit already has an active or pending lease."})
            # Prevent duplicate lease for same tenant + same unit
            if tenant:
                dup_qs = Lease.objects.filter(
                    tenant=tenant,
                    unit=unit,
                    status__in=[Lease.STATUS_ACTIVE, Lease.STATUS_PENDING_PAYMENT],
                )
                if self.instance and self.instance.pk:
                    dup_qs = dup_qs.exclude(pk=self.instance.pk)
                if dup_qs.exists():
                    raise ValidationError({"unit": f"This tenant already has an active or upcoming lease for Unit {unit.number}."})
        
        # Validate date logic
        if start_date and not end_date:
            raise ValidationError({"end_date": "End date is required."})

        if start_date and end_date:
            if start_date > end_date:
                raise ValidationError({"end_date": "End date must be after start date."})
            if end_date.day != start_date.day:
                raise ValidationError({"end_date": "End date must use the same day as the move-in date."})

        # Payment due day follows the tenant move-in date.
        if start_date:
            cleaned["due_day"] = start_date.day
        elif due_day and (due_day < 1 or due_day > 31):
            raise ValidationError({"due_day": "Payment due day must be between 1 and 31."})
        
        # Validate payment fields
        if monthly_rent and monthly_rent <= 0:
            raise ValidationError({"monthly_rent": "Monthly rent must be greater than 0."})
        
        if security_deposit and security_deposit < 0:
            raise ValidationError({"security_deposit": "Security deposit cannot be negative."})
        
        # Note: deposit_multiplier validation removed - using fixed 2x multiplier
        # Note: move-in payment validation removed - payment now happens on separate page
        
        return cleaned

    def save(self, commit=True):
        # Get the instance without saving yet
        instance = super().save(commit=False)
        is_existing_lease = bool(instance.pk)
        original_tenant = self.instance.tenant if is_existing_lease else None
        original_unit = self.instance.unit if is_existing_lease else None
        original_status = self.instance.status if is_existing_lease else None
        original_is_active = self.instance.is_active if is_existing_lease else None
        original_activated_at = self.instance.activated_at if is_existing_lease else None
        original_security_deposit = self._get_locked_security_deposit() if is_existing_lease else None
        
        # Auto-populate monthly rent from unit if not provided
        if instance.unit and not instance.monthly_rent:
            instance.monthly_rent = instance.unit.monthly_rent

        if instance.start_date:
            instance.due_day = instance.start_date.day
        
        # Auto-populate security deposit = monthly_rent × 2 only on create.
        if is_existing_lease:
            instance.tenant = original_tenant
            instance.unit = original_unit
            instance.security_deposit = original_security_deposit
        elif not instance.security_deposit and instance.monthly_rent:
            instance.security_deposit = instance.monthly_rent * 2
        
        # Ensure deposit_multiplier is always 2 for consistency
        instance.deposit_multiplier = 2
        
        # Preserve existing lease lifecycle state on edit.
        if is_existing_lease:
            instance.status = original_status
            instance.is_active = original_is_active
            instance.activated_at = original_activated_at
        else:
            # New leases stay pending until move-in payment succeeds.
            instance.status = Lease.STATUS_PENDING_PAYMENT
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
        # Only tenants without active or pending leases can be assigned a new lease.
        try:
            unavailable_tenant_ids = Lease.objects.filter(
                status__in=[Lease.STATUS_ACTIVE, Lease.STATUS_PENDING_PAYMENT]
            ).values_list("tenant_id", flat=True)
            tenant_queryset = User.objects.filter(role="TENANT").exclude(id__in=unavailable_tenant_ids)
            if self.instance and self.instance.pk and self.instance.tenant_id:
                tenant_queryset = (
                    tenant_queryset | User.objects.filter(pk=self.instance.tenant_id)
                ).distinct()
            self.fields["tenant"].queryset = tenant_queryset.select_related("tenantprofile").order_by(
                "tenantprofile__first_name",
                "tenantprofile__last_name",
                "email",
            )
        except Exception as e:
            logger.exception("Failed to set tenant queryset: %s", e)
        
        # Available means no active lease. Some historical rooms still have
        # status=OCCUPIED even after their lease was cleared, so do not rely on
        # Unit.status alone for lease assignment.
        try:
            occupied_units = Lease.objects.filter(is_active=True).values_list('unit_id', flat=True)
            unit_queryset = Unit.objects.filter(
                is_active=True,
            ).exclude(
                id__in=occupied_units
            ).exclude(
                status='MAINTENANCE'
            )
            if self.instance and self.instance.pk and self.instance.unit_id:
                unit_queryset = (unit_queryset | Unit.objects.filter(pk=self.instance.unit_id)).distinct()
            self.fields["unit"].queryset = unit_queryset.order_by('floor_level', 'number')
        except Exception as e:
            logger.exception("Failed to set unit queryset: %s", e)

        if self.instance and self.instance.pk:
            locked_security_deposit = self._get_locked_security_deposit()
            self.initial["tenant"] = self.instance.tenant_id
            self.initial["unit"] = self.instance.unit_id
            self.initial["start_date"] = self.instance.start_date
            self.initial["end_date"] = self.instance.end_date
            self.initial["due_day"] = self.instance.start_date.day
            self.initial["security_deposit"] = locked_security_deposit
            self.fields["tenant"].initial = self.instance.tenant_id
            self.fields["unit"].initial = self.instance.unit_id
            self.fields["start_date"].initial = self.instance.start_date
            self.fields["end_date"].initial = self.instance.end_date
            self.fields["due_day"].initial = self.instance.start_date.day
            self.fields["security_deposit"].initial = locked_security_deposit
            self.fields["tenant"].widget.attrs["disabled"] = "disabled"
            self.fields["unit"].widget.attrs["disabled"] = "disabled"
            self.fields["security_deposit"].widget.attrs["readonly"] = "readonly"

        self.fields["due_day"].widget.attrs["readonly"] = "readonly"


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            choice for choice in self.fields["status"].choices
            if choice[0] != "RESERVED"
        ]
        self.fields["unit_type"].choices = [
            ("1BR", "1 Bedroom"),
            ("2BR", "2 Bedrooms"),
        ]
        current_unit_type = (getattr(self.instance, "unit_type", "") or "").strip().upper()
        if current_unit_type == "STUDIO":
            self.initial["unit_type"] = "1BR"
        elif current_unit_type and current_unit_type != "1BR":
            self.initial["unit_type"] = "2BR"

    def clean_unit_type(self):
        value = (self.cleaned_data.get("unit_type") or "").strip().upper()
        if value == "STUDIO":
            return "1BR"
        if value not in {"1BR", "2BR"}:
            return "2BR"
        return value


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

            header = image.read(8192)
            image.seek(0)
            try:
                Image.open(BytesIO(header)).verify()
            except (UnidentifiedImageError, OSError):
                raise ValidationError("Invalid image file. Please upload a real image.")
        
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
