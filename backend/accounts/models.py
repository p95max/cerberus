from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Project-owned user model, introduced before the first migration."""

    pass
