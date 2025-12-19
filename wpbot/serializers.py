from rest_framework import serializers
from .models import WordpressBot

class ChatRequestSerializer(serializers.Serializer):
    """
    Recebe os dados do Plugin WordPress.
    """
    api_secret = serializers.UUIDField()
    session_uuid = serializers.CharField(max_length=100)
    message = serializers.CharField(required=False, allow_blank=True)
    
    # Opcionais: O plugin pode já enviar os dados se tiver capturado antes
    user_name = serializers.CharField(required=False, allow_blank=True)
    user_phone = serializers.CharField(required=False, allow_blank=True)

class ChatResponseSerializer(serializers.Serializer):
    """
    Devolve a resposta para o Plugin.
    """
    text = serializers.CharField()
    media_url = serializers.URLField(required=False, allow_null=True)
    media_type = serializers.CharField(required=False, allow_null=True)
    sender = serializers.CharField(default="bot")