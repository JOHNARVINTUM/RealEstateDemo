from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0011_manualpayment_metadata"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="manualpayment",
            index=models.Index(
                fields=["user", "status", "created_at"],
                name="pay_user_stat_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="manualpayment",
            index=models.Index(
                fields=["status", "payment_method", "created_at"],
                name="pay_stat_method_created_idx",
            ),
        ),
    ]
