from __future__ import annotations

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions

from .models import WordpressBot, WordpressApiErrorLog
from .serializers import (
    ChatRequestSerializer,
    BotAuthSerializer,
    BotSyncSerializer,
)
from .engine import WordpressBotEngine


# Chaves do widget que aceitamos receber do WordPress (para evitar lixo no banco)
ALLOWED_WIDGET_KEYS = {
    # Layout
    "position", "bottom_offset", "side_offset", "z_index", "widget_width", "widget_height", "rounded", "shadow",
    # Textos
    "header_title", "header_subtitle", "launcher_label", "placeholder", "send_label",
    # Marca
    "avatar_url", "brand_name", "brand_site",
    # Cores
    "primary_color", "accent_color", "background_color", "bubble_color", "bubble_text_color",
    # Comportamento
    "open_on_load", "open_delay", "show_badge", "sound", "typing_indicator",
    "greeting_enabled", "greeting_text", "offline_text",
    # Leads
    "lead_capture", "capture_name", "capture_phone", "capture_email", "lead_required",
    "lead_title", "lead_note",
    # LGPD
    "consent_required", "consent_text", "privacy_url",
}


def _sanitize_widget_settings(data: dict | None) -> dict:
    if not isinstance(data, dict):
        return {}
    clean = {}
    for k, v in data.items():
        if k in ALLOWED_WIDGET_KEYS:
            clean[k] = v
    return clean


def _build_meta(request, client_meta: dict | None) -> dict:
    meta = {}
    if isinstance(client_meta, dict):
        meta.update(client_meta)

    # Anexa dados do request (sem quebrar o que veio do cliente)
    meta.setdefault("ip", request.META.get("REMOTE_ADDR", ""))
    meta.setdefault("user_agent", request.META.get("HTTP_USER_AGENT", ""))
    meta.setdefault("host", request.META.get("HTTP_HOST", ""))
    meta.setdefault("x_forwarded_for", request.META.get("HTTP_X_FORWARDED_FOR", ""))
    return meta


def _bot_payload(bot: WordpressBot) -> dict:
    return {
        "id": bot.id,
        "name": bot.name,
        "company_name": bot.company_name,
        "website": bot.website,
        "summary": bot.summary,
        "active": bot.active,
    }


def _config_payload(bot: WordpressBot) -> dict:
    widget = bot.get_effective_widget_settings() if hasattr(bot, "get_effective_widget_settings") else {}
    return {
        "source": "django",
        "server_time": timezone.now().isoformat(),
        "bot": _bot_payload(bot),
        "widget": widget,
        "prefer_server": True,
        "last_sync_at": bot.last_sync_at.isoformat() if getattr(bot, "last_sync_at", None) else None,
        "last_sync_site": getattr(bot, "last_sync_site", "") or "",
    }


class WordpressChatAPI(APIView):
    """Recebe mensagens do WordPress e responde em formato simples."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {"error": "Dados inválidos", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        api_secret = serializer.validated_data["api_secret"]
        bot = WordpressBot.objects.filter(api_secret=api_secret, active=True).first()

        if not bot:
            return Response(
                {"error": "Chave inválida ou bot inativo."},
                status=status.HTTP_403_FORBIDDEN,
            )

        session_uuid = serializer.validated_data["session_uuid"]
        user_message = serializer.validated_data.get("message") or ""

        user_name = serializer.validated_data.get("user_name") or ""
        user_phone = serializer.validated_data.get("user_phone") or ""
        user_email = serializer.validated_data.get("user_email") or ""

        meta = _build_meta(request, serializer.validated_data.get("meta"))

        engine = WordpressBotEngine(bot=bot)

        try:
            result = engine.process_input(
                session_uuid=session_uuid,
                user_message=user_message,
                user_name=user_name,
                user_phone=user_phone,
                user_email=user_email,
                meta=meta,
            )
            # Result já vem no formato esperado: {text, media_url, media_type, session_uuid}
            return Response(result, status=status.HTTP_200_OK)

        except Exception as exc:
            # Loga no banco (evite vazar detalhes para o cliente)
            try:
                WordpressApiErrorLog.objects.create(
                    bot=bot,
                    session_uuid=session_uuid,
                    error_message=str(exc),
                    request_data=serializer.validated_data,
                )
            except Exception:
                pass

            return Response(
                {"error": "Erro interno. Tente novamente em instantes."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class WordpressBotConfigAPI(APIView):
    """
    Retorna configurações do bot/widget para o WordPress (para cache local e preview).
    Auth: api_secret do bot.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = BotAuthSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": "Dados inválidos", "details": serializer.errors}, status=400)

        api_secret = serializer.validated_data["api_secret"]
        bot = WordpressBot.objects.filter(api_secret=api_secret, active=True).first()
        if not bot:
            return Response({"error": "Chave inválida ou bot inativo."}, status=403)

        return Response(_config_payload(bot), status=200)


class WordpressBotSyncAPI(APIView):
    """
    Sincroniza preferências do WordPress → Django.
    IMPORTANT: o bot sempre usa preferências do Django (overrides) quando existir conflito.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = BotSyncSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": "Dados inválidos", "details": serializer.errors}, status=400)

        api_secret = serializer.validated_data["api_secret"]
        site_url = serializer.validated_data.get("site_url") or ""

        bot = WordpressBot.objects.filter(api_secret=api_secret, active=True).first()
        if not bot:
            return Response({"error": "Chave inválida ou bot inativo."}, status=403)

        wp_settings = serializer.validated_data.get("wp_settings") or {}
        # aceita tanto payload inteiro do plugin quanto somente widget
        if isinstance(wp_settings, dict) and "widget" in wp_settings and isinstance(wp_settings["widget"], dict):
            wp_widget = _sanitize_widget_settings(wp_settings["widget"])
        else:
            wp_widget = _sanitize_widget_settings(wp_settings)

        # Salva no bot
        if hasattr(bot, "wp_settings"):
            bot.wp_settings = wp_widget
        if hasattr(bot, "last_sync_at"):
            bot.last_sync_at = timezone.now()
        if hasattr(bot, "last_sync_site"):
            bot.last_sync_site = site_url[:500]
        bot.save()

        return Response(_config_payload(bot), status=200)
