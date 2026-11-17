from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameBackend(ModelBackend):
    """Lets users sign in with either their email or their username."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        User = get_user_model()
        field = 'email__iexact' if '@' in username else 'username'
        if field == 'email__iexact':
            username = username.strip()
        try:
            user = User.objects.get(**{field: username})
        except User.DoesNotExist:
            # Run the hasher anyway so response time doesn't reveal whether the account exists.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
