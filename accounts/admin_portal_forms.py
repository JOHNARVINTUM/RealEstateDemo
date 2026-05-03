import logging
from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from rentals.models import TenantProfile, Lease, Unit, UnitImage, TenantAttachment
from announcements.models import Announcement
from billing.models import MonthlyBill

User = get_user_model()
logger = logging.getLogger(__name__)


class TenantProfileForm(forms.ModelForm):
    # Create a new tenant user with profile
    email = forms.EmailField(required=True, label="Email address")
    password1 = forms.CharField(required=True, widget=forms.PasswordInput, label="Password")
    password2 = forms.CharField(required=True, widget=forms.PasswordInput, label="Confirm password")
    
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
        pw1 = cleaned.get("password1")
        pw2 = cleaned.get("password2")

        # Email is required
        if not email:
            raise ValidationError("Email address is required.")

        # Passwords are required and must match
        if not pw1 or not pw2:
            raise ValidationError("Please provide and confirm a password.")
        if pw1 != pw2:
            raise ValidationError("Passwords do not match.")
        
        # Email must be unique
        if User.objects.filter(email=email).exists():
            raise ValidationError({"email": "A user with that email already exists."})

        return cleaned

    def save(self, commit=True, uploaded_by=None):
        # Always create a new user with the provided information
        email = self.cleaned_data.get("email")
        pw = self.cleaned_data.get("password1")
        first_name = self.cleaned_data.get("first_name", "")
        last_name = self.cleaned_data.get("last_name", "")

        # Generate username from first and last name
        if first_name and last_name:
            full_name = f"{first_name} {last_name}"
            username = User.generate_username_from_name(full_name)
        else:
            username = User.generate_username_from_name(email)

        # Create user with generated username
        user = User.objects.create_user(email=email, username=username, password=pw)
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
            
            # Generate welcome notification for the new tenant
            try:
                welcome_message = f"Welcome to our property management system! Your account has been successfully created."
                Notification.create_notification(
                    title="Welcome to RealEstate Portal!",
                    message=welcome_message,
                    notification_type='SYSTEM',
                    related_tenant=instance
                )
            except Exception as e:
                logger.exception("Failed to create welcome notification: %s", e)
        
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
    class Meta:
        model = Lease
        fields = ["tenant", "unit", "due_day", "start_date", "is_active"]
        widgets = {
            # use a text input with a CSS class so JS datepicker (flatpickr) can enhance it
            "start_date": forms.DateInput(attrs={"type": "text", "class": "flatpickr", "autocomplete": "off"}),
        }

    def clean(self):
        cleaned = super().clean()
        unit = cleaned.get("unit")
        
        if unit:
            qs = Lease.objects.filter(unit=unit, is_active=True)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError({"unit": "Selected unit already has an active lease."})
        return cleaned

    def save(self, commit=True):
        # Get the instance without saving yet
        instance = super().save(commit=False)
        
        # Auto-populate monthly rent from unit
        if instance.unit and not instance.monthly_rent:
            instance.monthly_rent = instance.unit.monthly_rent
        
        if commit:
            instance.save()
        return instance

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # only allow selecting users with tenant role
        try:
            self.fields["tenant"].queryset = User.objects.filter(role="TENANT")
        except Exception as e:
            logger.exception("Failed to set tenant queryset: %s", e)
        
        # only allow selecting available units (active units without active leases)
        try:
            # Get units that are active and don't have active leases
            occupied_units = Lease.objects.filter(is_active=True).values_list('unit_id', flat=True)
            self.fields["unit"].queryset = Unit.objects.filter(is_active=True).exclude(id__in=occupied_units)
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