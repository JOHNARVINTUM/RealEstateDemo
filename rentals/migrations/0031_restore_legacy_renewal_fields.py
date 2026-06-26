from django.db import migrations, models
class Migration(migrations.Migration):
    dependencies = [
        ("rentals", "0030_alter_tenantattachment_file"),
    ]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=[
                        """
                        ALTER TABLE rentals_lease
                        ADD COLUMN IF NOT EXISTS renewal_requested_at timestamp with time zone NULL
                        """,
                        """
                        ALTER TABLE rentals_lease
                        ADD COLUMN IF NOT EXISTS renewal_status character varying(20)
                        """,
                        """
                        UPDATE rentals_lease
                        SET renewal_status = ''
                        WHERE renewal_status IS NULL
                        """,
                        """
                        ALTER TABLE rentals_lease
                        ALTER COLUMN renewal_status SET DEFAULT ''
                        """,
                        """
                        ALTER TABLE rentals_lease
                        ALTER COLUMN renewal_status SET NOT NULL
                        """,
                        """
                        ALTER TABLE rentals_lease
                        ADD COLUMN IF NOT EXISTS requested_renewal_end_date date NULL
                        """,
                    ],
                    reverse_sql=[
                        """
                        ALTER TABLE rentals_lease
                        DROP COLUMN IF EXISTS requested_renewal_end_date
                        """,
                        """
                        ALTER TABLE rentals_lease
                        DROP COLUMN IF EXISTS renewal_status
                        """,
                        """
                        ALTER TABLE rentals_lease
                        DROP COLUMN IF EXISTS renewal_requested_at
                        """,
                    ],
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="lease",
                    name="renewal_requested_at",
                    field=models.DateTimeField(blank=True, help_text="Legacy renewal request timestamp", null=True),
                ),
                migrations.AddField(
                    model_name="lease",
                    name="renewal_status",
                    field=models.CharField(blank=True, default="", help_text="Legacy renewal workflow state", max_length=20),
                ),
                migrations.AddField(
                    model_name="lease",
                    name="requested_renewal_end_date",
                    field=models.DateField(blank=True, help_text="Legacy requested lease end date", null=True),
                ),
            ],
        ),
    ]
