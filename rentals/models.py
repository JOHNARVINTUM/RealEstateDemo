from django.conf import settings
from django.db import models

class Unit(models.Model):
    number = models.CharField(max_length=10, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Unit {self.number}"

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


# Create your models here.
