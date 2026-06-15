from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("maintenance", "0004_maintenancerequest_photo"),
    ]

    operations = [
        migrations.AddField(
            model_name="maintenancerequest",
            name="requested_schedule_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Tenant's preferred date and time for maintenance visit.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="maintenancerequest",
            name="schedule_decision",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending Admin Review"),
                    ("APPROVED", "Approved"),
                    ("RESCHEDULED", "Rescheduled"),
                    ("DECLINED", "Declined"),
                ],
                default="PENDING",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="maintenancerequest",
            name="admin_scheduled_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Admin-approved or rescheduled maintenance visit time.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="maintenancerequest",
            name="schedule_admin_note",
            field=models.TextField(blank=True, default=""),
        ),
    ]
