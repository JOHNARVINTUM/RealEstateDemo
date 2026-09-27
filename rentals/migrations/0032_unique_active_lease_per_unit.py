from django.db import migrations, models
from django.db.models import Count, Q


def reject_existing_active_lease_duplicates(apps, schema_editor):
    Lease = apps.get_model("rentals", "Lease")
    violations = list(
        Lease.objects.filter(status="ACTIVE")
        .values("unit_id")
        .annotate(active_lease_count=Count("id"))
        .filter(active_lease_count__gt=1)
        .order_by("unit_id")
    )
    if violations:
        details = ", ".join(
            f"unit_id={row['unit_id']} ({row['active_lease_count']} active leases)"
            for row in violations
        )
        raise RuntimeError(
            "Cannot add unique_active_lease_per_unit while duplicate active "
            f"leases exist: {details}. Resolve them manually before retrying."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("rentals", "0031_restore_legacy_renewal_fields"),
    ]

    operations = [
        migrations.RunPython(
            reject_existing_active_lease_duplicates,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="lease",
            constraint=models.UniqueConstraint(
                condition=Q(("status", "ACTIVE")),
                fields=("unit",),
                name="unique_active_lease_per_unit",
            ),
        ),
    ]
