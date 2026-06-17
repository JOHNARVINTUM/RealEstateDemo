from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0014_manualpayment_schedule_admin_note"),
    ]

    operations = [
        migrations.AlterField(
            model_name="manualpayment",
            name="payment_type",
            field=models.CharField(
                choices=[
                    ("full", "Full Payment"),
                    ("rent_only", "Monthly Rent"),
                    ("water_only", "Water Only"),
                    ("move_in", "Move-in Payment"),
                ],
                default="full",
                max_length=20,
            ),
        ),
    ]
