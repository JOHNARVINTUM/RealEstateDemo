from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.contrib.auth import get_user_model
from .models import Notification

User = get_user_model()

@login_required
def tenant_notifications(request):
    """View for tenant notifications with role-based filtering"""
    user = request.user
    
    # Only show tenant notifications to tenant users
    if user.role != 'TENANT':
        return render(request, 'error.html', {
            'message': 'Access denied. This page is for tenants only.'
        })
    
    # Get tenant-specific notifications
    notifications = Notification.objects.filter(
        recipient_type='TENANT',
        user=user
    ).order_by('-created_at')
    
    return render(request, 'tenant_portal/notifications.html', {
        'notifications': notifications,
        'user_type': 'tenant'
    })

@login_required
def admin_notifications(request):
    """View for admin notifications with role-based filtering"""
    user = request.user
    
    # Only show admin notifications to admin users
    if user.role != 'ADMIN':
        return render(request, 'error.html', {
            'message': 'Access denied. This page is for administrators only.'
        })
    
    # Get admin-specific notifications
    notifications = Notification.objects.filter(
        recipient_type='ADMIN',
        user=user
    )
    
    # Handle filtering
    status_filter = request.GET.get('status', 'all')
    if status_filter == 'unread':
        notifications = notifications.filter(is_read=False)
    elif status_filter == 'read':
        notifications = notifications.filter(is_read=True)
        
    notifications = notifications.order_by('is_read', '-created_at')
    
    # Calculate unread count (unfiltered)
    unread_count = Notification.objects.filter(
        recipient_type='ADMIN', user=user, is_read=False
    ).count()
    
    return render(request, 'admin_portal/notifications.html', {
        'notifications': notifications,
        'unread_count': unread_count,
        'status_filter': status_filter,
        'user_type': 'admin'
    })

@login_required
def mark_notification_read(request, notification_id):
    """Mark notification as read"""
    user = request.user
    
    try:
        notification = Notification.objects.get(
            id=notification_id,
            user=user
        )
        
        # Check if user has permission to access this notification
        if user.role == 'TENANT' and notification.recipient_type != 'TENANT':
            return render(request, 'error.html', {
                'message': 'Access denied.'
            })
        
        if user.role == 'ADMIN' and notification.recipient_type != 'ADMIN':
            return render(request, 'error.html', {
                'message': 'Access denied.'
            })
        
        notification.is_read = True
        notification.save(update_fields=['is_read'])
        
        # Redirect based on user role
        if user.role == 'TENANT':
            return redirect('tenant_notifications')
        else:
            return redirect('admin_notifications')
            
    except Notification.DoesNotExist:
        return render(request, 'error.html', {
            'message': 'Notification not found.'
        })
