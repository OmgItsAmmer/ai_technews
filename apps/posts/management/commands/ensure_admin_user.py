import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Create or update the Django admin user from ADMIN_USERNAME and "
        "ADMIN_PASSWORD in the environment (password stored hashed)."
    )

    def handle(self, *args, **options):
        username = os.environ.get("ADMIN_USERNAME", "").strip()
        password = os.environ.get("ADMIN_PASSWORD", "")

        if not username or not password:
            self.stderr.write(
                self.style.ERROR(
                    "Set ADMIN_USERNAME and ADMIN_PASSWORD in .env, then re-run."
                )
            )
            return

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"is_staff": True, "is_superuser": True},
        )
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save()

        verb = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(f"{verb} admin user '{username}' (password hashed in DB).")
        )
