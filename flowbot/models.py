import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


class FlowBot(models.Model):
    """Bot offline, baseado em fluxo (sem IA), editável via editor visual."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flowbots",
        verbose_name="Dono",
    )

    name = models.CharField(max_length=120, verbose_name="Nome do Bot")
    active = models.BooleanField(default=True, verbose_name="Ativo?")
    description = models.TextField(blank=True, default="", verbose_name="Descrição")

    # Token público (para uso em integrações: WordPress, apps, etc.)
    public_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    # JSON do fluxo (nodes/edges)
    flow_json = models.JSONField(default=dict, blank=True, verbose_name="Fluxo (JSON)")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "FlowBot"
        verbose_name_plural = "FlowBots"
        ordering = ("-updated_at", "-created_at")

    def __str__(self) -> str:
        return f"{self.name}"


class FlowMedia(models.Model):
    """Arquivos anexáveis ao fluxo (imagens, áudios, PDFs etc.)."""

    MEDIA_TYPES = (
        ("image", "Imagem"),
        ("audio", "Áudio"),
        ("file", "Arquivo"),
        ("video", "Vídeo"),
    )

    bot = models.ForeignKey(
        FlowBot,
        on_delete=models.CASCADE,
        related_name="medias",
        verbose_name="Bot",
    )

    file = models.FileField(upload_to="flowbot_media/%Y/%m/", verbose_name="Arquivo")
    media_type = models.CharField(max_length=20, choices=MEDIA_TYPES, default="file")
    title = models.CharField(max_length=140, blank=True, default="", verbose_name="Título")
    caption = models.TextField(blank=True, default="", verbose_name="Legenda/Descrição")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mídia do FlowBot"
        verbose_name_plural = "Mídias do FlowBot"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        label = self.title or (self.file.name.split("/")[-1] if self.file else "Arquivo")
        return f"{label}"


class FlowConversation(models.Model):
    """Conversa de teste (simulador) ou conversa real (site/app) para um FlowBot."""

    bot = models.ForeignKey(
        FlowBot,
        on_delete=models.CASCADE,
        related_name="conversations",
        verbose_name="Bot",
    )

    # Identificador de sessão (ex.: para uso em API pública)
    session_key = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)

    visitor_name = models.CharField(max_length=120, blank=True, default="")
    visitor_whatsapp = models.CharField(max_length=40, blank=True, default="")

    # Estado do fluxo
    # Exemplo:
    # {
    #   "current_node_id": "n_start",
    #   "waiting": {"type":"ask_input","node_id":"n_ask","var":"nome"},
    #   "vars": {"nome":"Audrey"},
    #   "last_user_text":"oi"
    # }
    state = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Conversa do FlowBot"
        verbose_name_plural = "Conversas do FlowBot"
        ordering = ("-updated_at",)

    def __str__(self) -> str:
        return f"{self.bot.name} / {self.session_key}"


class FlowMessage(models.Model):
    """Mensagens do simulador (e também pode ser usado em produção)."""

    MESSAGE_TYPES = (
        ("text", "Texto"),
        ("media", "Mídia"),
        ("system", "Sistema"),
    )

    conversation = models.ForeignKey(
        FlowConversation,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="Conversa",
    )

    from_visitor = models.BooleanField(default=False, verbose_name="Veio do visitante?")
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPES, default="text")
    text = models.TextField(blank=True, default="")
    media = models.ForeignKey(
        FlowMedia,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
    )

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Mensagem do FlowBot"
        verbose_name_plural = "Mensagens do FlowBot"
        ordering = ("created_at", "id")

    def __str__(self) -> str:
        who = "Visitor" if self.from_visitor else "Bot"
        return f"{who}: {self.message_type}"
