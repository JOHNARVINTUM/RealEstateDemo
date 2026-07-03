from django.contrib import admin
from .models import Announcement, HomepageBanner, BusinessProfile


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "is_active", "created_by", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("title", "body")


@admin.register(HomepageBanner)
class HomepageBannerAdmin(admin.ModelAdmin):
    list_display = ("title", "eyebrow", "is_active", "created_by", "updated_at")
    list_filter = ("is_active", "updated_at", "created_at")
    search_fields = ("title", "body", "eyebrow")


@admin.register(BusinessProfile)
class BusinessProfileAdmin(admin.ModelAdmin):
    list_display = ("business_name", "tagline", "is_active", "updated_by", "updated_at")
    list_filter = ("is_active", "updated_at", "created_at")
    search_fields = ("business_name", "tagline", "address", "contact_email")
