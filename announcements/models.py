from django.conf import settings
from django.db import models

from rentals.models import get_supabase_storage


def landing_hero_upload_path(instance, filename):
    return f"landing/content/hero/{filename}"


def landing_about_upload_path(instance, filename):
    return f"landing/content/about/{filename}"


def landing_service_1_upload_path(instance, filename):
    return f"landing/content/services/service-1/{filename}"


def landing_service_2_upload_path(instance, filename):
    return f"landing/content/services/service-2/{filename}"


def landing_service_3_upload_path(instance, filename):
    return f"landing/content/services/service-3/{filename}"


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
    hero_title = models.CharField(max_length=220, blank=True)
    hero_description = models.TextField(blank=True)
    hero_subtitle = models.CharField(max_length=220, blank=True)
    hero_button_text = models.CharField(max_length=80, blank=True)
    hero_button_url = models.CharField(max_length=255, blank=True, default='#about')
    hero_image = models.ImageField(
        upload_to=landing_hero_upload_path,
        storage=get_supabase_storage(),
        blank=True,
        null=True,
    )
    about_title = models.CharField(max_length=220, blank=True)
    about_description = models.TextField(blank=True)
    about_image = models.ImageField(
        upload_to=landing_about_upload_path,
        storage=get_supabase_storage(),
        blank=True,
        null=True,
    )
    services_title = models.CharField(max_length=220, blank=True)
    services_description = models.TextField(blank=True)
    service_1_title = models.CharField(max_length=180, blank=True)
    service_1_description = models.TextField(blank=True)
    service_1_image = models.ImageField(
        upload_to=landing_service_1_upload_path,
        storage=get_supabase_storage(),
        blank=True,
        null=True,
    )
    service_2_title = models.CharField(max_length=180, blank=True)
    service_2_description = models.TextField(blank=True)
    service_2_image = models.ImageField(
        upload_to=landing_service_2_upload_path,
        storage=get_supabase_storage(),
        blank=True,
        null=True,
    )
    service_3_title = models.CharField(max_length=180, blank=True)
    service_3_description = models.TextField(blank=True)
    service_3_image = models.ImageField(
        upload_to=landing_service_3_upload_path,
        storage=get_supabase_storage(),
        blank=True,
        null=True,
    )
    contact_title = models.CharField(max_length=220, blank=True)
    contact_description = models.TextField(blank=True)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=40)
    address = models.CharField(max_length=255)
    inquiry_text = models.TextField()
    footer_text = models.TextField(blank=True)
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

    @property
    def hero_image_url(self):
        if not self.hero_image:
            return ''
        try:
            return self.hero_image.url
        except Exception:
            return ''

    @property
    def about_image_url(self):
        if not self.about_image:
            return ''
        try:
            return self.about_image.url
        except Exception:
            return ''

    @property
    def service_1_image_url(self):
        if not self.service_1_image:
            return ''
        try:
            return self.service_1_image.url
        except Exception:
            return ''

    @property
    def service_2_image_url(self):
        if not self.service_2_image:
            return ''
        try:
            return self.service_2_image.url
        except Exception:
            return ''

    @property
    def service_3_image_url(self):
        if not self.service_3_image:
            return ''
        try:
            return self.service_3_image.url
        except Exception:
            return ''


class LandingPageSection(models.Model):
    SECTION_HERO = 'hero'
    SECTION_ABOUT = 'about'
    SECTION_SERVICES = 'services'
    SECTION_CONTACT = 'contact'
    SECTION_FOOTER = 'footer'

    SECTION_KEY_CHOICES = [
        (SECTION_HERO, 'Hero'),
        (SECTION_ABOUT, 'About'),
        (SECTION_SERVICES, 'Services'),
        (SECTION_CONTACT, 'Contact'),
        (SECTION_FOOTER, 'Footer'),
    ]

    section_key = models.CharField(max_length=40, unique=True, choices=SECTION_KEY_CHOICES)
    title = models.CharField(max_length=180, blank=True)
    subtitle = models.CharField(max_length=220, blank=True)
    body_text = models.TextField(blank=True)
    image = models.ImageField(
        upload_to='landing/sections/',
        storage=get_supabase_storage(),
        blank=True,
        null=True,
    )
    button_text = models.CharField(max_length=60, blank=True)
    button_url = models.CharField(max_length=255, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_landing_page_sections',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'section_key']
        verbose_name = 'Landing page section'
        verbose_name_plural = 'Landing page sections'

    def __str__(self):
        return self.get_section_key_display()

    @property
    def image_url(self):
        if not self.image:
            return ''
        try:
            return self.image.url
        except Exception:
            return ''


class LandingPageFeature(models.Model):
    title = models.CharField(max_length=140)
    description = models.TextField()
    image = models.ImageField(
        upload_to='landing/features/',
        storage=get_supabase_storage(),
        blank=True,
        null=True,
    )
    icon_label = models.CharField(max_length=40, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_landing_page_features',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'title']
        verbose_name = 'Landing page feature'
        verbose_name_plural = 'Landing page features'

    def __str__(self):
        return self.title

    @property
    def image_url(self):
        if not self.image:
            return ''
        try:
            return self.image.url
        except Exception:
            return ''
