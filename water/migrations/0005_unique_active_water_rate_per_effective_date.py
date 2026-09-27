from django.db import migrations, models
from django.db.models import Count, Q


def reject_existing_active_water_rate_duplicates(apps, schema_editor):
    WaterRate = apps.get_model("water", "WaterRate")
    duplicate_dates = list(
        WaterRate.objects.filter(is_active=True)
        .values("effective_date")
        .annotate(active_rate_count=Count("id"))
        .filter(active_rate_count__gt=1)
        .order_by("effective_date")
    )
    if duplicate_dates:
        details = []
        for row in duplicate_dates:
            rate_ids = list(
                WaterRate.objects.filter(
                    effective_date=row["effective_date"],
                    is_active=True,
                )
                .order_by("id")
                .values_list("id", flat=True)
            )
            details.append(
                f"effective_date={row['effective_date']} rate_ids={rate_ids}"
            )
        raise RuntimeError(
            "Cannot add unique_active_water_rate_per_effective_date while "
            "duplicate active water rates exist: "
            + "; ".join(details)
            + ". Resolve them manually before retrying."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("water", "0004_alter_waterrate_options"),
    ]

    operations = [
        migrations.RunPython(
            reject_existing_active_water_rate_duplicates,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="waterrate",
            constraint=models.UniqueConstraint(
                condition=Q(("is_active", True)),
                fields=("effective_date",),
                name="unique_active_water_rate_per_effective_date",
            ),
        ),
    ]
