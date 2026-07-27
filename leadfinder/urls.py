from django.urls import path

from . import views


app_name = "leadfinder"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/delete-rejected/", views.delete_rejected_leads, name="delete_rejected_leads"),
    path("runs/new/", views.run_new, name="run_new"),
    path("runs/booklife/", views.booklife_run, name="booklife_run"),
    path("runs/", views.run_list, name="run_list"),
    path("runs/<uuid:pk>/", views.run_detail, name="run_detail"),
    path("runs/<uuid:pk>/status/", views.run_agent_status, name="run_agent_status"),
    path("runs/<uuid:pk>/stop/", views.run_stop, name="run_stop"),
    path("runs/<uuid:pk>/retry/", views.run_retry, name="run_retry"),
    path("import-csv/", views.import_csv, name="import_csv"),
    path("leads/", views.lead_list, name="lead_list"),
    path("leads/bulk-action/", views.lead_bulk_action, name="lead_bulk_action"),
    path("leads/<uuid:pk>/", views.lead_detail, name="lead_detail"),
    path("leads/<uuid:pk>/<str:action>/", views.lead_action, name="lead_action"),
    path("export/leads.csv", views.export_leads_csv, name="export_leads_csv"),
    path("export/leads.xlsx", views.export_leads_xlsx_view, name="export_leads_xlsx"),
    path("settings-help/", views.settings_help, name="settings_help"),
    path("isbn-search/", views.isbn_search, name="isbn_search"),
    path("isbn-search/status/<uuid:run_id>/", views.isbn_search_status, name="isbn_search_status"),
    path("isbn-search/analyze/", views.isbn_analyze, name="isbn_analyze"),
    path("isbn-search/barcode/<str:identifier>.svg", views.isbn_barcode, name="isbn_barcode"),
    path("isbn-search/lookup/", views.isbn_lookup, name="isbn_lookup"),
]
