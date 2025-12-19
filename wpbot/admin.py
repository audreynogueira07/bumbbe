from django.contrib import admin
from .models import WordpressBot, WordpressContact, WordpressMessage, WordpressMedia, WordpressApiErrorLog

@admin.register(WordpressApiErrorLog)
class WordpressApiErrorLogAdmin(admin.ModelAdmin):
    # Colunas exibidas na lista
    list_display = ('created_at', 'bot', 'endpoint', 'short_error_message', 'ip_address')
    
    # Filtros laterais
    list_filter = ('created_at', 'bot', 'endpoint')
    
    # Campos de busca
    search_fields = ('error_message', 'request_data', 'stack_trace', 'ip_address')
    
    # Deixar apenas leitura no admin para evitar alteração de logs de erro
    readonly_fields = ('created_at', 'bot', 'endpoint', 'request_data', 'error_message', 'stack_trace', 'ip_address')

    def short_error_message(self, obj):
        """Resumo da mensagem de erro para não quebrar o layout da lista"""
        return obj.error_message[:100] + '...' if len(obj.error_message) > 100 else obj.error_message
    short_error_message.short_description = 'Mensagem de Erro'

@admin.register(WordpressBot)
class WordpressBotAdmin(admin.ModelAdmin):
    # CORRECTION 1: Changed 'provider' to 'ai_provider'
    list_display = ('name', 'user', 'ai_provider', 'active', 'created_at')
    
    # CORRECTION 2: Changed 'provider' to 'ai_provider' and 'tone' to 'conversation_tone'
    list_filter = ('ai_provider', 'active', 'conversation_tone')
    
    search_fields = ('name', 'user__username', 'api_secret')
    readonly_fields = ('api_secret',) 

@admin.register(WordpressContact)
class WordpressContactAdmin(admin.ModelAdmin):
    # CORRECTION 3: Changed 'user_name' to 'name' and 'user_phone' to 'phone'
    list_display = ('name', 'phone', 'bot', 'last_interaction')
    
    # Updated search fields to match model fields as well
    search_fields = ('name', 'phone', 'session_uuid')
    list_filter = ('bot',)

@admin.register(WordpressMessage)
class WordpressMessageAdmin(admin.ModelAdmin):
    list_display = ('contact', 'sender', 'timestamp', 'short_content')
    list_filter = ('sender', 'timestamp')
    
    def short_content(self, obj):
        return obj.content[:50]
    short_content.short_description = 'Conteúdo'

@admin.register(WordpressMedia)
class WordpressMediaAdmin(admin.ModelAdmin):
    list_display = ('description', 'bot', 'media_type', 'created_at')
    list_filter = ('media_type', 'bot')