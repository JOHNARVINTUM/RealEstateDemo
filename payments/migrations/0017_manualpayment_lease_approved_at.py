from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("rentals", "0032_unique_active_lease_per_unit"),
        ("payments", "0016_alter_manualpayment_payment_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="manualpayment",
            name="approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="manualpayment",
            name="lease",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="move_in_payments",
                to="rentals.lease",
            ),
        ),
    ]
