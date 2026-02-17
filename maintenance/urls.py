from django.urls import path
from .views import report_issue, maintenance_list

urlpatterns = [
    path("report/", report_issue, name="report_issue"),
    path("", maintenance_list, name="maintenance_list"),
]
