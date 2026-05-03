from django.core.management.base import BaseCommand
from rentals.models import Room

class Command(BaseCommand):
    help = 'Create sample room data for testing'

    def handle(self, *args, **options):
        self.stdout.write('Creating sample rooms...')
        
        sample_rooms = [
            {
                'name': 'Deluxe Suite A',
                'price': 25000.00,
                'description': 'Spacious deluxe suite with king-size bed, living area, and city view. Includes premium amenities and housekeeping service.',
                'status': 'AVAILABLE'
            },
            {
                'name': 'Executive Room B',
                'price': 18000.00,
                'description': 'Modern executive room with workspace, high-speed internet, and mini kitchenette. Perfect for business travelers.',
                'status': 'OCCUPIED'
            },
            {
                'name': 'Standard Room C',
                'price': 12000.00,
                'description': 'Comfortable standard room with queen bed, private bathroom, and basic amenities. Great value for money.',
                'status': 'AVAILABLE'
            },
            {
                'name': 'Family Suite D',
                'price': 35000.00,
                'description': 'Large family suite with two bedrooms, full kitchen, and living room. Ideal for families and long stays.',
                'status': 'AVAILABLE'
            },
            {
                'name': 'Studio Room E',
                'price': 8000.00,
                'description': 'Compact studio with Murphy bed, kitchenette, and modern bathroom. Perfect for solo travelers.',
                'status': 'MAINTENANCE'
            },
            {
                'name': 'Penthouse Suite F',
                'price': 50000.00,
                'description': 'Luxurious penthouse with panoramic views, private terrace, jacuzzi, and full butler service.',
                'status': 'OCCUPIED'
            },
            {
                'name': 'Garden View Room G',
                'price': 15000.00,
                'description': 'Peaceful room overlooking the garden with private balcony. Includes tea/coffee facilities.',
                'status': 'AVAILABLE'
            },
            {
                'name': 'Ocean View Room H',
                'price': 22000.00,
                'description': 'Beautiful ocean view room with large windows, sitting area, and premium bedding.',
                'status': 'AVAILABLE'
            }
        ]
        
        created_count = 0
        for room_data in sample_rooms:
            room, created = Room.objects.get_or_create(
                name=room_data['name'],
                defaults=room_data
            )
            if created:
                created_count += 1
                self.stdout.write(f'Created room: {room.name}')
            else:
                self.stdout.write(f'Room already exists: {room.name}')
        
        self.stdout.write(self.style.SUCCESS(f'Successfully created {created_count} new rooms'))
        self.stdout.write(f'Total rooms in database: {Room.objects.count()}')
