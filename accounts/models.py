from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        TENANT = "TENANT", "Tenant"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.TENANT)
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=150, unique=True)  # keep for Django admin

    REQUIRED_FIELDS = ["username"]
    USERNAME_FIELD = "email"
