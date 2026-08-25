from django.urls import path

from apps.cash_register import views

app_name = "cash_register"

urlpatterns = [
    path("stores/<int:store_id>/", views.register_list, name="register_list"),
    path("stores/<int:store_id>/open/", views.open_session, name="open"),
    path("stores/<int:store_id>/history/", views.history, name="history"),
    path(
        "stores/<int:store_id>/sessions/<int:session_id>/",
        views.session_detail,
        name="session_detail",
    ),
    path(
        "stores/<int:store_id>/sessions/<int:session_id>/cash-in/",
        views.cash_in,
        name="cash_in",
    ),
    path(
        "stores/<int:store_id>/sessions/<int:session_id>/cash-out/",
        views.cash_out,
        name="cash_out",
    ),
    path(
        "stores/<int:store_id>/sessions/<int:session_id>/adjustment/",
        views.adjustment,
        name="adjustment",
    ),
    path(
        "stores/<int:store_id>/sessions/<int:session_id>/review/",
        views.review,
        name="review",
    ),
    path(
        "stores/<int:store_id>/sessions/<int:session_id>/close/",
        views.close,
        name="close",
    ),
]
