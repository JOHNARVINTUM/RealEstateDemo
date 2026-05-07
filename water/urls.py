"""
URL configuration for water app.
"""
from django.urls import path
from . import bulk_views

app_name = 'water'

urlpatterns = [
    path('bulk-entry/', bulk_views.bulk_water_reading_entry, name='bulk_entry'),
    path('bulk-process/', bulk_views.bulk_water_reading_process, name='bulk_process'),
]
