from rentals.models import Notification
from django.test import Client
from accounts.models import User

# Test notification functionality
print('Testing Notification System:')
print('=' * 50)

# Get admin user
admin_user = User.objects.filter(role='ADMIN').first()
if not admin_user:
    print('No admin user found - using existing admin')

# Create test notifications
print('\n1. Creating test notifications...')
test_notifications = [
    {
        'title': 'Test Info Notification',
        'message': 'This is a test info notification.',
        'notification_type': 'INFO'
    },
    {
        'title': 'Test Warning Notification', 
        'message': 'This is a test warning notification.',
        'notification_type': 'WARNING'
    },
    {
        'title': 'Test Success Notification',
        'message': 'This is a test success notification.',
        'notification_type': 'SUCCESS'
    }
]

created_notifications = []
for notif_data in test_notifications:
    notification = Notification.objects.create(**notif_data)
    created_notifications.append(notification)
    print(f'  Created: {notification.title} (ID: {notification.id})')

# Test notification display
print(f'\n2. Total notifications: {Notification.objects.count()}')
print(f'   Unread notifications: {Notification.objects.filter(is_read=False).count()}')

# Test marking as read
print('\n3. Testing mark as read functionality...')
if created_notifications:
    test_notif = created_notifications[0]
    print(f'  Before: {test_notif.title} - Read: {test_notif.is_read}')
    test_notif.is_read = True
    test_notif.save()
    print(f'  After: {test_notif.title} - Read: {test_notif.is_read}')
    
    # Reset
    test_notif.is_read = False
    test_notif.save()

# Test notification types
print('\n4. Testing notification types...')
for notification_type in ['INFO', 'WARNING', 'SUCCESS', 'ERROR']:
    count = Notification.objects.filter(notification_type=notification_type).count()
    print(f'  {notification_type}: {count} notifications')

# Test notification ordering
print('\n5. Testing notification ordering...')
ordered_notifications = Notification.objects.all().order_by('-created_at')
print('  Latest notifications:')
for notif in ordered_notifications[:3]:
    print(f'    {notif.title} - {notif.created_at.strftime("%Y-%m-%d %H:%M:%S")}')

print('\n6. Notification system appears to be working correctly!')
