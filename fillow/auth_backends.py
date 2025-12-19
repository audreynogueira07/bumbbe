from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

class EmailOrUsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        try:
            # Verifica o email ou o campo username
            user = User.objects.get(email=username) if '@' in username else User.objects.get(username=username)
        except User.DoesNotExist:
            return None

        if user.check_password(password) and (user.is_active and (user.is_superuser or hasattr(user, 'aprovado') and user.aprovado)):
            return user
        return None
