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