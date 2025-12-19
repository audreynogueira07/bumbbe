from rest_framework import serializers
from .models import Instance, WebhookConfig, Message

# ==============================================================================
# 1. SERIALIZERS ORIGINAIS (DASHBOARD E API INTERNA)
# ==============================================================================

class InstanceSerializer(serializers.ModelSerializer):
    """Serializa os dados da instância para exibir no Dashboard/API."""
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Instance
        fields = ['id', 'name', 'phone_connected', 'status', 'status_display', 'platform', 'battery_level', 'updated_at', 'token']
        read_only_fields = ['id', 'token', 'phone_connected', 'status', 'updated_at', 'platform', 'battery_level']

class WebhookConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookConfig
        fields = ['url', 'send_messages', 'send_ack', 'send_presence']

class MessageSerializer(serializers.ModelSerializer):
    """Serializa mensagens para listagem no painel."""
    formatted_time = serializers.DateTimeField(source='timestamp', format="%d/%m %H:%M", read_only=True)

    class Meta:
        model = Message
        fields = ['id', 'remote_jid', 'push_name', 'from_me', 'message_type', 'content', 'formatted_time']

class SendMessageSerializer(serializers.Serializer):
    """Valida o payload de envio de mensagem de texto simples."""
    to = serializers.CharField(help_text="Número de destino (ex: 5511999999999@s.whatsapp.net)")
    message = serializers.CharField(help_text="Texto da mensagem")
    type = serializers.ChoiceField(choices=['text', 'image'], default='text', required=False)
    media_url = serializers.URLField(required=False, help_text="URL da imagem (se type=image)")
    options = serializers.DictField(required=False, help_text="Opções adicionais do Baileys")

# ==============================================================================
# 2. NOVOS SERIALIZERS (API V1 AVANÇADA - COMPLETA)
# ==============================================================================

# --- Mensagens e Mídia ---
class SendVoiceSerializer(serializers.Serializer):
    """Valida envio de Áudio/PTT."""
    to = serializers.CharField(help_text="Número de destino")
    file = serializers.FileField(help_text="Arquivo de áudio (mp3/ogg/wav)")

class SendLocationSerializer(serializers.Serializer):
    """Valida envio de Localização."""
    to = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    address = serializers.CharField(required=False, allow_blank=True)
    name = serializers.CharField(required=False, allow_blank=True)

class SendPollSerializer(serializers.Serializer):
    """
    Valida envio de Enquete.

    A versão mais recente da API Baileys utiliza o campo "values" para as
    opções da enquete. Para manter compatibilidade, o campo "options" ainda
    é aceito e será mapeado para "values" na view.
    """
    to = serializers.CharField()
    name = serializers.CharField(help_text="Pergunta da enquete")
    # Novo campo principal: values
    values = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        required=False,
        help_text="Lista de opções (use este campo de preferência)"
    )
    # Campo legado: options (mapeado para values na view)
    options = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        required=False,
        help_text="Lista de opções (legado; será convertido em values)"
    )
    selectable_count = serializers.IntegerField(
        default=1,
        min_value=0,
        required=False,
        help_text="Quantas opções podem ser escolhidas (0 = sem limite)"
    )
    to_announcement_group = serializers.BooleanField(
        required=False,
        help_text="Permite votar em enquete em grupos de anúncio/comunidade"
    )

class SendContactSerializer(serializers.Serializer):
    """Valida envio de Contato (VCard)."""
    to = serializers.CharField()
    full_name = serializers.CharField(help_text="Nome de exibição do contato")
    phone_number = serializers.CharField(help_text="Número do contato a ser compartilhado")

class SendReactionSerializer(serializers.Serializer):
    """Valida envio de Reação."""
    to = serializers.CharField()
    emoji = serializers.CharField(max_length=10, help_text="Emoji da reação")
    key = serializers.DictField(help_text="Objeto Key da mensagem (id, fromMe, remoteJid)")

# --- Gestão de Mensagens (Edit/Pin/Delete/Star) ---
class MessageKeySerializer(serializers.Serializer):
    """Serializer auxiliar para identificar mensagens."""
    id = serializers.CharField(help_text="ID da mensagem")
    from_me = serializers.BooleanField(default=True)
    remote_jid = serializers.CharField(required=False, help_text="Se diferente do 'to'")

class EditMessageSerializer(serializers.Serializer):
    """Valida edição de mensagem."""
    to = serializers.CharField()
    text = serializers.CharField(help_text="Novo texto da mensagem")
    key = MessageKeySerializer(help_text="Dados da mensagem original")

class MessageActionSerializer(serializers.Serializer):
    """Valida ações como Delete (Revoke)."""
    to = serializers.CharField()
    key = MessageKeySerializer()

class PinMessageSerializer(serializers.Serializer):
    """Valida fixação de mensagem."""
    to = serializers.CharField()
    key = MessageKeySerializer()
    time = serializers.IntegerField(required=False, default=86400, help_text="Duração em segundos")

class StarMessageSerializer(serializers.Serializer):
    """Valida favoritar mensagem."""
    to = serializers.CharField()
    key = MessageKeySerializer()
    star = serializers.BooleanField(default=True)

# --- Gestão de Chats (Archive/Mute/Clear) ---
class ChatArchiveSerializer(serializers.Serializer):
    to = serializers.CharField()
    archive = serializers.BooleanField(default=True)

class ChatMuteSerializer(serializers.Serializer):
    to = serializers.CharField()
    time = serializers.IntegerField(allow_null=True, required=False, help_text="Tempo em ms ou null para desmutar")

class ChatActionSerializer(serializers.Serializer):
    """Usado para limpar chat ou marcar como lido."""
    to = serializers.CharField()
    read = serializers.BooleanField(required=False, default=True) # Apenas para mark-read

# --- Grupos ---
class GroupCreateSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=100)
    participants = serializers.ListField(child=serializers.CharField(), min_length=1)

class GroupParticipantsSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['add', 'remove', 'promote', 'demote'])
    participants = serializers.ListField(child=serializers.CharField(), min_length=1)

class GroupUpdateSubjectSerializer(serializers.Serializer):
    subject = serializers.CharField()

class GroupUpdateDescriptionSerializer(serializers.Serializer):
    description = serializers.CharField()

class GroupSettingSerializer(serializers.Serializer):
    setting = serializers.ChoiceField(choices=['announcement', 'not_announcement', 'locked', 'unlocked'])

class JoinGroupSerializer(serializers.Serializer):
    code = serializers.CharField()

# --- Perfil e Bloqueio ---
class BlockUserSerializer(serializers.Serializer):
    jid = serializers.CharField()
    action = serializers.ChoiceField(choices=['block', 'unblock'])

class UpdateProfileStatusSerializer(serializers.Serializer):
    status = serializers.CharField()

class CheckOnWhatsappSerializer(serializers.Serializer):
    jid = serializers.CharField()