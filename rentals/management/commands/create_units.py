from django.core.management.base import BaseCommand
from rentals.models import Unit

class Command(BaseCommand):
    help = "Create 58 units (Unit 1 to Unit 58)"

    def handle(self, *args, **options):
        created = 0
        for i in range(1, 59):
            unit_no = str(i).zfill(2)  # 01..58
            obj, was_created = Unit.objects.get_or_create(number=unit_no)
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Done. Newly created: {created}. Total units: {Unit.objects.count()}"))
