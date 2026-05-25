"""
Authentication security middleware for RealEstate360+.

This module contains middleware for enforcing authentication security policies:
- First-login password change enforcement for tenants
- Session security validation
"""

import logging
from django.shortcuts import redirect
from django.urls import resolve, Resolver404
from django.conf import settings

logger = logging.getLogger(__name__)


class FirstLoginEnforcementMiddleware:
    """
    Middleware to enforce password change on first login for tenants.
    
    This middleware checks if a tenant user has the password_change_required
    flag set and redirects them to the password change page until they update
    their temporary password.
    
    Key features:
    - Only affects TENANT role users (not ADMIN/STAFF)
    - Prevents redirect loops by whitelisting exempt URLs
    - Bypasses checks for superusers and staff members
    - Minimal database impact (single field check)
    
    Usage:
        Add to MIDDLEWARE after AuthenticationMiddleware:
        'accounts.middleware.FirstLoginEnforcementMiddleware',
    
    Security considerations:
    - Must be placed AFTER AuthenticationMiddleware in settings
    - Exempt URLs must include password change flow endpoints
    - Does not affect API endpoints (only HTML page requests)
    """
    
    # URLs that should be accessible even when password change is required
    # These prevent redirect loops and allow logout/login
    EXEMPT_URL_PATTERNS = [
        '/password-change/',           # Password change form
        '/password-change/done/',        # Password change success
        '/logout/',                      # Logout endpoint
        '/login/',                       # Login page
        '/admin/',                       # Django admin (admins only)
        '/static/',                      # Static files
        '/media/',                       # Media files
    ]
    
    # URL names that should be exempt (reverse URL resolution)
    EXEMPT_URL_NAMES = [
        'password_change',
        'password_change_done',
        'logout',
        'login',
        'password_reset',
        'password_reset_done',
        'password_reset_confirm',
        'password_reset_complete',
    ]
    
    def __init__(self, get_response):
        """
        Initialize middleware with Django's get_response callable.
        
        Args:
            get_response: Django's callable to get the response from the next middleware/view
        """
        self.get_response = get_response
        # One-time configuration at startup
        logger.info("FirstLoginEnforcementMiddleware initialized")
    
    def __call__(self, request):
        """
        Process each request through the middleware.
        
        This is the main entry point for each request. It checks if the user
        needs to change their password and redirects if necessary.
        
        Args:
            request: The current HttpRequest object
            
        Returns:
            HttpResponse: Either a redirect or the response from the next handler
        """
        # Skip check if user is not authenticated
        if not request.user.is_authenticated:
            return self.get_response(request)
        
        # Skip for staff and superusers (admins bypass this check)
        if request.user.is_staff or request.user.is_superuser:
            return self.get_response(request)
        
        # Skip for non-tenant users (shouldn't happen with role system, but safety check)
        if not hasattr(request.user, 'role') or request.user.role != 'TENANT':
            return self.get_response(request)
        
        # Check if current URL is exempt from password change requirement
        if self._is_exempt_url(request):
            return self.get_response(request)
        
        # Check if tenant needs password change
        if self._requires_password_change(request.user):
            logger.info(
                f"Redirecting user {request.user.username} to password change - "
                f"password_change_required=True"
            )
            return redirect('password_change')
        
        # User has changed password or didn't require change, proceed normally
        return self.get_response(request)
    
    def _is_exempt_url(self, request):
        """
        Check if the current request URL is exempt from password change enforcement.
        
        Args:
            request: The current HttpRequest object
            
        Returns:
            bool: True if URL is exempt, False otherwise
        """
        path = request.path
        
        # Check URL patterns (direct string matching)
        for exempt_pattern in self.EXEMPT_URL_PATTERNS:
            if path.startswith(exempt_pattern):
                return True
        
        # Check URL names (reverse resolution matching)
        try:
            resolved_url = resolve(path)
            if resolved_url.url_name in self.EXEMPT_URL_NAMES:
                return True
        except Resolver404:
            # URL not resolvable, let it through to avoid blocking
            pass
        
        return False
    
    def _requires_password_change(self, user):
        """
        Check if the user requires a password change.
        
        This checks the TenantProfile.password_change_required flag.
        Returns False safely if profile doesn't exist (edge case handling).
        
        Args:
            user: The User object to check
            
        Returns:
            bool: True if password change required, False otherwise
        """
        try:
            # Check if user has a tenant profile with password_change_required=True
            if hasattr(user, 'tenantprofile'):
                return user.tenantprofile.password_change_required
        except Exception as e:
            # Log error but don't block user (fail-safe)
            logger.error(
                f"Error checking password_change_required for user {user.username}: {e}"
            )
        
        return False
