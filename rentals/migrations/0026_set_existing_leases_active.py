# Generated migration to set existing leases to ACTIVE status

from django.db import migrations

def set_existing_leases_active(apps, schema_editor):
    """Set all existing leases to ACTIVE status and sync is_active"""
    Lease = apps.get_model('rentals', 'Lease')
    
    for lease in Lease.objects.all():
        # If lease is already active (based on is_active), set status to ACTIVE
        if lease.is_active:
            lease.status = 'ACTIVE'
        else:
            # If not active, set to TERMINATED (for historical consistency)
            lease.status = 'TERMINATED'
        lease.save(update_fields=['status'])

def reverse_set_existing_leases_active(apps, schema_editor):
    """Reverse: clear status field (will revert to default)"""
    pass

class Migration(migrations.Migration):
    dependencies = [
        ('rentals', '0025_add_lease_status'),
    ]

    operations = [
        migrations.RunPython(set_existing_leases_active, reverse_set_existing_leases_active),
    ]
