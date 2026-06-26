from django.db import migrations, models
import rentals.storage


class Migration(migrations.Migration):

    dependencies = [
        ("maintenance", "0005_maintenance_schedule_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="maintenancerequest",
            name="photo",
            field=models.ImageField(
                blank=True,
                null=True,
                storage=rentals.storage.SupabaseStorage(bucket="user-files"),
                upload_to="maintenance/",
            ),
        ),
    ]

