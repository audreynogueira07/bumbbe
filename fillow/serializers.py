# serializers.py
from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from .models import (
    CampaignRecipientSnapshot,
    DispatchCampaign,
    DispatchContactGroup,
    DispatchContactInGroup,
    DispatchQueueItem,
    MessageTemplate,
    WaInstance,
)


class MessageTemplateSerializer(serializers.ModelSerializer):
    media_file_id = serializers.IntegerField(
        required=False, allow_null=True, write_only=True
    )

    class Meta:
        model = MessageTemplate
        fields = [
            "id",
            "name",
            "body",
            "media_file",
            "media_file_id",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "media_file"]

    def validate(self, attrs):
        media_file_id = attrs.pop("media_file_id", None)

        # PATCH sem media_file_id no payload: preserve valor atual
        if self.instance and media_file_id is None:
            media_file = self.instance.media_file
        else:
            media_file = None
            if media_file_id:
                from .models import DispatchMediaFile  # import local para evitar ciclo

                try:
                    media_file = DispatchMediaFile.objects.get(pk=media_file_id)
                except DispatchMediaFile.DoesNotExist:
                    raise serializers.ValidationError(
                        {"media_file_id": "Arquivo de mídia não encontrado."}
                    )

        body = attrs.get(
            "body", self.instance.body if self.instance else ""
        ) or ""

        if not body.strip() and not media_file:
            raise serializers.ValidationError(
                "Template precisa ter body ou media_file."
            )

        attrs["media_file"] = media_file
        return attrs


class DispatchContactInGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = DispatchContactInGroup
        fields = ["id", "phone_number", "jid", "display_name", "created_at"]
        read_only_fields = ["id", "created_at"]


class DispatchContactGroupSerializer(serializers.ModelSerializer):
    contacts_count = serializers.IntegerField(read_only=True)
    contacts = DispatchContactInGroupSerializer(many=True, read_only=True)
    raw_numbers = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )

    class Meta:
        model = DispatchContactGroup
        fields = [
            "id",
            "name",
            "description",
            "contacts_count",
            "contacts",
            "raw_numbers",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "contacts_count",
            "contacts",
            "created_at",
            "updated_at",
        ]


class DispatchCampaignSerializer(serializers.ModelSerializer):
    instance_name = serializers.SerializerMethodField()
    templates = MessageTemplateSerializer(many=True, read_only=True)
    groups = DispatchContactGroupSerializer(many=True, read_only=True)

    class Meta:
        model = DispatchCampaign
        fields = [
            "id",
            "name",
            "status",
            "instance",
            "instance_name",
            "templates",
            "groups",
            "raw_numbers",
            "start_at",
            "min_delay_seconds",
            "max_delay_seconds",
            "messages_per_recipient",
            "use_name_placeholder",
            "total_recipients",
            "total_planned",
            "total_sent",
            "total_failed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "total_recipients",
            "total_planned",
            "total_sent",
            "total_failed",
            "created_at",
            "updated_at",
        ]

    def get_instance_name(self, obj):
        if obj.instance:
            return obj.instance.name or obj.instance.session_id
        return None


class CampaignCreateSerializer(serializers.Serializer):
    """
    Serializer de criação com compatibilidade:
    - Campos canônicos (segundos): min_delay_seconds / max_delay_seconds
    - Aliases antigos aceitos: min_delay / max_delay
    - templates/groups via ids, ou aliases template_ids/group_ids
    """
    name = serializers.CharField(max_length=180)
    instance_id = serializers.IntegerField()
    template_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False
    )
    group_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=True
    )
    raw_numbers = serializers.CharField(required=False, allow_blank=True)

    start_at = serializers.DateTimeField(required=False, allow_null=True)
    min_delay_seconds = serializers.IntegerField(default=20)
    max_delay_seconds = serializers.IntegerField(default=45)
    messages_per_recipient = serializers.IntegerField(default=1)
    use_name_placeholder = serializers.BooleanField(default=True)

    # ---- compatibilidade de payload ----
    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data or {})

        # Aliases de campos vindos do front antigo
        if ("instance_id" not in data or data.get("instance_id") in ("", None)) and data.get("instance") not in ("", None):
            data["instance_id"] = data.get("instance")

        if ("template_ids" not in data or data.get("template_ids") in ("", None, [])) and data.get("templates") not in ("", None):
            data["template_ids"] = data.get("templates")

        if ("group_ids" not in data or data.get("group_ids") in ("", None, [])) and data.get("groups") not in ("", None):
            data["group_ids"] = data.get("groups")

        # Delay em segundos (aceita alias min_delay / max_delay)
        if ("min_delay_seconds" not in data or data.get("min_delay_seconds") in ("", None)) and data.get("min_delay") not in ("", None):
            data["min_delay_seconds"] = data.get("min_delay")

        if ("max_delay_seconds" not in data or data.get("max_delay_seconds") in ("", None)) and data.get("max_delay") not in ("", None):
            data["max_delay_seconds"] = data.get("max_delay")

        # Aceita lista como string "1,2,3"
        for key in ("template_ids", "group_ids"):
            val = data.get(key)
            if isinstance(val, str):
                data[key] = [x.strip() for x in val.split(",") if x.strip()]

        return super().to_internal_value(data)

    def validate_instance_id(self, value):
        try:
            inst = WaInstance.objects.get(pk=value)
        except WaInstance.DoesNotExist:
            raise serializers.ValidationError("Instância não encontrada.")
        if inst.status != "CONNECTED":
            raise serializers.ValidationError("Instância precisa estar CONNECTED.")
        return value

    def validate_template_ids(self, value):
        qs = MessageTemplate.objects.filter(
            id__in=value, is_active=True
        ).values_list("id", flat=True)
        found = set(qs)
        missing = [x for x in value if x not in found]
        if missing:
            raise serializers.ValidationError(
                f"Templates inválidos/inativos: {missing}"
            )
        return value

    def validate_group_ids(self, value):
        if not value:
            return value
        qs = DispatchContactGroup.objects.filter(id__in=value).values_list(
            "id", flat=True
        )
        found = set(qs)
        missing = [x for x in value if x not in found]
        if missing:
            raise serializers.ValidationError(f"Grupos inválidos: {missing}")
        return value

    def validate_start_at(self, value):
        if value is None:
            return value
        # tolerância de 1 minuto para evitar falha com drift de relógio
        if value < timezone.now() - timedelta(minutes=1):
            raise serializers.ValidationError("start_at não pode ser no passado.")
        return value

    def validate(self, attrs):
        min_d = attrs["min_delay_seconds"]
        max_d = attrs["max_delay_seconds"]

        if min_d < 1:
            raise serializers.ValidationError(
                {"min_delay_seconds": "Deve ser >= 1 segundo."}
            )
        if max_d < 1:
            raise serializers.ValidationError(
                {"max_delay_seconds": "Deve ser >= 1 segundo."}
            )
        if min_d > max_d:
            raise serializers.ValidationError(
                {"max_delay_seconds": "max_delay_seconds deve ser >= min_delay_seconds."}
            )
        if attrs["messages_per_recipient"] < 1:
            raise serializers.ValidationError(
                {"messages_per_recipient": "Deve ser >= 1."}
            )

        if not attrs.get("group_ids") and not (attrs.get("raw_numbers") or "").strip():
            raise serializers.ValidationError(
                "Informe group_ids ou raw_numbers."
            )
        return attrs


class QueueItemSerializer(serializers.ModelSerializer):
    campaign_name = serializers.CharField(source="campaign.name", read_only=True)
    template_name = serializers.CharField(source="template.name", read_only=True)

    class Meta:
        model = DispatchQueueItem
        fields = [
            "id",
            "campaign",
            "campaign_name",
            "recipient",
            "template",
            "template_name",
            "status",
            "step",
            "scheduled_at",
            "attempts",
            "last_error_code",
            "error_text",
            "provider_message_id",
            "created_at",
            "updated_at",
        ]


class CampaignRecipientSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = CampaignRecipientSnapshot
        fields = [
            "id",
            "campaign",
            "phone_number",
            "jid",
            "display_name",
            "source_type",
            "source_ref",
            "created_at",
        ]


class QueueProcessSerializer(serializers.Serializer):
    campaign_id = serializers.IntegerField(required=False)
    instance_id = serializers.IntegerField(required=False)
    max_instances = serializers.IntegerField(default=3, min_value=1, max_value=20)
