from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0013_manualpayment_list_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="manualpayment",
            name="schedule_admin_note",
            field=models.TextField(blank=True, default="", help_text="Latest admin note for F2F schedule changes"),
        ),
    ]
