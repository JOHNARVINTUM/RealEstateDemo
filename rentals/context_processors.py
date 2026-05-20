from .models import Notification


def unread_notification_count(request):
    """
    Context processor to add unread notification count for logged-in tenants.
    This makes the count available in all templates.
    """
    if not request.user.is_authenticated:
        return {"unread_notification_count": 0}
    
    # Only count notifications for tenants
    count = Notification.objects.filter(
        recipient_type='TENANT',
        user=request.user,
        is_read=False
    ).count()
    
    return {"unread_notification_count": count}
