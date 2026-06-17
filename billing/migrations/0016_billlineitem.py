from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0015_billinginvoice"),
        ("water", "0003_waterreading_base_water_amount_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="BillLineItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("line_type", models.CharField(choices=[("RENT", "Rent"), ("PARKING", "Parking"), ("WATER", "Water"), ("LATE_FEE", "Late Fee"), ("SECURITY_DEPOSIT", "Security Deposit"), ("CONTRACT_DEPOSIT", "Contract Deposit")], max_length=30)),
                ("amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("paid_amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("status", models.CharField(choices=[("UNPAID", "Unpaid"), ("PARTIAL", "Partial"), ("PAID", "Paid")], default="UNPAID", max_length=20)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("payment_reference", models.CharField(blank=True, default="", max_length=80)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("monthly_bill", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="line_items", to="billing.monthlybill")),
                ("source_water_reading", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="billing_line_items", to="water.waterreading")),
            ],
            options={
                "ordering": ("monthly_bill", "line_type"),
                "unique_together": {("monthly_bill", "line_type")},
            },
        ),
        migrations.AddIndex(
            model_name="billlineitem",
            index=models.Index(fields=["monthly_bill", "line_type"], name="line_bill_type_idx"),
        ),
        migrations.AddIndex(
            model_name="billlineitem",
            index=models.Index(fields=["line_type", "status"], name="line_type_status_idx"),
        ),
    ]
