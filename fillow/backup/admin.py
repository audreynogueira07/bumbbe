from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from .models import Usuario, Plan, Instance, WebhookConfig, MediaFile
from chatbot.models import Chatbot, ChatbotMedia

# ==============================================================================
# INLINES (Vistas aninhadas)
# ==============================================================================

class WebhookInline(admin.StackedInline):
    """Permite editar o Webhook diretamente dentro da tela da Instância."""
    model = WebhookConfig
    can_delete = False
    verbose_name_plural = 'Configuração de Webhook'
    fields = ('url', 'secret', ('send_messages', 'send_ack', 'send_presence'))
    readonly_fields = ('secret', 'created_at')

class InstanceInline(admin.TabularInline):
    """Permite visualizar as instâncias do usuário dentro da tela do Usuário."""
    model = Instance
    fk_name = 'owner'
    extra = 0
    can_delete = False 
    fields = ('name', 'phone_connected', 'status_badge', 'updated_at')
    readonly_fields = ('name', 'phone_connected', 'status_badge', 'updated_at')
    show_change_link = True 

    def status_badge(self, obj):
        colors = {
            'CONNECTED': 'green', 'DISCONNECTED': 'red', 'QR_SCANNED': 'orange',
            'CREATED': 'gray', 'BAN': 'black',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 10px; font-weight: bold;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'

class MediaFileInline(admin.TabularInline):
    """Lista os arquivos enviados pelo usuário."""
    model = MediaFile
    fk_name = 'owner'
    extra = 0
    can_delete = True
    fields = ('preview', 'original_name', 'media_type', 'file_link', 'created_at')
    readonly_fields = ('preview', 'file_link', 'created_at', 'original_name', 'media_type')
    ordering = ('-created_at',)

    def preview(self, obj):
        if obj.media_type == 'image' and obj.file:
            return format_html('<img src="{}" style="width: 40px; height: 40px; object-fit: cover; border-radius: 4px;" />', obj.file.url)
        return "📄"
    preview.short_description = "Prévia"

    def file_link(self, obj):
        if obj.file:
            return format_html('<a href="{}" target="_blank">Abrir Arquivo ↗</a>', obj.file.url)
        return "-"
    file_link.short_description = "Link"

class ChatbotInline(admin.StackedInline):
    """Permite visualizar/editar o chatbot dentro da tela da Instância ou Usuário."""
    model = Chatbot
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ('name', 'active', 'ai_provider', 'model_name')
    readonly_fields = ('name', 'active', 'ai_provider', 'model_name') # Apenas visualização rápida

# ==============================================================================
# ADMINS PRINCIPAIS
# ==============================================================================

@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'duration_display', 'max_instances', 'formatted_price', 'users_count')
    search_fields = ('name',)
    ordering = ('price',)
    list_editable = ('max_instances',)
    
    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'price', 'max_instances', 'monthly_conversations_limit')
        }),
        ('Vigência do Plano', {
            'fields': (('duration_value', 'duration_type'),),
            'description': 'Defina por quanto tempo o plano é válido (ex: 1 Mês, 365 Dias, Vitalício).'
        }),
    )

    def formatted_price(self, obj):
        return f"R$ {obj.price}"
    formatted_price.short_description = 'Preço'
    formatted_price.admin_order_field = 'price'

    def duration_display(self, obj):
        if obj.duration_type == 'lifetime':
            return "♾️ Vitalício"
        return f"{obj.duration_value} {obj.get_duration_type_display()}"
    duration_display.short_description = 'Duração'

    def users_count(self, obj):
        return obj.users.count()
    users_count.short_description = 'Clientes'

@admin.register(MediaFile)
class MediaFileAdmin(admin.ModelAdmin):
    list_display = ('preview_thumb', 'original_name', 'media_type_badge', 'owner_link', 'created_at', 'open_action')
    list_filter = ('media_type', 'created_at')
    search_fields = ('original_name', 'owner__username', 'owner__email')
    readonly_fields = ('id', 'file_url_display', 'created_at', 'owner', 'media_type')

    def preview_thumb(self, obj):
        if obj.media_type == 'image' and obj.file:
            return format_html('<img src="{}" style="max-height: 50px; max-width: 50px; border-radius: 5px; border: 1px solid #ddd;" />', obj.file.url)
        icons = {
            'video': '🎥', 'audio': '🎵', 'document': '📁', 'sticker': '💟'
        }
        return icons.get(obj.media_type, '📄')
    preview_thumb.short_description = "Mídia"

    def media_type_badge(self, obj):
        colors = {
            'image': '#17a2b8', 'video': '#6610f2', 'audio': '#e83e8c',
            'document': '#6c757d', 'sticker': '#fd7e14'
        }
        color = colors.get(obj.media_type, '#333')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.get_media_type_display()
        )
    media_type_badge.short_description = "Tipo"

    def owner_link(self, obj):
        return format_html('<a href="/admin/fillow/usuario/{}/change/">{}</a>', obj.owner.id, obj.owner.username)
    owner_link.short_description = 'Proprietário'

    def open_action(self, obj):
        if obj.file:
            return format_html(
                '<a class="button" href="{}" target="_blank" style="background-color: #28a745; color: white; padding: 3px 10px; border-radius: 4px;">Abrir</a>',
                obj.file.url
            )
        return "-"
    open_action.short_description = "Ação"

    def file_url_display(self, obj):
        return obj.file.url if obj.file else "-"
    file_url_display.short_description = "URL do Arquivo"

@admin.register(Usuario)
class CustomUserAdmin(UserAdmin):
    """
    Painel de Usuário Enriquecido com controle de Assinatura e Arquivos.
    """
    inlines = [InstanceInline, MediaFileInline, ChatbotInline]
    
    list_display = (
        'username', 
        'get_plan_name', 
        'get_plan_status',
        'phone_number', 
        'api', 
        'get_instances_count', 
        'is_active'
    )
    
    list_filter = ('plan', 'is_active', 'api', 'agendamento', 'chatbot', 'date_joined', 'plan_end_date')
    search_fields = ('username', 'email', 'phone_number', 'api_key', 'cpf')
    ordering = ('-date_joined',)
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('Personal info'), {'fields': ('first_name', 'cpf', 'last_name', 'email', 'phone_number')}),
        
        # Configurações do SaaS (Atualizado com Datas)
        (_('Assinatura e Plano'), {
            'fields': ('plan', ('plan_start_date', 'plan_end_date'), 'api_key'),
            'description': 'Ao alterar o plano, as datas serão recalculadas automaticamente ao salvar.'
        }),
        
        (_('Acesso aos Módulos'), {
            'fields': ('api', 'agendamento', 'chatbot'),
            'description': 'Marque as funcionalidades que este usuário pode utilizar.'
        }),

        (_('Permissions'), {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
            'classes': ('collapse',),
        }),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )
    readonly_fields = ('api_key', 'last_login', 'date_joined')

    def save_model(self, request, obj, form, change):
        """
        Sobrescreve o salvamento para calcular a data de vencimento
        automaticamente se o plano for alterado pelo Admin.
        """
        # Se o campo 'plan' foi modificado no formulário
        if 'plan' in form.changed_data and obj.plan:
            # Chama o método do model que calcula a data
            obj.assign_plan(obj.plan)
        
        super().save_model(request, obj, form, change)

    def get_plan_name(self, obj):
        if obj.plan:
            return format_html('<span style="color: #2c3e50; font-weight: bold;">{}</span>', obj.plan.name)
        return "-"
    get_plan_name.short_description = 'Plano'
    get_plan_name.admin_order_field = 'plan'

    def get_plan_status(self, obj):
        """Badge visual para indicar se a assinatura está válida."""
        if not obj.plan:
            return format_html('<span style="color: gray;">{}</span>', 'Sem Plano')
        
        # Lógica visual
        is_valid = obj.is_plan_valid
        
        if obj.plan.duration_type == 'lifetime':
             return format_html('<span style="background-color: #17a2b8; color: white; padding: 3px 8px; border-radius: 4px; font-size: 11px;">{}</span>', 'Vitalício')

        if is_valid:
            if obj.plan_end_date:
                delta = obj.plan_end_date - timezone.now()
                if delta.days < 5:
                    # Alerta se faltar menos de 5 dias
                    return format_html('<span style="color: orange; font-weight: bold;">Expira em {} dias</span>', delta.days)
            
            return format_html('<span style="background-color: #28a745; color: white; padding: 3px 8px; border-radius: 4px; font-size: 11px;">{}</span>', 'Ativo')
        else:
            return format_html('<span style="background-color: #dc3545; color: white; padding: 3px 8px; border-radius: 4px; font-size: 11px;">{}</span>', 'Vencido')

    get_plan_status.short_description = 'Status Assinatura'

    def get_instances_count(self, obj):
        count = obj.instances.count()
        limit = obj.plan.max_instances if obj.plan else 0
        color = 'green' if count < limit else 'red'
        return format_html('<span style="color: {};">{} / {}</span>', color, count, limit)
    get_instances_count.short_description = 'Uso Inst.'

@admin.register(Instance)
class InstanceAdmin(admin.ModelAdmin):
    inlines = [WebhookInline, ChatbotInline]
    list_display = ('name', 'owner_link', 'owner_plan_status', 'phone_display', 'status_badge', 'battery_display', 'updated_at')
    list_filter = ('status', 'platform', 'created_at', ('owner__plan', admin.RelatedOnlyFieldListFilter))
    search_fields = ('name', 'session_id', 'phone_connected', 'owner__username', 'owner__email', 'token')
    readonly_fields = ('id', 'session_id', 'token', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Identificação', {
            'fields': ('id', 'name', 'owner', 'created_at')
        }),
        ('Dados Técnicos', {
            'fields': ('session_id', 'token'),
            'classes': ('collapse',),
        }),
        ('Estado da Conexão', {
            'fields': ('status', 'phone_connected', 'platform', 'battery_level', 'updated_at')
        }),
    )

    def owner_link(self, obj):
        return format_html('<a href="/admin/fillow/usuario/{}/change/">{}</a>', obj.owner.id, obj.owner.username)
    owner_link.short_description = 'Cliente'
    owner_link.admin_order_field = 'owner'

    def owner_plan_status(self, obj):
        """Mostra se o dono da instância está com a conta em dia"""
        if obj.owner.is_plan_valid:
             return format_html('<span style="color: green;">{}</span>', '✔')
        return format_html('<span style="color: red; font-weight: bold;">{}</span>', '✖ Vencido')
    owner_plan_status.short_description = 'Pagamento'

    def phone_display(self, obj):
        if obj.phone_connected:
            phone = obj.phone_connected.split('@')[0]
            return format_html('<a href="https://wa.me/{}" target="_blank">{}</a>', phone, obj.phone_connected)
        return "Não conectado"
    phone_display.short_description = 'WhatsApp'

    def status_badge(self, obj):
        colors = {
            'CONNECTED': '#28a745', 'DISCONNECTED': '#dc3545',
            'QR_SCANNED': '#ffc107', 'CREATED': '#6c757d', 'BAN': '#343a40',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<div style="background-color: {}; color: white; padding: 4px 10px; border-radius: 15px; text-align: center; font-weight: bold; width: fit-content;">{}</div>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    status_badge.admin_order_field = 'status'

    def battery_display(self, obj):
        if obj.battery_level is None: return "-"
        color = 'green'
        if obj.battery_level < 20: color = 'red'
        elif obj.battery_level < 50: color = 'orange'
        return format_html('<span style="color: {}; font-weight: bold;">{}%</span>', color, obj.battery_level)
    battery_display.short_description = 'Bateria'
    battery_display.admin_order_field = 'battery_level'

@admin.register(WebhookConfig)
class WebhookConfigAdmin(admin.ModelAdmin):
    list_display = ('instance_link', 'url', 'msg_flag', 'ack_flag', 'presence_flag', 'created_at')
    search_fields = ('url', 'instance__name', 'instance__owner__username')
    readonly_fields = ('secret', 'created_at')

    def instance_link(self, obj):
        return format_html('<a href="/admin/fillow/instance/{}/change/">{}</a>', obj.instance.id, obj.instance.name)
    instance_link.short_description = 'Instância'

    def msg_flag(self, obj): return obj.send_messages
    msg_flag.boolean = True
    msg_flag.short_description = 'Msgs'

    def ack_flag(self, obj): return obj.send_ack
    ack_flag.boolean = True
    ack_flag.short_description = 'Lido'

    def presence_flag(self, obj): return obj.send_presence
    presence_flag.boolean = True
    presence_flag.short_description = 'Online'