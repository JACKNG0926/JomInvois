from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("switch-role/", views.switch_role_view, name="switch_role"),
    path("simulate/", views.simulate_whatsapp_view, name="simulate_whatsapp"),

    # New: resolve customer, catalogue and quantity issues.
    path(
        "resolve/<int:draft_id>/",
        views.resolve_invoice_view,
        name="resolve_invoice",
    ),

    path(
        "approve/<int:draft_id>/",
        views.approve_invoice_view,
        name="approve_invoice",
    ),

    path("export/csv/", views.export_accountant_csv, name="export_csv"),

    path(
        "export/json/",
        views.export_accountant_json,
        name="export_json",
    ),
]
