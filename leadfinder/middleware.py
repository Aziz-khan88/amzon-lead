from __future__ import annotations

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.urls import resolve

from .access import user_role


class LoginAndRoleRequiredMiddleware:
    """Require authentication globally and reject sales access to management routes."""

    PUBLIC_URL_NAMES = {
        "login", "password_reset", "password_reset_done", "password_reset_confirm", "password_reset_complete",
        "token_obtain_pair", "token_refresh",
    }
    SALES_URL_NAMES = {
        "dashboard",
        "lead_list",
        "lead_detail",
        "lead_action",
        "lead_assignment_update",
        "export_leads_csv",
        "export_leads_xlsx",
        "logout",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        if path.startswith(f"/{settings.STATIC_URL.lstrip('/')}") or path.startswith("/admin/login/"):
            return self.get_response(request)

        match = resolve(path)
        url_name = match.url_name or ""
        if not request.user.is_authenticated:
            if url_name in self.PUBLIC_URL_NAMES:
                return self.get_response(request)
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)

        if user_role(request.user) == "sales" and url_name not in self.SALES_URL_NAMES:
            return HttpResponseForbidden("Your sales role does not have access to this workspace area.")

        response = self.get_response(request)
        response.headers.setdefault("Cache-Control", "private, no-store")
        response.headers.setdefault("Pragma", "no-cache")
        return response
