import pytest
from django.contrib.auth import get_user_model
from django.test import Client


@pytest.fixture
def client(db):
    user = get_user_model().objects.create(
        username="test-admin",
        email="admin@example.test",
        password="!test-login-disabled",
        is_staff=True,
        is_superuser=True,
    )
    test_client = Client()
    test_client.force_login(user)
    return test_client
