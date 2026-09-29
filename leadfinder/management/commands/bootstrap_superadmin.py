from getpass import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from leadfinder.models import UserProfile


class Command(BaseCommand):
    help = "Create the first Lead Finder super-admin account securely."

    def add_arguments(self, parser):
        parser.add_argument("--username")
        parser.add_argument("--email")

    def handle(self, *args, **options):
        User = get_user_model()
        username = (options.get("username") or input("Username: ")).strip()
        email = (options.get("email") or input("Email: ")).strip()
        if not username or not email:
            raise CommandError("Username and email are required.")
        if User.objects.filter(username__iexact=username).exists():
            raise CommandError("That username already exists.")
        password = getpass("Password: ")
        confirmation = getpass("Confirm password: ")
        if password != confirmation:
            raise CommandError("Passwords do not match.")
        user = User.objects.create_superuser(username=username, email=email, password=password)
        UserProfile.objects.update_or_create(user=user, defaults={"role": "super_admin"})
        self.stdout.write(self.style.SUCCESS(f"Super admin {username} created. You can now sign in."))
