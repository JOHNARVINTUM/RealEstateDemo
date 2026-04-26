from rentals.models import Notification

# Check all notification details
print('Current Notifications:')
print('=' * 50)
for notification in Notification.objects.all():
    print(f'ID: {notification.id}')
    print(f'Title: {notification.title}')
    print(f'Type: {notification.notification_type}')
    print(f'Read: {notification.is_read}')
    print(f'Created: {notification.created_at}')
    print(f'User: {notification.user.email if notification.user else "All Admins"}')
    print(f'Related Unit: {notification.related_unit.number if notification.related_unit else "None"}')
    print(f'Related Tenant: {notification.related_tenant.email if notification.related_tenant else "None"}')
    print('-' * 30)
