import os
import uuid
import secrets
import re
from datetime import timedelta
from dateutil.relativedelta import relativedelta  # Requer: pip install python-dateutil
from django.dispatch import receiver
from django.utils import timezone
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models.signals import post_delete, pre_save

# ==============================================================================
# VALIDATORS
# ==============================================================================

def validate_cpf(value):
    """
    Validador de CPF que verifica o cálculo dos dígitos verificadores.
    Aceita CPF com ou sem pontuação.
    """
    # Remove caracteres não numéricos
    cpf = ''.join(filter(str.isdigit, str(value)))

    if len(cpf) != 11:
        raise ValidationError("O CPF deve conter exatamente 11 dígitos.")

    # Verifica se todos os números são iguais (ex: 111.111.111-11), o que é inválido
    if cpf == cpf[0] * 11:
        raise ValidationError("CPF inválido.")

    # Cálculo do primeiro dígito verificador
    soma = 0
    for i in range(9):
        soma += int(cpf[i]) * (10 - i)
    resto = (soma * 10) % 11
    if resto == 10:
        resto = 0
    if resto != int(cpf[9]):
        raise ValidationError("CPF inválido.")

    # Cálculo do segundo dígito verificador
    soma = 0
    for i in range(10):
        soma += int(cpf[i]) * (11 - i)
    resto = (soma * 10) % 11
    if resto == 10:
        resto = 0
    if resto != int(cpf[10]):
        raise ValidationError("CPF inválido.")

# ==============================================================================
# 1. MODELO DE PLANOS (Atualizado com Duração e Chatbots)
# ==============================================================================
class Plan(models.Model):
    DURATION_TYPES = (
        ('days', 'Dias'),
        ('months', 'Meses'),
        ('years', 'Anos'),
        ('lifetime', 'Vitalício'),
    )

    name = models.CharField(max_length=50, unique=True, verbose_name="Nome do Plano")
    max_instances = models.PositiveIntegerField(default=1, verbose_name="Limite de Instâncias")
    
    # --- NOVO CAMPO: Limite de Chatbots ---
    max_chatbots = models.PositiveIntegerField(default=1, verbose_name="Limite de Chatbots")
    
    # Limite de conversas mensais para o chatbot (usado no app chatbot)
    monthly_conversations_limit = models.IntegerField(default=1000, verbose_name="Limite de Conversas/Mês")

    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Preço Mensal")
    description = models.TextField(blank=True, verbose_name="Descrição do Plano")

    # Campos para controle de tempo
    duration_type = models.CharField(
        max_length=10, 
        choices=DURATION_TYPES, 
        default='months',
        verbose_name="Tipo de Duração"
    )
    duration_value = models.PositiveIntegerField(
        default=1, 
        verbose_name="Tempo de Duração",
        help_text="Ex: Se Tipo='Meses' e Tempo=3, o plano dura 3 meses."
    )

    class Meta:
        verbose_name = "Plano"
        verbose_name_plural = "Planos"

    def __str__(self):
        if self.duration_type == 'lifetime':
            return f"{self.name} (Vitalício)"
        return f"{self.name} ({self.duration_value} {self.get_duration_type_display()})"

# ==============================================================================
# 2. USUÁRIO CUSTOMIZADO (Atualizado com Lógica de Chatbot)
# ==============================================================================
class Usuario(AbstractUser):
    plan = models.ForeignKey(
        Plan, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="users",
        verbose_name="Plano Atual"
    )
    
    # Campo de CPF com Validação
    cpf = models.CharField(
        max_length=14, 
        unique=True, 
        null=True, 
        blank=True, 
        verbose_name="CPF", 
        validators=[validate_cpf],
        help_text="Digite apenas números ou no formato 000.000.000-00"
    )
    
    # Campos de controle de assinatura
    plan_start_date = models.DateTimeField(blank=True, null=True, verbose_name="Início do Plano")
    plan_end_date = models.DateTimeField(blank=True, null=True, verbose_name="Vencimento do Plano")
    
    phone_number = models.CharField(max_length=20, blank=True, null=True, verbose_name="Telefone")
    api_key = models.UUIDField(default=uuid.uuid4, editable=False)
    api = models.BooleanField(default=False, verbose_name="Acesso à API")
    agendamento = models.BooleanField(default=False, verbose_name="Acesso a Agendamento")
    chatbot = models.BooleanField(default=False, verbose_name="Acesso ao Chatbot")
    
    # Campos padrão do AbstractUser
    groups = models.ManyToManyField(
        'auth.Group', verbose_name='groups', blank=True,
        related_name="usuario_groups", related_query_name="usuario"
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission', verbose_name='user permissions', blank=True,
        related_name="usuario_user_permissions", related_query_name="usuario"
    )

    class Meta:
        verbose_name = "Usuário"
        verbose_name_plural = "Usuários"

    def save(self, *args, **kwargs):
        """
        Sobrescreve o save para garantir que o CPF seja salvo apenas com números.
        """
        if self.cpf:
            self.cpf = ''.join(filter(str.isdigit, str(self.cpf)))
        super().save(*args, **kwargs)

    def assign_plan(self, plan):
        """
        Atribui um plano e calcula a data de vencimento.
        """
        self.plan = plan
        self.plan_start_date = timezone.now()
        
        if plan.duration_type == 'lifetime':
            self.plan_end_date = None  # None significa nunca expira
        else:
            if plan.duration_type == 'days':
                self.plan_end_date = self.plan_start_date + timedelta(days=plan.duration_value)
            elif plan.duration_type == 'months':
                self.plan_end_date = self.plan_start_date + relativedelta(months=plan.duration_value)
            elif plan.duration_type == 'years':
                self.plan_end_date = self.plan_start_date + relativedelta(years=plan.duration_value)
        
        self.save()

    @property
    def is_plan_valid(self):
        """Verifica se o usuário tem um plano e se ele não expirou."""
        if not self.plan:
            return False
        
        if self.plan_end_date is None:
            return True
            
        return timezone.now() < self.plan_end_date

    def can_create_instance(self):
        """Verifica limites de instâncias."""
        if not self.is_plan_valid:
            return False
        current_count = self.instances.count()
        return current_count < self.plan.max_instances

    # --- MÉTODO NOVO PARA O CHATBOT ---
    def can_create_chatbot(self):
        """Verifica limites de criação de chatbot baseados no plano."""
        # 1. Verifica se o plano é válido
        if not self.is_plan_valid:
            return False
            
        # 2. Verifica limite de chatbots definido no plano
        # Se self.plan for None, assume limite 0
        limit = self.plan.max_chatbots if self.plan else 0
        
        # 'chatbots' é o related_name definido no model Chatbot
        current_count = self.chatbots.count() 
        
        return current_count < limit

# ==============================================================================
# 3. INSTÂNCIA
# ==============================================================================
class Instance(models.Model):
    STATUS_CHOICES = (
        ('CREATED', 'Aguardando Início'),
        ('QR_SCANNED', 'QR Code Lido'),
        ('CONNECTED', 'Conectado'),
        ('DISCONNECTED', 'Desconectado'),
        ('BAN', 'Banido'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="instances")
    name = models.CharField(max_length=100, verbose_name="Nome da Instância")
    session_id = models.CharField(max_length=100, unique=True, editable=False)
    # Token gerenciado pelo Node.js
    token = models.CharField(max_length=64, unique=True, editable=False, blank=True, null=True)
    phone_connected = models.CharField(max_length=30, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='CREATED')
    profile_pic_url = models.URLField(blank=True, null=True)
    platform = models.CharField(max_length=50, blank=True, null=True)
    battery_level = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.owner.is_plan_valid:
            self.status = 'DISCONNECTED'

        if not self.session_id:
            self.session_id = f"sess_{uuid.uuid4().hex[:16]}"

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} - {self.owner.username}"

class WebhookConfig(models.Model):
    instance = models.OneToOneField(Instance, on_delete=models.CASCADE, related_name="webhook")
    url = models.URLField(verbose_name="URL de Retorno", blank=True, null=True)
    secret = models.CharField(max_length=64, default=secrets.token_hex, editable=False)
    send_messages = models.BooleanField(default=True)
    send_ack = models.BooleanField(default=False)
    send_presence = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class Message(models.Model):
    MESSAGE_TYPES = (
        ('text', 'Texto'), ('image', 'Imagem'), ('video', 'Vídeo'), 
        ('audio', 'Áudio'), ('document', 'Documento'), ('sticker', 'Figurinha'), 
        ('other', 'Outro')
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(Instance, on_delete=models.CASCADE, related_name="messages")
    remote_jid = models.CharField(max_length=50)
    from_me = models.BooleanField(default=False)
    push_name = models.CharField(max_length=100, blank=True, null=True)
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPES, default='text')
    content = models.TextField(blank=True, null=True)
    media_url = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    wamid = models.CharField(max_length=100, blank=True, null=True, unique=True)
    
    class Meta:
        ordering = ['-timestamp']
        
def user_directory_path(instance, filename):
    ext = filename.split('.')[-1]
    filename = f'{uuid.uuid4()}.{ext}'
    return f'uploads/user_{instance.owner.id}/{filename}'

class MediaFile(models.Model):
    MEDIA_TYPES = (
        ('image', 'Imagem'),
        ('video', 'Vídeo'),
        ('audio', 'Áudio'),
        ('document', 'Documento'),
        ('sticker', 'Figurinha'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name="media_files",
        verbose_name="Dono do Arquivo"
    )
    file = models.FileField(upload_to=user_directory_path, verbose_name="Arquivo")
    original_name = models.CharField(max_length=255, verbose_name="Nome Original")
    media_type = models.CharField(max_length=20, choices=MEDIA_TYPES, default='document')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Arquivo de Mídia"
        verbose_name_plural = "Arquivos de Mídia"
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.media_type and self.file:
            ext = os.path.splitext(self.file.name)[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                self.media_type = 'image'
            elif ext in ['.mp4', '.avi', '.mov', '.mkv']:
                self.media_type = 'video'
            elif ext in ['.mp3', '.ogg', '.wav', '.aac']:
                self.media_type = 'audio'
            elif ext in ['.pdf', '.doc', '.docx', '.txt', '.xls']:
                self.media_type = 'document'
            
        if not self.id or not self.original_name:
             self.original_name = self.file.name 

        super().save(*args, **kwargs)

    @property
    def get_absolute_url(self):
        if self.file:
            return self.file.url
        return None
    
    @property
    def file_extension(self):
        name, extension = os.path.splitext(self.file.name)
        return extension

    def __str__(self):
        return f"{self.original_name} ({self.get_media_type_display()})"
    
# ==============================================================================
# SIGNALS / RECEIVERS PARA LIMPEZA DE ARQUIVOS
# ==============================================================================

@receiver(post_delete, sender=MediaFile)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    if instance.file:
        if os.path.isfile(instance.file.path):
            try:
                os.remove(instance.file.path)
            except Exception as e:
                print(f"Erro ao deletar arquivo: {e}")

@receiver(pre_save, sender=MediaFile)
def auto_delete_file_on_change(sender, instance, **kwargs):
    if not instance.pk:
        return False

    try:
        old_file = sender.objects.get(pk=instance.pk).file
    except sender.DoesNotExist:
        return False

    new_file = instance.file
    
    if not old_file == new_file:
        if os.path.isfile(old_file.path):
            try:
                os.remove(old_file.path)
            except Exception as e:
                print(f"Erro ao deletar arquivo antigo: {e}")
                
# =========================
# DISPARADOR / CAMPANHAS
# =========================

class DispatchMessageTemplate(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dispatch_message_templates",
    )
    name = models.CharField(max_length=120)
    body = models.TextField(blank=True, help_text='Você pode usar {nome} para personalização.')
    media_file = models.ForeignKey(
        "MediaFile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dispatch_templates",
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name"],
                name="uniq_dispatch_template_name_per_owner",
            )
        ]

    def clean(self):
        if not self.body and not self.media_file:
            raise ValidationError("Informe um texto ou anexe uma mídia no template.")

    def __str__(self):
        return f"{self.name} ({self.owner})"


class DispatchContactGroup(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dispatch_contact_groups",
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name"],
                name="uniq_dispatch_group_name_per_owner",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.owner})"


class DispatchContact(models.Model):
    group = models.ForeignKey(
        "DispatchContactGroup",
        on_delete=models.CASCADE,
        related_name="contacts",
    )
    phone_number = models.CharField(max_length=30)
    jid = models.CharField(max_length=80, db_index=True)
    display_name = models.CharField(max_length=120, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_name", "phone_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["group", "jid"],
                name="uniq_dispatch_contact_per_group",
            )
        ]

    def __str__(self):
        return self.display_name or self.phone_number or self.jid


class DispatchCampaign(models.Model):
    STATUS_DRAFT = "DRAFT"
    STATUS_SCHEDULED = "SCHEDULED"
    STATUS_RUNNING = "RUNNING"
    STATUS_PAUSED = "PAUSED"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_CANCELED = "CANCELED"
    STATUS_FAILED = "FAILED"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Rascunho"),
        (STATUS_SCHEDULED, "Agendada"),
        (STATUS_RUNNING, "Em execução"),
        (STATUS_PAUSED, "Pausada"),
        (STATUS_COMPLETED, "Concluída"),
        (STATUS_CANCELED, "Cancelada"),
        (STATUS_FAILED, "Falha"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dispatch_campaigns",
    )
    instance = models.ForeignKey(
        "Instance",
        on_delete=models.CASCADE,
        related_name="dispatch_campaigns",
    )

    name = models.CharField(max_length=150)
    start_at = models.DateTimeField(default=timezone.now)

    min_delay_seconds = models.PositiveIntegerField(default=20)
    max_delay_seconds = models.PositiveIntegerField(default=45)

    messages_per_recipient = models.PositiveIntegerField(default=1)
    use_name_placeholder = models.BooleanField(default=True)

    raw_numbers = models.TextField(
        blank=True,
        help_text="Números separados por vírgula/linha (aceita também JID).",
    )

    groups = models.ManyToManyField(
        "DispatchContactGroup",
        related_name="campaigns",
        blank=True,
    )
    templates = models.ManyToManyField(
        "DispatchMessageTemplate",
        related_name="campaigns",
        blank=True,
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)

    total_recipients = models.PositiveIntegerField(default=0)
    total_planned = models.PositiveIntegerField(default=0)
    total_sent = models.PositiveIntegerField(default=0)
    total_failed = models.PositiveIntegerField(default=0)
    total_delivered = models.PositiveIntegerField(default=0)
    total_read = models.PositiveIntegerField(default=0)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["instance", "status"]),
            models.Index(fields=["start_at"]),
        ]

    def clean(self):
        if self.max_delay_seconds < self.min_delay_seconds:
            raise ValidationError("max_delay_seconds não pode ser menor que min_delay_seconds.")
        if self.messages_per_recipient < 1:
            raise ValidationError("messages_per_recipient deve ser >= 1.")

    def __str__(self):
        return f"{self.name} [{self.get_status_display()}]"


class DispatchCampaignRecipient(models.Model):
    SOURCE_INLINE = "INLINE"
    SOURCE_GROUP = "GROUP"

    SOURCE_CHOICES = [
        (SOURCE_INLINE, "Lista avulsa"),
        (SOURCE_GROUP, "Grupo"),
    ]

    campaign = models.ForeignKey(
        "DispatchCampaign",
        on_delete=models.CASCADE,
        related_name="recipients",
    )
    jid = models.CharField(max_length=80, db_index=True)
    phone_number = models.CharField(max_length=30)
    display_name = models.CharField(max_length=120, blank=True)

    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_INLINE)
    source_group = models.ForeignKey(
        "DispatchContactGroup",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaign_recipients",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "jid"],
                name="uniq_dispatch_recipient_per_campaign",
            )
        ]

    def __str__(self):
        return f"{self.jid} ({self.campaign_id})"


class DispatchCampaignQueueItem(models.Model):
    STATUS_QUEUED = "QUEUED"
    STATUS_SENDING = "SENDING"
    STATUS_SENT = "SENT"
    STATUS_DELIVERED = "DELIVERED"
    STATUS_READ = "READ"
    STATUS_PLAYED = "PLAYED"
    STATUS_FAILED = "FAILED"
    STATUS_CANCELED = "CANCELED"

    STATUS_CHOICES = [
        (STATUS_QUEUED, "Na fila"),
        (STATUS_SENDING, "Enviando"),
        (STATUS_SENT, "Enviado"),
        (STATUS_DELIVERED, "Entregue"),
        (STATUS_READ, "Lido"),
        (STATUS_PLAYED, "Reproduzido"),
        (STATUS_FAILED, "Falhou"),
        (STATUS_CANCELED, "Cancelado"),
    ]

    campaign = models.ForeignKey(
        "DispatchCampaign",
        on_delete=models.CASCADE,
        related_name="queue_items",
    )
    instance = models.ForeignKey(
        "Instance",
        on_delete=models.CASCADE,
        related_name="dispatch_queue_items",
    )
    recipient = models.ForeignKey(
        "DispatchCampaignRecipient",
        on_delete=models.CASCADE,
        related_name="queue_items",
    )

    step = models.PositiveIntegerField(default=1, help_text="Ordem de envio para este contato (1..N).")
    scheduled_at = models.DateTimeField(default=timezone.now, db_index=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED, db_index=True)
    attempts = models.PositiveIntegerField(default=0)

    template = models.ForeignKey(
        "DispatchMessageTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="queue_items",
    )
    rendered_body = models.TextField(blank=True)
    media_file = models.ForeignKey(
        "MediaFile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="queue_items",
    )

    wamid = models.CharField(max_length=120, null=True, blank=True, db_index=True)
    node_response = models.JSONField(default=dict, blank=True)
    error_text = models.TextField(blank=True)

    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    played_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scheduled_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "recipient", "step"],
                name="uniq_dispatch_queue_step_per_recipient",
            )
        ]
        indexes = [
            models.Index(fields=["instance", "status", "scheduled_at"]),
            models.Index(fields=["campaign", "status"]),
            models.Index(fields=["wamid"]),
        ]

    def __str__(self):
        return f"QueueItem {self.id} - {self.status}"


class DispatchInstanceState(models.Model):
    instance = models.OneToOneField(
        "Instance",
        on_delete=models.CASCADE,
        related_name="dispatch_state",
    )
    next_available_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_dispatched_at = models.DateTimeField(null=True, blank=True)

    last_campaign = models.ForeignKey(
        "DispatchCampaign",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="instance_states",
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Estado de Disparo da Instância"
        verbose_name_plural = "Estados de Disparo das Instâncias"

    def __str__(self):
        return f"{self.instance.name} - next={self.next_available_at}"
