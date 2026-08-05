from django.urls import path
from django.contrib.auth import views as auth_views
from rest_framework_simplejwt.views import TokenRefreshView

from .auth_api import RoleTokenView
from .auth_views import RateLimitedLoginView

from . import views


app_name = "leadfinder"

urlpatterns = [
    path("login/", RateLimitedLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("api/auth/token/", RoleTokenView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/delete-rejected/", views.delete_rejected_leads, name="delete_rejected_leads"),
    path("scheduled-tasks/", views.scheduled_task_list, name="scheduled_task_list"),
    path("scheduled-tasks/new/", views.scheduled_task_create, name="scheduled_task_create"),
    path("scheduled-tasks/<uuid:pk>/edit/", views.scheduled_task_edit, name="scheduled_task_edit"),
    path("scheduled-tasks/<uuid:pk>/toggle/", views.scheduled_task_toggle, name="scheduled_task_toggle"),
    path("scheduled-tasks/<uuid:pk>/run-now/", views.scheduled_task_run_now, name="scheduled_task_run_now"),
    path("scheduled-tasks/<uuid:pk>/delete/", views.scheduled_task_delete, name="scheduled_task_delete"),
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
    path("lead-assignments/<uuid:pk>/update/", views.lead_assignment_update, name="lead_assignment_update"),
    path("assignment-schedules/", views.assignment_schedule_list, name="assignment_schedule_list"),
    path("assignment-schedules/new/", views.assignment_schedule_create, name="assignment_schedule_create"),
    path("assignment-schedules/<uuid:pk>/edit/", views.assignment_schedule_edit, name="assignment_schedule_edit"),
    path("assignment-schedules/<uuid:pk>/toggle/", views.assignment_schedule_toggle, name="assignment_schedule_toggle"),
    path("assignment-schedules/<uuid:pk>/run/", views.assignment_schedule_run, name="assignment_schedule_run"),
    path("assignment-schedules/<uuid:pk>/delete/", views.assignment_schedule_delete, name="assignment_schedule_delete"),
    path("team/", views.team_list, name="team_list"),
    path("team/<int:pk>/toggle/", views.team_member_toggle, name="team_member_toggle"),
    path("team/<int:pk>/role/", views.team_member_role_update, name="team_member_role_update"),
    path("export/leads.csv", views.export_leads_csv, name="export_leads_csv"),
    path("export/leads.xlsx", views.export_leads_xlsx_view, name="export_leads_xlsx"),
    path("settings-help/", views.settings_help, name="settings_help"),
    path("isbn-search/", views.isbn_search, name="isbn_search"),
    path("isbn-search/status/<uuid:run_id>/", views.isbn_search_status, name="isbn_search_status"),
    path("isbn-search/analyze/", views.isbn_analyze, name="isbn_analyze"),
    path("isbn-search/barcode/<str:identifier>.svg", views.isbn_barcode, name="isbn_barcode"),
    path("isbn-search/lookup/", views.isbn_lookup, name="isbn_lookup"),
]
