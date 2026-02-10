from rest_framework import serializers


class ChatRequestSerializer(serializers.Serializer):
    """
    Payload vindo do plugin WordPress (via proxy do WP REST).
    """
    api_secret = serializers.CharField()
    session_uuid = serializers.CharField()
    message = serializers.CharField(allow_blank=True, required=False)

    # Leads / identificadores
    user_name = serializers.CharField(allow_blank=True, required=False)
    user_phone = serializers.CharField(allow_blank=True, required=False)
    user_email = serializers.EmailField(allow_blank=True, required=False)

    # Metadados (ex.: page_url, referrer, user_agent, ip, utm, etc.)
    meta = serializers.JSONField(required=False)


class ChatResponseSerializer(serializers.Serializer):
    """Resposta padronizada para o widget."""
    text = serializers.CharField()
    media_url = serializers.CharField(required=False, allow_blank=True)
    media_type = serializers.CharField(required=False, allow_blank=True)
    session_uuid = serializers.CharField()


class BotAuthSerializer(serializers.Serializer):
    """Autenticação simples por api_secret (o WordPress não gera a chave)."""
    api_secret = serializers.CharField()
    site_url = serializers.URLField(required=False, allow_blank=True)


class BotSyncSerializer(BotAuthSerializer):
    """Recebe as preferências/configs do WordPress para o servidor armazenar."""
    wp_settings = serializers.JSONField(required=False)
