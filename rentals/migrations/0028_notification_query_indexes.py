from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rentals", "0027_notification_read_at"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(
                fields=["user", "recipient_type", "is_read", "created_at"],
                name="notif_user_read_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(
                fields=["is_read", "read_at"],
                name="notif_read_at_idx",
            ),
        ),
    ]
