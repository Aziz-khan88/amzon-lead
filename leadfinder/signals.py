from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


@receiver(post_save, sender=get_user_model())
def ensure_user_profile(sender, instance, created, **kwargs):
    if created:
        role = "super_admin" if instance.is_superuser else "admin" if instance.is_staff else "sales"
        UserProfile.objects.get_or_create(user=instance, defaults={"role": role})
