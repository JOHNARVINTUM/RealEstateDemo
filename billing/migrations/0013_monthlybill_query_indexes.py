from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0012_add_parking_to_lease_and_bill"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="monthlybill",
            index=models.Index(
                fields=["lease", "status", "billing_month"],
                name="bill_lease_stat_month_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="monthlybill",
            index=models.Index(
                fields=["status", "due_date"],
                name="bill_stat_due_idx",
            ),
        ),
    ]
