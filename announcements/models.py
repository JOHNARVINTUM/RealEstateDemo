from django.conf import settings
from django.db import models


class Announcement(models.Model):
    title = models.CharField(max_length=150)
    body = models.TextField()
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class HomepageBanner(models.Model):
    eyebrow = models.CharField(max_length=80, blank=True, default='Official Update')
    title = models.CharField(max_length=160)
    body = models.TextField()
    button_text = models.CharField(max_length=40, blank=True)
    button_url = models.CharField(max_length=255, blank=True, default='#about')
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_homepage_banners',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_active', '-updated_at', '-created_at']
        verbose_name = 'Homepage banner'
        verbose_name_plural = 'Homepage banners'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_active:
            type(self).objects.exclude(pk=self.pk).filter(is_active=True).update(is_active=False)

    def __str__(self):
        return self.title


class BusinessProfile(models.Model):
    business_name = models.CharField(max_length=160)
    tagline = models.CharField(max_length=220, blank=True)
    about_text = models.TextField()
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=40)
    address = models.CharField(max_length=255)
    inquiry_text = models.TextField()
    is_active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_business_profiles',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_active', '-updated_at', '-created_at']
        verbose_name = 'Business profile'
        verbose_name_plural = 'Business profiles'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_active:
            type(self).objects.exclude(pk=self.pk).filter(is_active=True).update(is_active=False)

    def __str__(self):
        return self.business_name
