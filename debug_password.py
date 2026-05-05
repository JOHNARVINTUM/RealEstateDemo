import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RealEstateDemo.settings')
django.setup()

from rentals.services import generate_tenant_password

result = generate_tenant_password('mary-jane', "o'connor")
print(f'Result: {result}')
print('Expected: MJo\'connor')
print('Split test:')
print('mary-jane'.split())
