from .access import user_role


def role_context(request):
    role = user_role(getattr(request, "user", None))
    return {
        "current_role": role,
        "is_management": role in {"super_admin", "admin"},
        "is_super_admin": role == "super_admin",
        "is_sales": role == "sales",
    }
