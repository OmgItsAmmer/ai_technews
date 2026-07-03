import os

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command


@pytest.mark.django_db
def test_ensure_admin_user_hashes_password(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "testadmin")
    monkeypatch.setenv("ADMIN_PASSWORD", "Str0ng-Pass!")

    call_command("ensure_admin_user")

    user = get_user_model().objects.get(username="testadmin")
    assert user.is_staff
    assert user.is_superuser
    assert user.check_password("Str0ng-Pass!")
    assert user.password != "Str0ng-Pass!"


@pytest.mark.django_db
def test_ensure_admin_user_updates_existing_password(monkeypatch):
    User = get_user_model()
    user = User.objects.create_user(username="testadmin", password="old-pass")
    user.is_staff = True
    user.is_superuser = True
    user.save()

    monkeypatch.setenv("ADMIN_USERNAME", "testadmin")
    monkeypatch.setenv("ADMIN_PASSWORD", "new-pass-123")

    call_command("ensure_admin_user")

    user.refresh_from_db()
    assert user.check_password("new-pass-123")
