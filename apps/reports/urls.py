from django.urls import path

from apps.reports.views import ReportsOverviewView, SalesExportView

app_name = "reports"

urlpatterns = [
    path("", ReportsOverviewView.as_view(), name="overview"),
    path("sales/export.csv", SalesExportView.as_view(), name="sales_export"),
]
