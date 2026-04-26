from rentals.models import Notification
from accounts.models import User

# Check if admin user can access notifications
admin_user = User.objects.filter(role='ADMIN').first()
print(f'Admin user: {admin_user.email if admin_user else "None"}')

# Check all notifications
all_notifications = Notification.objects.all()
print(f'Total notifications in DB: {all_notifications.count()}')

# Check notification details
for notif in all_notifications[:3]:
    user_info = notif.user.email if notif.user else "All Admins"
    print(f'  {notif.title} - User: {user_info} - Read: {notif.is_read}')

# Test the query that dashboard uses
dashboard_notifications = Notification.objects.all().order_by('-created_at')[:5]
print(f'Dashboard notifications query result: {dashboard_notifications.count()}')

# Test the query that admin_notifications uses  
admin_notifications = Notification.objects.all().order_by('-created_at')
print(f'Admin notifications query result: {admin_notifications.count()}')
