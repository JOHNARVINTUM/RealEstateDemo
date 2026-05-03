from django.contrib.auth.models import AbstractUser
from django.db import models
import re

class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        TENANT = "TENANT", "Tenant"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.TENANT)
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=150, unique=True)  # keep for Django admin

    REQUIRED_FIELDS = ["username"]
    USERNAME_FIELD = "email"

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
        # Auto-generate username if not provided and user has tenant profile
        if not self.username and hasattr(self, 'tenantprofile'):
            # Use first_name and last_name from tenant profile
            first_name = getattr(self.tenantprofile, 'first_name', '')
            last_name = getattr(self.tenantprofile, 'last_name', '')
            if first_name and last_name:
                full_name = f"{first_name} {last_name}"
                self.username = self.generate_username_from_name(full_name)
        
        super().save(*args, **kwargs)
