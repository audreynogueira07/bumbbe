from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe  # <--- IMPORTANTE: Importação adicionada
from .models import (
    Chatbot, 
    ChatbotMedia, 
    ChatbotContact, 
    ChatbotPlan, 
    UserSubscription
)

# ==================================================
# 1. ADMINISTRAÇÃO DE PLANOS E ASSINATURAS
# ==================================================

@admin.register(ChatbotPlan)
class ChatbotPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'periodicity', 'max_chatbots', 'max_conversations', 'is_active')
    list_filter = ('periodicity', 'is_active')
    search_fields = ('name',)
    ordering = ('price',)

@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'active', 'expires_at', 'status_badge')
    list_filter = ('active', 'plan')
    search_fields = ('user__username', 'user__email')
    autocomplete_fields = ('user', 'plan')

    def status_badge(self, obj):
        # CORREÇÃO AQUI: Usando mark_safe para HTML estático
        if obj.active:
            return mark_safe('<span style="color:green; font-weight:bold;">ATIVO</span>')
        return mark_safe('<span style="color:red;">INATIVO</span>')
    status_badge.short_description = "Status"


# ==================================================
# 2. INLINES (MÍDIA E CONTATOS)
# ==================================================

class ChatbotMediaInline(admin.TabularInline):
    model = ChatbotMedia
    extra = 1
    fields = ('file', 'media_type', 'description', 'send_rules', 'is_accessible_by_ai')
    verbose_name = "Arquivo de Mídia"
    verbose_name_plural = "Arquivos de Mídia (Base de Conhecimento)"

class ChatbotContactInline(admin.TabularInline):
    model = ChatbotContact
    extra = 0
    # Apenas leitura para visualizar contatos dentro do Bot, sem editar
    fields = ('remote_jid', 'push_name', 'last_interaction', 'is_blocked')
    readonly_fields = ('remote_jid', 'push_name', 'last_interaction', 'is_blocked')
    show_change_link = True
    can_delete = False
    classes = ('collapse',) # Começa fechado para não poluir a tela


# ==================================================
# 3. ADMINISTRAÇÃO DE CONTATOS (VISÃO GERAL)
# ==================================================

@admin.register(ChatbotContact)
class ChatbotContactAdmin(admin.ModelAdmin):
    list_display = ('push_name', 'remote_jid', 'chatbot_link', 'last_interaction', 'is_blocked')
    list_filter = ('is_blocked', 'chatbot__name')
    search_fields = ('remote_jid', 'push_name', 'chatbot__name')
    readonly_fields = ('first_interaction', 'last_interaction')

    def chatbot_link(self, obj):
        return obj.chatbot.name
    chatbot_link.short_description = "Bot Associado"


# ==================================================
# 4. ADMINISTRAÇÃO DO CHATBOT (PRINCIPAL)
# ==================================================

@admin.register(Chatbot)
class ChatbotAdmin(admin.ModelAdmin):
    list_display = (
        'name', 
        'user_info', 
        'active', 
        'ai_provider', 
        'usage_status', 
        'token_usage_display'
    )
    list_filter = ('active', 'ai_provider', 'segment', 'token_usage_type')
    search_fields = ('name', 'user__username', 'company_name')
    autocomplete_fields = ('user', 'instance')
    inlines = [ChatbotMediaInline, ChatbotContactInline]
    
    # Organização visual dos campos em abas/seções
    fieldsets = (
        ('Status e Conexão', {
            'fields': (
                ('active', 'user'),
                ('name', 'instance'),
            )
        }),
        ('Identidade da Empresa', {
            'fields': (
                ('company_name', 'company_website'),
                ('sector', 'segment'),
                'company_summary',
            ),
            'classes': ('wide',),
        }),
        ('Comportamento e Respostas', {
            'fields': (
                ('conversation_tone', 'business_hours'),
                ('trigger_on_groups', 'trigger_on_unknown'),
                ('allow_audio_response', 'allow_media_response'),
                ('simulate_typing', 'typing_time_min', 'typing_time_max'),
            )
        }),
        ('Memória e Inteligência Artificial', {
            'fields': (
                ('ai_provider', 'model_name'),
                'api_key',
                ('use_history', 'history_limit'),
                'context',
                'skills',
                'extra_instructions',
            )
        }),
        ('Transferência de Atendimento (Setores)', {
            'fields': (
                ('transf_1_active', 'transf_1_label', 'transf_1_number'),
                ('transf_2_active', 'transf_2_label', 'transf_2_number'),
                ('transf_3_active', 'transf_3_label', 'transf_3_number'),
                ('transf_4_active', 'transf_4_label', 'transf_4_number'),
                ('transf_5_active', 'transf_5_label', 'transf_5_number'),
            ),
            'classes': ('collapse',),
            'description': "Configure até 5 departamentos para transbordo humano."
        }),
        ('Métricas e Limites (Plano & Tokens)', {
            'fields': (
                ('conversations_count', 'last_reset_date'),
                ('token_usage_type', 'token_limit', 'current_tokens_used'),
            ),
            'classes': ('collapse',),
            'description': "Monitoramento de consumo. Cuidado ao alterar manualmente."
        }),
        ('Metadados', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    readonly_fields = ('created_at', 'updated_at', 'current_tokens_used', 'conversations_count', 'last_reset_date')

    def user_info(self, obj):
        """Exibe o usuário e qual plano ele possui"""
        sub = getattr(obj.user, 'chatbot_subscription', None)
        # Proteção extra caso a assinatura exista mas o plano tenha sido deletado
        plan_name = "Sem Plano"
        if sub and hasattr(sub, 'plan') and sub.plan:
             plan_name = sub.plan.name
             
        return f"{obj.user.username} ({plan_name})"
    user_info.short_description = "Dono / Plano"


    def usage_status(self, obj):
        """Mostra o uso do plano de conversas"""
        sub = getattr(obj.user, 'chatbot_subscription', None)
        limit = 0
        if sub and hasattr(sub, 'plan') and sub.plan:
            limit = sub.plan.max_conversations
        
        if limit > 999999: # Assumindo infinito
            return f"{obj.conversations_count} (∞)"
        
        color = "green"
        if limit > 0 and (obj.conversations_count / limit) > 0.9:
            color = "red"
        
        # Aqui o format_html FUNCIONA porque estamos passando argumentos (color, count, limit)
        return format_html(
            '<span style="color: {};">{} / {}</span>',
            color, obj.conversations_count, limit
        )
    usage_status.short_description = "Conversas (Mês)"

    def token_usage_display(self, obj):
        if obj.token_usage_type == 'infinity':
            return "Ilimitado"
        return f"{obj.current_tokens_used} / {obj.token_limit}"
    token_usage_display.short_description = "Tokens"
    