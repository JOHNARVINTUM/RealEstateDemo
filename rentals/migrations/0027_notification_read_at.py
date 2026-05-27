from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rentals', '0026_set_existing_leases_active'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='read_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
