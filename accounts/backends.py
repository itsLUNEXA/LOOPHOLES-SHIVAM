from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User


class EmailAuthBackend(ModelBackend):
    """Authenticate using email address (or fallback to username)."""

    def authenticate(self, request, username=None, password=None, email=None, **kwargs):
        lookup_val = email or username
        if not lookup_val or not password:
            return None

        # Look up by case-insensitive email, then fallback to username
        user = User.objects.filter(email__iexact=lookup_val.strip()).first()
        if not user:
            user = User.objects.filter(username__iexact=lookup_val.strip()).first()

        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
