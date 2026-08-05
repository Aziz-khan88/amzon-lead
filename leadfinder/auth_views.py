from __future__ import annotations

import hashlib

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.core.cache import cache


class EmailOrUsernameAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Email or username",
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username", "placeholder": "name@example.com"}),
    )

    def clean(self):
        identity = self.cleaned_data.get("username")
        if identity and "@" in identity:
            user = get_user_model().objects.filter(email__iexact=identity).order_by("id").first()
            if user:
                self.cleaned_data["username"] = user.get_username()
        return super().clean()


class RateLimitedLoginView(LoginView):
    form_class = EmailOrUsernameAuthenticationForm
    template_name = "registration/login.html"
    window_seconds = 15 * 60
    maximum_attempts = 5

    def _cache_key(self):
        identity = f"{self.request.META.get('REMOTE_ADDR', '')}:{self.request.POST.get('username', '').lower()}"
        return "login-attempt:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def post(self, request, *args, **kwargs):
        if cache.get(self._cache_key(), 0) >= self.maximum_attempts:
            form = self.get_form()
            form.add_error(None, "Too many sign-in attempts. Try again in 15 minutes.")
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        key = self._cache_key()
        attempts = cache.get(key, 0) + 1
        cache.set(key, attempts, self.window_seconds)
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(self._cache_key())
        return super().form_valid(form)
