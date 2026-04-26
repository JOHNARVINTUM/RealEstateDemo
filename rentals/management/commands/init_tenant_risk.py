from django.core.management.base import BaseCommand
from rentals.services import TenantRiskService

class Command(BaseCommand):
    help = 'Initialize tenant risk classifications for all existing tenants'

    def handle(self, *args, **options):
        self.stdout.write('Initializing tenant risk classifications...')
        
        try:
            updated_count = TenantRiskService.update_all_tenant_risks()
            self.stdout.write(self.style.SUCCESS(f'Successfully initialized risk classifications for {updated_count} tenants'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error initializing risk classifications: {e}'))
