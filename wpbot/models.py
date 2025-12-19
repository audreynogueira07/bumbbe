import uuid
import os
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

# ==========================================
# 1. MODELO PRINCIPAL (BOT WORDPRESS)
# ==========================================

class WordpressBot(models.Model):
    """
    Bot exclusivo para integração via API com WordPress.
    """
    PROVIDER_CHOICES = (
        ('openai', 'OpenAI (GPT)'),
        ('gemini', 'Google (Gemini)'),
    )

    TONE_CHOICES = [
        ('formal', 'Formal e Respeitoso'),
        ('casual', 'Casual e Descontraído'),
        ('friendly', 'Amigável e Empático'),
        ('enthusiastic', 'Entusiasta e Energético'),
        ('professional', 'Profissional e Direto'),
    ]

    # Vínculo com usuário (Dono do bot)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name="wordpress_bots"
    )

    # Identificação e Segurança
    name = models.CharField(max_length=100, verbose_name="Nome do Bot")
    api_secret = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, verbose_name="Chave de API (Secret)")
    active = models.BooleanField(default=True, verbose_name="Ativo?")

    # Identidade
    company_name = models.CharField(max_length=100, verbose_name="Nome da Empresa")
    company_website = models.URLField(blank=True, null=True, verbose_name="Site")
    company_summary = models.TextField(verbose_name="Resumo da Empresa")
    business_hours = models.TextField(verbose_name="Horário de Atendimento", blank=True)
    
    # Comportamento
    conversation_tone = models.CharField(max_length=50, choices=TONE_CHOICES, default='friendly')
    
    # IA Configuration
    ai_provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default='gemini')
    model_name = models.CharField(max_length=50, default='gemini-pro', verbose_name="Modelo IA")
    api_key = models.CharField(max_length=255, verbose_name="API Key da IA")
    
    context = models.TextField(verbose_name="Contexto (Prompt Sistema)", blank=True)
    skills = models.TextField(verbose_name="Habilidades", blank=True)

    # Memória
    use_history = models.BooleanField(default=True, verbose_name="Usar Memória?")
    history_limit = models.IntegerField(default=10, verbose_name="Limite de Mensagens")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.company_name})"


# ==========================================
# 2. CONTATOS E MENSAGENS (Histórico Próprio)
# ==========================================

class WordpressContact(models.Model):
    """
    Representa o visitante do site.
    """
    bot = models.ForeignKey(WordpressBot, on_delete=models.CASCADE, related_name="contacts")
    
    # Identificador único vindo do plugin (pode ser cookie ID ou session ID)
    session_uuid = models.CharField(max_length=100, verbose_name="ID da Sessão/Cookie")
    
    # Dados capturados
    name = models.CharField(max_length=100, blank=True, null=True, verbose_name="Nome")
    phone = models.CharField(max_length=30, blank=True, null=True, verbose_name="WhatsApp/Telefone")
    email = models.EmailField(blank=True, null=True, verbose_name="Email")
    
    # Estado do fluxo de captura de dados (para pedir nome/telefone no inicio)
    # 0 = Cadastro Completo / IA Livre
    # 1 = Esperando Nome
    # 2 = Esperando Telefone
    input_state = models.IntegerField(default=1, verbose_name="Estado de Entrada") 

    created_at = models.DateTimeField(auto_now_add=True)
    last_interaction = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('bot', 'session_uuid')

    def __str__(self):
        return f"{self.name or 'Visitante'} ({self.session_uuid})"


class WordpressMessage(models.Model):
    """
    Armazena o chat, já que não temos o WhatsApp para isso.
    """
    SENDER_CHOICES = (
        ('user', 'Usuário/Visitante'),
        ('bot', 'Bot/IA'),
    )
    
    contact = models.ForeignKey(WordpressContact, on_delete=models.CASCADE, related_name="messages")
    sender = models.CharField(max_length=10, choices=SENDER_CHOICES)
    content = models.TextField()
    media_url = models.URLField(blank=True, null=True) # Se o bot enviou mídia
    
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.sender}: {self.content[:30]}"


# ==========================================
# 3. MÍDIAS (Base de Conhecimento)
# ==========================================

def wp_media_path(instance, filename):
    return f'wp_bot_media/bot_{instance.bot.id}/{filename}'

class WordpressMedia(models.Model):
    MEDIA_TYPES = (
        ('image', 'Imagem'),
        ('audio', 'Áudio'),
        ('video', 'Vídeo'),
        ('document', 'Arquivo/PDF'),
    )

    bot = models.ForeignKey(WordpressBot, on_delete=models.CASCADE, related_name="medias")
    file = models.FileField(upload_to=wp_media_path)
    media_type = models.CharField(max_length=20, choices=MEDIA_TYPES, default='document')
    description = models.TextField(verbose_name="Descrição")
    send_rules = models.TextField(verbose_name="Quando enviar?", blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.media_type} - {self.description}"

@receiver(post_delete, sender=WordpressMedia)
def delete_wp_media_file(sender, instance, **kwargs):
    if instance.file:
        try:
            if os.path.isfile(instance.file.path):
                os.remove(instance.file.path)
        except: pass
        
        
class WordpressApiErrorLog(models.Model):
    """
    Registra falhas de autenticação, erros de validação e exceções internas da API.
    """
    bot = models.ForeignKey(WordpressBot, on_delete=models.SET_NULL, null=True, blank=True)
    endpoint = models.CharField(max_length=255, default='/api/chat/')
    request_data = models.TextField(verbose_name="Dados Recebidos")
    error_message = models.TextField(verbose_name="Mensagem de Erro")
    stack_trace = models.TextField(verbose_name="Stack Trace", blank=True, null=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Erro em {self.created_at} - Bot: {self.bot}"