from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from .access import user_role


class RoleTokenSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        username_field = self.username_field
        identity = attrs.get(username_field)
        if identity and "@" in identity:
            user = get_user_model().objects.filter(email__iexact=identity).order_by("id").first()
            if user:
                attrs[username_field] = user.get_username()
        return super().validate(attrs)

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user_role(user)
        token["name"] = user.get_full_name() or user.username
        return token


class RoleTokenView(TokenObtainPairView):
    serializer_class = RoleTokenSerializer
