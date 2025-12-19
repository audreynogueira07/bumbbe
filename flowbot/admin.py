from django.contrib import admin
from django.utils.html import format_html
from .models import FlowBot, FlowMedia, FlowConversation, FlowMessage


@admin.register(FlowBot)
class FlowBotAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "active", "public_token", "updated_at")
    list_filter = ("active",)
    search_fields = ("name", "user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Identificação", {"fields": ("user", "name", "active", "description", "public_token")}),
        ("Fluxo", {"fields": ("flow_json",)}),
        ("Datas", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(FlowMedia)
class FlowMediaAdmin(admin.ModelAdmin):
    list_display = ("__str__", "bot", "media_type", "created_at", "preview")
    list_filter = ("media_type", "bot")
    search_fields = ("title", "file", "caption", "bot__name")
    readonly_fields = ("created_at", "preview")

    def preview(self, obj):
        try:
            if obj.media_type == "image":
                return format_html('<img src="{}" style="max-height:50px;border-radius:6px;" />', obj.file.url)
        except Exception:
            return "-"
        return "-"

    preview.short_description = "Preview"


@admin.register(FlowConversation)
class FlowConversationAdmin(admin.ModelAdmin):
    list_display = ("bot", "session_key", "visitor_name", "visitor_whatsapp", "updated_at")
    list_filter = ("bot",)
    search_fields = ("session_key", "visitor_name", "visitor_whatsapp", "bot__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(FlowMessage)
class FlowMessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "created_at", "from_visitor", "message_type", "short_text")
    list_filter = ("message_type", "from_visitor")
    search_fields = ("text", "conversation__session_key", "conversation__bot__name")
    readonly_fields = ("created_at",)

    def short_text(self, obj):
        t = (obj.text or "").strip()
        return t[:80] + ("…" if len(t) > 80 else "")

    short_text.short_description = "Conteúdo"
