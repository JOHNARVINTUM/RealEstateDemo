from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.exceptions import ValidationError
import re


def normalize_email_address(email: str) -> str:
    return (email or "").strip().lower()


def canonical_email_address(email: str) -> str:
    normalized = normalize_email_address(email)
    if "@" not in normalized:
        return normalized
    local_part, domain = normalized.split("@", 1)
    if domain in {"gmail.com", "googlemail.com"}:
        local_part = local_part.split("+", 1)[0]
    return f"{local_part}@{domain}"


def gmail_plus_alias_used(email: str) -> bool:
    normalized = normalize_email_address(email)
    if "@" not in normalized:
        return False
    local_part, domain = normalized.split("@", 1)
    return domain in {"gmail.com", "googlemail.com"} and "+" in local_part


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        STAFF = "STAFF", "Staff"
        TENANT = "TENANT", "Tenant"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.TENANT)
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=150, unique=True)  # keep for Django admin

    REQUIRED_FIELDS = ["username"]
    USERNAME_FIELD = "email"

    @classmethod
    def normalize_email_address(cls, email):
        return normalize_email_address(email)

    @classmethod
    def canonical_email_address(cls, email):
        return canonical_email_address(email)

    @classmethod
    def validate_email_constraints(cls, email, *, exclude_pk=None):
        normalized = cls.normalize_email_address(email)

        if not normalized:
            return normalized

        if gmail_plus_alias_used(normalized):
            raise ValidationError({
                "email": "Please use the main Gmail address without a '+' alias."
            })

        canonical = cls.canonical_email_address(normalized)
        for existing in cls.objects.exclude(pk=exclude_pk).only("id", "email"):
            if cls.canonical_email_address(existing.email) == canonical:
                raise ValidationError({
                    "email": "A user with this email already exists."
                })

        return normalized

    @classmethod
    def generate_username_from_name(cls, full_name):
        """
        Generate username from full name.
        Example: "John Doe Swanson" -> "JDSwanson"
        """
        # Remove extra spaces and split name
        name_parts = [part.strip() for part in full_name.split() if part.strip()]
        
        if not name_parts:
            return "User"
        
        # Take first letter of each part except last part
        initials = ''.join([part[0].upper() for part in name_parts[:-1]])
        
        # Combine with last part (capitalize first letter)
        last_part = name_parts[-1].capitalize()
        
        username = f"{initials}{last_part}"
        
        # Ensure username is valid (remove special characters)
        username = re.sub(r'[^a-zA-Z0-9]', '', username)
        
        # Check if username exists, add number if needed
        base_username = username
        counter = 1
        while cls.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1
        
        return username

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.validate_email_constraints(self.email, exclude_pk=self.pk)

        # Auto-generate username if not provided and user has tenant profile
        if not self.username and hasattr(self, 'tenantprofile'):
            # Use first_name and last_name from tenant profile
            first_name = getattr(self.tenantprofile, 'first_name', '')
            last_name = getattr(self.tenantprofile, 'last_name', '')
            if first_name and last_name:
                full_name = f"{first_name} {last_name}"
                self.username = self.generate_username_from_name(full_name)
        
        super().save(*args, **kwargs)
