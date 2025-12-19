from rest_framework import permissions
from .models import Instance


class HasInstanceToken(permissions.BasePermission):
    """
    Verifica se o request possui um Header 'Authorization: Bearer <token-da-instancia>'.

    Em caso de falha, nega acesso (False). Quando válido, injeta a instância em:
        request.instance
    """

    message = "Token inválido ou ausente. Use: Authorization: Bearer <token-da-instancia>."

    def has_permission(self, request, view):
        auth_header = request.headers.get("Authorization") or request.headers.get("authorization") or ""
        auth_header = auth_header.strip()

        if not auth_header or not auth_header.lower().startswith("bearer "):
            return False

        parts = auth_header.split()
        if len(parts) < 2:
            return False

        token = parts[1].strip()
        if not token:
            return False

        try:
            instance = Instance.objects.get(token=token)
        except Instance.DoesNotExist:
            return False

        request.instance = instance
        return True
