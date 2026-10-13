from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0017_manualpayment_lease_approved_at"),
        ("rentals", "0032_unique_active_lease_per_unit"),
    ]

    operations = [
        migrations.CreateModel(
            name="LeaseContractEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("MOVE_IN_PAYMENT", "Move-in Payment")], max_length=32)),
                ("status", models.CharField(choices=[("APPROVED", "Approved")], max_length=16)),
                ("occurred_at", models.DateTimeField()),
                ("payment_reference", models.CharField(blank=True, default="", max_length=80)),
                ("payment_method", models.CharField(blank=True, default="", max_length=30)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "lease",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="contract_events",
                        to="rentals.lease",
                    ),
                ),
                (
                    "source_payment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="contract_events",
                        to="payments.manualpayment",
                    ),
                ),
            ],
            options={"ordering": ["occurred_at", "id"]},
        ),
        migrations.AddIndex(
            model_name="leasecontractevent",
            index=models.Index(fields=["lease", "occurred_at"], name="lease_contract_event_idx"),
        ),
        migrations.AddConstraint(
            model_name="leasecontractevent",
            constraint=models.UniqueConstraint(
                fields=("source_payment", "event_type"),
                name="unique_contract_event_per_payment_type",
            ),
        ),
    ]
