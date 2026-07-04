from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import HomepageBanner, BusinessProfile


User = get_user_model()


class HomepageBannerCmsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admincms',
            email='admincms@example.com',
            password='StrongPass123!',
            role='ADMIN',
        )
        self.staff = User.objects.create_user(
            username='staffcms',
            email='staffcms@example.com',
            password='StrongPass123!',
            role='STAFF',
        )

    def test_admin_can_open_landing_page_editor_preview(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_business_profile'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Landing Page Editor')
        self.assertContains(response, 'Edit Hero')

    def test_legacy_banner_management_redirects_to_editor(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_homepage_banners'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin_business_profile'))

    def test_staff_cannot_open_banner_management_page(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('admin_homepage_banners'))
        self.assertEqual(response.status_code, 302)

    def test_staff_cannot_open_business_profile_page(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('admin_business_profile'))
        self.assertEqual(response.status_code, 302)

    def test_active_banner_renders_on_public_landing_page(self):
        HomepageBanner.objects.create(
            eyebrow='Official Update',
            title='Now accepting July inquiries',
            body='A focused landing-page message for visitors.',
            button_text='Explore',
            button_url='#about',
            is_active=True,
            created_by=self.admin,
        )
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Now accepting July inquiries')
        self.assertContains(response, 'Official Update')

    def test_active_business_profile_renders_on_public_landing_page(self):
        BusinessProfile.objects.create(
            business_name='Demo Property Group',
            tagline='Smart Leasing For Growing Portfolios',
            about_text='Legacy about text',
            hero_description='A scalable leasing platform for multiple properties.',
            contact_email='hello@example.com',
            contact_phone='09170000000',
            address='Mandaluyong City',
            inquiry_text='Contact our team for new property inquiries.',
            is_active=True,
            updated_by=self.admin,
        )
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Demo Property Group')
        self.assertContains(response, 'Smart Leasing For Growing Portfolios')
        self.assertContains(response, 'hello@example.com')
        self.assertContains(response, 'A scalable leasing platform for multiple properties.')

    def test_public_landing_uses_default_hero_paragraph_when_hero_description_is_blank(self):
        BusinessProfile.objects.create(
            business_name='Fallback Property',
            tagline='Fallback Tagline',
            about_text='Legacy about fallback text',
            hero_description='',
            contact_email='fallback@example.com',
            contact_phone='09170000003',
            address='Fallback Address',
            inquiry_text='Fallback inquiry text',
            is_active=True,
            updated_by=self.admin,
        )
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A masterclass in modern living.')

    def test_only_latest_active_banner_stays_active(self):
        first = HomepageBanner.objects.create(
            eyebrow='First',
            title='First Banner',
            body='First body',
            is_active=True,
            created_by=self.admin,
        )
        second = HomepageBanner.objects.create(
            eyebrow='Second',
            title='Second Banner',
            body='Second body',
            is_active=True,
            created_by=self.admin,
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertTrue(second.is_active)

    def test_only_latest_active_business_profile_stays_active(self):
        first = BusinessProfile.objects.create(
            business_name='First Property',
            tagline='First tagline',
            about_text='First about',
            contact_email='first@example.com',
            contact_phone='09170000001',
            address='First address',
            inquiry_text='First inquiry',
            is_active=True,
            updated_by=self.admin,
        )
        second = BusinessProfile.objects.create(
            business_name='Second Property',
            tagline='Second tagline',
            about_text='Second about',
            contact_email='second@example.com',
            contact_phone='09170000002',
            address='Second address',
            inquiry_text='Second inquiry',
            is_active=True,
            updated_by=self.admin,
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertTrue(second.is_active)
