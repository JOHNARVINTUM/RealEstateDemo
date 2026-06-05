from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("payments", "0013_manualpayment_list_indexes"),
        ("billing", "0014_monthlybill_list_indexes"),
    ]

    operations = [
        migrations.CreateModel(
            name="BillingInvoice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("invoice_number", models.CharField(max_length=40, unique=True)),
                ("bill_ids", models.CharField(blank=True, default="", max_length=255)),
                ("reference_code", models.CharField(blank=True, default="", max_length=80)),
                ("payment_method", models.CharField(blank=True, default="", max_length=30)),
                ("payment_type", models.CharField(blank=True, default="", max_length=30)),
                ("amount_paid", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("snapshot", models.JSONField(blank=True, default=dict)),
                ("email_sent", models.BooleanField(default=False)),
                ("emailed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "payment",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="invoice",
                        to="payments.manualpayment",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="billing_invoices",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(fields=["tenant", "created_at"], name="invoice_tenant_created_idx"),
                    models.Index(fields=["reference_code"], name="invoice_ref_idx"),
                ],
            },
        ),
    ]
