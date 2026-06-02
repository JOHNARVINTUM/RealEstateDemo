from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0012_manualpayment_query_indexes"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="manualpayment",
            index=models.Index(fields=["created_at"], name="pay_created_idx"),
        ),
        migrations.AddIndex(
            model_name="manualpayment",
            index=models.Index(fields=["payment_method", "created_at"], name="pay_method_created_idx"),
        ),
    ]
