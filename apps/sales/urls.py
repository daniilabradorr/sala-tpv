from django.urls import path

from apps.sales import views

urlpatterns = [
    path("", views.SaleListView.as_view(), name="sale_list"),
    path("create/", views.SaleCreateView.as_view(), name="sale_create"),
    path("<int:pk>/", views.SaleDetailView.as_view(), name="sale_detail"),
    path("<int:pk>/edit/", views.SaleUpdateView.as_view(), name="sale_update"),
    path(
        "<int:pk>/cancel/",
        views.SaleCancelView.as_view(),
        name="sale_cancel",
    ),
    path(
        "<int:pk>/print/",
        views.SalePrintView.as_view(),
        name="sale_print",
    ),
]
