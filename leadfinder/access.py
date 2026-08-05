from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.shortcuts import redirect

from .models import Lead, UserProfile


def user_role(user) -> str:
    if not user or not user.is_authenticated:
        return "anonymous"
    if user.is_superuser:
        return "super_admin"
    try:
        return user.leadfinder_profile.role
    except UserProfile.DoesNotExist:
        return "sales"


def is_management(user) -> bool:
    return user_role(user) in {"super_admin", "admin"}


def lead_queryset_for_user(user, queryset: QuerySet | None = None) -> QuerySet:
    leads = queryset if queryset is not None else Lead.objects.all()
    if is_management(user):
        return leads
    if user_role(user) == "sales":
        return leads.filter(assignments__assigned_to=user, assignments__is_current=True).distinct()
    return leads.none()


def roles_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if user_role(request.user) not in allowed_roles:
                messages.error(request, "You do not have permission to open that page.")
                return redirect("leadfinder:dashboard")
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


def ensure_lead_access(user, lead: Lead) -> None:
    if not lead_queryset_for_user(user).filter(pk=lead.pk).exists():
        raise PermissionDenied("This lead is not assigned to you.")
