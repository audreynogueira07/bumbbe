import os
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

# Ajuste os imports conforme a estrutura do seu projeto
try:
    from fillow.models import Instance, Message 
except ImportError:
    # Fallback apenas para evitar erro de linting se o ambiente não estiver configurado
    Instance = 'instances.Instance'
    Message = 'instances.Message'

# ==========================================
# 1. MODELO DE PLANOS (Novo)
# ==========================================

class ChatbotPlan(models.Model):
    """
    Define as regras e limites do plano contratado.
    """
    PERIODICITY_CHOICES = [
        ('infinity', 'Sem Limites (Infinito)'),
        ('daily', 'Diário'),
        ('monthly', 'Mensal'),
        ('quarterly', 'Trimestral'),
        ('semiannual', 'Semestral'),
        ('yearly', 'Anual'),
    ]

    name = models.CharField(max_length=100, verbose_name="Nome do Plano")
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Preço")
    
    # Limites
    max_chatbots = models.PositiveIntegerField(
        default=1, 
        verbose_name="Máx. Chatbots",
        help_text="Quantos bots o cliente pode criar."
    )
    
    max_conversations = models.PositiveIntegerField(
        default=1000, 
        verbose_name="Máx. Conversas",
        help_text="Limite de conversas dentro do período escolhido."
    )
    
    periodicity = models.CharField(
        max_length=20, 
        choices=PERIODICITY_CHOICES, 
        default='monthly',
        verbose_name="Renovação do Limite"
    )

    is_active = models.BooleanField(default=True, verbose_name="Ativo?")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Plano de Chatbot"
        verbose_name_plural = "Planos de Chatbot"

    def __str__(self):
        return f"{self.name} ({self.get_periodicity_display()})"


class UserSubscription(models.Model):
    """
    Liga o Usuário ao Plano. Isso evita ter que mexer no model de User nativo.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='chatbot_subscription',
        verbose_name="Usuário"
    )
    plan = models.ForeignKey(
        ChatbotPlan, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name="Plano Atual"
    )
    active = models.BooleanField(default=True, verbose_name="Assinatura Ativa?")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="Expira em")

    class Meta:
        verbose_name = "Assinatura do Usuário"
        verbose_name_plural = "Assinaturas dos Usuários"

    def __str__(self):
        plan_name = self.plan.name if self.plan else "Sem Plano"
        return f"{self.user} - {plan_name}"


# ==========================================
# 2. MODELO CHATBOT (Principal)
# ==========================================

class Chatbot(models.Model):
    """
    Modelo principal para configuração dos Chatbots.
    """

    # --- OPÇÕES DE SELEÇÃO ---
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

    SEGMENT_CHOICES = [
        ('retail', 'Varejo / Loja'),
        ('tech', 'Tecnologia / Software'),
        ('health', 'Saúde / Clínica'),
        ('food', 'Alimentação / Restaurante'),
        ('real_estate', 'Imobiliária'),
        ('education', 'Educação / Cursos'),
        ('services', 'Prestação de Serviços'),
        ('other', 'Outro'),
    ]

    DEPT_CHOICES = [
        ('support', 'Suporte Técnico'),
        ('sales', 'Vendas / Comercial'),
        ('financial', 'Financeiro'),
        ('attendance', 'Atendimento Geral'),
        ('scheduling', 'Agendamento'),
        ('other', 'Outro'),
    ]

    TOKEN_USAGE_CHOICES = [
        ('daily', 'Diário'),
        ('monthly', 'Mensal'),
        ('lifetime', 'Total Vitalício'),
        ('infinity', 'Sem Limites'),
    ]

    # --- DADOS BÁSICOS ---
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name="chatbots",
        verbose_name="Dono"
    )
    
    instance = models.OneToOneField(
        Instance, 
        on_delete=models.CASCADE, 
        related_name="chatbot_config",
        verbose_name="Instância Conectada"
    )
    
    name = models.CharField(max_length=100, verbose_name="Nome Interno do Bot")
    active = models.BooleanField(default=True, verbose_name="Bot Ativo?")

    # --- IDENTIDADE DA EMPRESA ---
    company_name = models.CharField(max_length=100, verbose_name="Nome da Empresa")
    company_website = models.URLField(blank=True, null=True, verbose_name="Site da Empresa")
    sector = models.CharField(max_length=100, verbose_name="Setor de Atuação", help_text="Ex: Moda, Odontologia")
    segment = models.CharField(max_length=50, choices=SEGMENT_CHOICES, default='other', verbose_name="Segmento")
    company_summary = models.TextField(verbose_name="Resumo da Empresa", help_text="O que a empresa faz, produtos, missão, etc.")
    
    # --- COMPORTAMENTO ---
    conversation_tone = models.CharField(max_length=50, choices=TONE_CHOICES, default='friendly', verbose_name="Tom da Conversa")
    business_hours = models.TextField(verbose_name="Horário de Atendimento", help_text="Ex: Seg-Sex das 09h às 18h.")
    
    trigger_on_groups = models.BooleanField(default=False, verbose_name="Responder em Grupos?")
    trigger_on_unknown = models.BooleanField(default=True, verbose_name="Responder Números Desconhecidos?")
    simulate_typing = models.BooleanField(default=True, verbose_name="Simular Digitação?")
    typing_time_min = models.PositiveIntegerField(default=2000, verbose_name="Tempo Min (ms)")
    typing_time_max = models.PositiveIntegerField(default=5000, verbose_name="Tempo Max (ms)")
    allow_audio_response = models.BooleanField(default=True, verbose_name="Pode enviar Áudio?")
    allow_media_response = models.BooleanField(default=True, verbose_name="Pode enviar Mídia?")

    # --- MEMÓRIA E CONTEXTO ---
    use_history = models.BooleanField(
        default=True, 
        verbose_name="Lembrar Conversa Anterior?",
        help_text="Se ativo, o bot lerá as últimas mensagens para manter o contexto."
    )
    history_limit = models.IntegerField(
        default=10, 
        verbose_name="Qtd. Mensagens de Memória",
        help_text="Quantas mensagens passadas o bot deve analisar?"
    )

    # --- TRANSFERÊNCIA DE ATENDIMENTO (5 OPÇÕES) ---
    transf_1_active = models.BooleanField(default=False, verbose_name="Ativar Transf. 1")
    transf_1_label = models.CharField(max_length=50, choices=DEPT_CHOICES, blank=True, null=True, verbose_name="Setor 1")
    transf_1_number = models.CharField(max_length=30, blank=True, null=True, verbose_name="WhatsApp 1")
    
    transf_2_active = models.BooleanField(default=False, verbose_name="Ativar Transf. 2")
    transf_2_label = models.CharField(max_length=50, choices=DEPT_CHOICES, blank=True, null=True, verbose_name="Setor 2")
    transf_2_number = models.CharField(max_length=30, blank=True, null=True, verbose_name="WhatsApp 2")

    transf_3_active = models.BooleanField(default=False, verbose_name="Ativar Transf. 3")
    transf_3_label = models.CharField(max_length=50, choices=DEPT_CHOICES, blank=True, null=True, verbose_name="Setor 3")
    transf_3_number = models.CharField(max_length=30, blank=True, null=True, verbose_name="WhatsApp 3")

    transf_4_active = models.BooleanField(default=False, verbose_name="Ativar Transf. 4")
    transf_4_label = models.CharField(max_length=50, choices=DEPT_CHOICES, blank=True, null=True, verbose_name="Setor 4")
    transf_4_number = models.CharField(max_length=30, blank=True, null=True, verbose_name="WhatsApp 4")

    transf_5_active = models.BooleanField(default=False, verbose_name="Ativar Transf. 5")
    transf_5_label = models.CharField(max_length=50, choices=DEPT_CHOICES, blank=True, null=True, verbose_name="Setor 5")
    transf_5_number = models.CharField(max_length=30, blank=True, null=True, verbose_name="WhatsApp 5")

    # --- CONFIGURAÇÃO DE IA ---
    ai_provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default='gemini', verbose_name="Provedor de IA")
    model_name = models.CharField(max_length=50, default='gemini-pro', verbose_name="Modelo")
    api_key = models.CharField(max_length=255, verbose_name="API Key")
    
    context = models.TextField(verbose_name="Contexto do Sistema (Prompt Inicial)", blank=True, null=True) 
    skills = models.TextField(verbose_name="Habilidades & Instruções", blank=True, null=True) 
    extra_instructions = models.TextField(verbose_name="Instruções Extras (Prompt Manual)", blank=True)
    
    # --- CONTROLE DE LIMITES (PLANO) ---
    conversations_count = models.IntegerField(default=0, verbose_name="Conversas no Período Atual")
    last_reset_date = models.DateTimeField(default=timezone.now)

    # --- CONTROLE DE CUSTOS (TOKENS - Extras) ---
    current_tokens_used = models.IntegerField(
        default=0, 
        verbose_name="Total de Tokens Consumidos"
    )
    
    token_usage_type = models.CharField(
        max_length=20, 
        choices=TOKEN_USAGE_CHOICES, 
        default='infinity', 
        verbose_name="Tipo de Limite (Token)"
    )
    
    token_limit = models.IntegerField(
        default=0, 
        verbose_name="Limite Máximo de Tokens",
        help_text="Defina 0 para ilimitado, caso o tipo permita."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Conexão Chatbot"
        verbose_name_plural = "Conexões Chatbot"

    def __str__(self):
        return f"{self.name} - {self.company_name}"

    def clean(self):
        """
        Valida a criação baseada no Plano do Usuário.
        """
        # 1. Validação de Limite de Criação (Só se for novo objeto)
        if not self.pk:
            subscription = getattr(self.user, 'chatbot_subscription', None)
            
            if subscription and subscription.plan and subscription.active:
                current_count = Chatbot.objects.filter(user=self.user).count()
                max_allowed = subscription.plan.max_chatbots
                
                if current_count >= max_allowed:
                    raise ValidationError(
                        f"Seu plano '{subscription.plan.name}' permite apenas {max_allowed} chatbots. "
                        "Faça um upgrade para criar mais."
                    )
            else:
                # Se não tiver assinatura, decide se bloqueia ou permite. 
                # Aqui estamos bloqueando por segurança:
                # raise ValidationError("Você precisa de um plano ativo para criar um chatbot.")
                pass 

        # 2. Validação lógica dos tempos
        if self.typing_time_max < self.typing_time_min:
            raise ValidationError("O tempo máximo de digitação não pode ser menor que o mínimo.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def check_limit(self):
        """
        Verifica se o bot pode responder baseado no plano e reseta o contador se necessário.
        Retorna True se permitido, False se bloqueado.
        """
        subscription = getattr(self.user, 'chatbot_subscription', None)

        # Sem plano = Bloqueia ou usa padrão (aqui bloqueia false)
        if not subscription or not subscription.plan or not subscription.active:
            return False

        plan = subscription.plan
        
        # Se for infinito, passa direto
        if plan.periodicity == 'infinity':
            return True

        now = timezone.now()
        last = self.last_reset_date
        should_reset = False

        # Lógica de Reset
        if plan.periodicity == 'daily':
            if last.date() != now.date():
                should_reset = True
        
        elif plan.periodicity == 'monthly':
            if last.month != now.month or last.year != now.year:
                should_reset = True

        elif plan.periodicity == 'quarterly':
            current_q = (now.month - 1) // 3 + 1
            last_q = (last.month - 1) // 3 + 1
            if current_q != last_q or last.year != now.year:
                should_reset = True
        
        elif plan.periodicity == 'semiannual':
            current_s = 1 if now.month <= 6 else 2
            last_s = 1 if last.month <= 6 else 2
            if current_s != last_s or last.year != now.year:
                should_reset = True
        
        elif plan.periodicity == 'yearly':
            if last.year != now.year:
                should_reset = True

        if should_reset:
            self.conversations_count = 0
            self.last_reset_date = now
            self.save(update_fields=['conversations_count', 'last_reset_date'])

        return self.conversations_count < plan.max_conversations

    def check_token_limit(self):
        """
        Verifica limites técnicos de tokens (independente do plano de conversas).
        """
        if self.token_usage_type == 'infinity':
            return True
            
        if self.token_limit > 0 and self.current_tokens_used >= self.token_limit:
            return False
            
        return True


# ==========================================
# 3. CONTATOS E MÍDIAS
# ==========================================

class ChatbotContact(models.Model):
    chatbot = models.ForeignKey(Chatbot, on_delete=models.CASCADE, related_name="contacts")
    remote_jid = models.CharField(max_length=50, verbose_name="Número (JID)")
    push_name = models.CharField(max_length=100, blank=True, null=True, verbose_name="Nome no WhatsApp")
    
    first_interaction = models.DateTimeField(auto_now_add=True, verbose_name="Primeira Interação")
    last_interaction = models.DateTimeField(auto_now=True, verbose_name="Última Interação")
    
    is_blocked = models.BooleanField(default=False, verbose_name="Bloqueado pelo Bot?")
    notes = models.TextField(blank=True, verbose_name="Anotações Internas")

    class Meta:
        verbose_name = "Contato do Chatbot"
        verbose_name_plural = "Contatos do Chatbot"
        unique_together = ('chatbot', 'remote_jid')

    def __str__(self):
        return f"{self.push_name or 'Desconhecido'} ({self.remote_jid})"

    @property
    def history(self):
        return Message.objects.filter(
            instance=self.chatbot.instance, 
            remote_jid=self.remote_jid
        ).order_by('timestamp')


def chatbot_media_path(instance, filename):
    return f'chatbot_media/user_{instance.chatbot.user.id}/bot_{instance.chatbot.id}/{filename}'

class ChatbotMedia(models.Model):
    MEDIA_TYPES = (
        ('image', 'Imagem'),
        ('audio', 'Áudio'),
        ('video', 'Vídeo'),
        ('document', 'Arquivo/Documento'),
        ('sticker', 'Figurinha'),
    )

    chatbot = models.ForeignKey(Chatbot, on_delete=models.CASCADE, related_name="medias")
    file = models.FileField(upload_to=chatbot_media_path, verbose_name="Arquivo")
    media_type = models.CharField(max_length=20, choices=MEDIA_TYPES, default='document')
    
    is_accessible_by_ai = models.BooleanField(default=True, verbose_name="Acessível pela IA?")
    description = models.TextField(verbose_name="Descrição/Palavras-chave")
    
    send_rules = models.TextField(
        verbose_name="Regras de Envio (Quando enviar?)", 
        blank=True, 
        null=True,
        help_text="Explique para a IA quando enviar este arquivo."
    )
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mídia do Chatbot"
        verbose_name_plural = "Mídias do Chatbot"

# --- SIGNALS PARA LIMPEZA DE ARQUIVOS ---

@receiver(post_delete, sender=ChatbotMedia)
def delete_chatbot_media_file(sender, instance, **kwargs):
    if instance.file:
        try:
            if os.path.isfile(instance.file.path):
                os.remove(instance.file.path)
        except Exception:
            pass

@receiver(pre_save, sender=ChatbotMedia)
def delete_old_file_on_update(sender, instance, **kwargs):
    if not instance.pk:
        return
    try:
        old_instance = ChatbotMedia.objects.get(pk=instance.pk)
    except ChatbotMedia.DoesNotExist:
        return
    old_file = old_instance.file
    new_file = instance.file
    if old_file and old_file != new_file:
        try:
            if os.path.isfile(old_file.path):
                os.remove(old_file.path)
        except Exception:
            pass