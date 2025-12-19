import logging
import json
import requests
from datetime import datetime

from django.utils import timezone
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.views import LoginView
from django.conf import settings

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from .models import Instance, WebhookConfig, Message
from .serializers import (
    InstanceSerializer,
    WebhookConfigSerializer,
    MessageSerializer,
    SendMessageSerializer,
    # API V1 avançada
    SendVoiceSerializer,
    SendLocationSerializer,
    SendPollSerializer,
    SendContactSerializer,
    SendReactionSerializer,
    EditMessageSerializer,
    MessageActionSerializer,
    PinMessageSerializer,
    StarMessageSerializer,
    ChatArchiveSerializer,
    ChatMuteSerializer,
    ChatActionSerializer,
    GroupCreateSerializer,
    GroupParticipantsSerializer,
    GroupUpdateSubjectSerializer,
    GroupUpdateDescriptionSerializer,
    GroupSettingSerializer,
    JoinGroupSerializer,
    BlockUserSerializer,
    UpdateProfileStatusSerializer,
    CheckOnWhatsappSerializer,
)
from .services import NodeBridge, sync_instance_token
# Renomeamos o import original para podermos sobrescrever com a versão de DEBUG abaixo
from .permissions import HasInstanceToken as OriginalHasInstanceToken

logger = logging.getLogger(__name__)
node_bridge = NodeBridge()


# ==============================================================================
# PERMISSÕES, DECORATORS E MIXINS
# ==============================================================================

class HasInstanceToken(permissions.BasePermission):
    """
    Versão DEBUG local de HasInstanceToken para diagnosticar erro 403.
    Substitui a classe importada de .permissions.
    """
    def has_permission(self, request, view):
        auth_header = request.headers.get("Authorization", "")
        
        print(f"\n[DEBUG API] Verificando permissão para: {request.path}")
        print(f"[DEBUG API] Header Authorization recebido: '{auth_header}'")

        if not auth_header or not auth_header.startswith("Bearer "):
            print("[DEBUG API] FALHA: Header ausente ou sem prefixo Bearer.")
            return False

        token = auth_header.split(" ")[1]
        print(f"[DEBUG API] Token extraído: '{token}'")

        try:
            # Tenta buscar a instância pelo token
            instance = Instance.objects.get(token=token)
            # Injeta a instância no request para uso nas Views
            request.instance = instance
            print(f"[DEBUG API] SUCESSO: Instância '{instance.name}' (ID: {instance.id}) autenticada.")
            return True
        except Instance.DoesNotExist:
            print(f"[DEBUG API] FALHA: Nenhuma instância encontrada com o token '{token}'.")
            return False
        except Exception as e:
            print(f"[DEBUG API] ERRO: Exceção ao verificar token: {e}")
            return False


class HasActivePlan(permissions.BasePermission):
    """
    Permissão personalizada para DRF (API Interna / Painel).

    Regras:
    1. Usuário autenticado.
    2. Campo 'api' no usuário deve ser True.
    3. Campo 'plan_end_date' não pode ser None.
    4. Campo 'plan_end_date' deve ser maior que agora.
    """

    message = "Seu plano expirou ou você não possui permissão de acesso à API."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        # Flag de acesso à API
        if not getattr(user, "api", False):
            return False

        expiration = getattr(user, "plan_end_date", None)

        # Sem data definida = expirado / sem vigência
        if expiration is None:
            return False

        if expiration < timezone.now():
            return False

        return True


def active_plan_required(view_func):
    """
    Decorator para views HTML (Django clássico).
    Só permite acesso a usuários com plano ativo e api=True.
    """
    from django.contrib.auth.decorators import user_passes_test

    def check_plan(user):
        if not user.is_authenticated:
            return False

        if not getattr(user, "api", False):
            return False

        expiration = getattr(user, "plan_end_date", None)
        if expiration is None:
            return False

        if expiration < timezone.now():
            return False

        return True

    return user_passes_test(check_plan, login_url="fillow:index")(view_func)


class InstancePlanCheckMixin:
    """
    Mixin auxiliar para validar se o DONO da instância possui plano ativo
    antes de processar requisições da API Pública V1.

    A instância é injetada em request.instance pelo permission HasInstanceToken.
    """

    def validate_instance_ready(self, request):
        """
        Valida:
        - Token da instância (já feito pelo HasInstanceToken).
        - Plano do dono (api=True e plan_end_date > agora).
        - Status da instância (CONNECTED).

        Retorna:
        (instance, None) em caso de sucesso
        (None, Response) em caso de erro (já pronto para retornar na view)
        """
        print("[DEBUG MIXIN] Iniciando validate_instance_ready...")
        instance = getattr(request, "instance", None)
        if instance is None:
            print("[DEBUG MIXIN] Erro: request.instance é None (HasInstanceToken falhou?)")
            return None, Response({"error": "Instância não encontrada pelo token."}, status=401)

        print(f"[DEBUG MIXIN] Instância: {instance.name}, Status: {instance.status}")
        owner = instance.owner

        # 1. Flag API
        if not getattr(owner, "api", False):
            print(f"[DEBUG MIXIN] Erro: Usuário {owner} sem flag API.")
            return None, Response(
                {"error": "O plano do proprietário desta instância não permite uso da API."},
                status=403,
            )

        # 2. Data de expiração
        expiration = getattr(owner, "plan_end_date", None)
        if expiration is None or expiration < timezone.now():
            print(f"[DEBUG MIXIN] Erro: Plano expirado (Exp: {expiration}).")
            return None, Response(
                {"error": "O plano do proprietário desta instância expirou."},
                status=403,
            )

        # 3. Status da instância
        # Comentando verificação estrita de CONNECTED para debug, caso o status esteja desatualizado
        # if instance.status != "CONNECTED":
        #    return None, Response(
        #        {"error": "Instância não conectada. Conecte o WhatsApp antes de usar a API."},
        #        status=503,
        #    )

        print("[DEBUG MIXIN] Validação OK.")
        return instance, None


# ==============================================================================
# 1. AUTH E DASHBOARD GERAL
# ==============================================================================


class CustomLoginView(LoginView):
    template_name = "fillow/pages/page-login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        from django.urls import reverse

        return reverse("fillow:index")


@login_required
def dashboard_view(request):
    """
    Dashboard principal.
    Permite acesso mesmo com plano vencido, para o usuário poder renovar.
    """
    instances = Instance.objects.filter(owner=request.user).order_by("-created_at")
    context = {
        "instances": instances,
        "plan": getattr(request.user, "plan", None),
        "can_create": request.user.can_create_instance(),
    }
    return render(request, "fillow/index.html", context)


@login_required
def api_dashboard_view(request):
    """
    Dashboard principal.
    Permite acesso mesmo com plano vencido, para o usuário poder renovar.
    """
    instances = Instance.objects.filter(owner=request.user).order_by("-created_at")
    context = {
        "instances": instances,
        "plan": getattr(request.user, "plan", None),
        "can_create": request.user.can_create_instance(),
    }
    return render(request, "fillow/api.html", context)


@login_required
@active_plan_required
def docs_view(request):
    """
    Documentação da API (apenas para quem tem plano ativo e api=True).
    """
    base_url = request.build_absolute_uri("/api/v1").rstrip("/")
    return render(request, "fillow/docs.html", {"api_base_url": base_url})


# ==============================================================================
# 2. PAINEL DE ADMINISTRAÇÃO DA INSTÂNCIA
# ==============================================================================


@login_required
@active_plan_required
def instance_dashboard_view(request, instance_id):
    instance = get_object_or_404(Instance, id=instance_id, owner=request.user)
    webhook_config, _ = WebhookConfig.objects.get_or_create(instance=instance)

    # Self-healing: se o token ainda não chegou via webhook, tenta sincronizar no Node
    if not instance.token:
        sync_instance_token(instance, bridge=node_bridge)

    messages = Message.objects.filter(instance=instance).order_by("-timestamp")[:50]

    context = {
        "instance": instance,
        "webhook_config": webhook_config,
        "messages": messages,
        "api_token": instance.token,
        "node_url": getattr(settings, "NODE_API_URL", "http://localhost:3000"),
    }
    return render(request, "fillow/instance_dashboard.html", context)


# ==============================================================================
# 3. ACTIONS INTERNAS (PAINEL / API INTERNA)
# ==============================================================================


class InstanceActionView(APIView):
    """
    Criação e exclusão de instâncias via painel (AJAX).
    """
    permission_classes = [permissions.IsAuthenticated, HasActivePlan]

    def post(self, request):
        user = request.user

        if not user.can_create_instance():
            return Response(
                {"error": "Limite do plano atingido ou plano inválido."},
                status=status.HTTP_403_FORBIDDEN,
            )

        name = request.data.get("name", "Nova Instância")
        instance = Instance.objects.create(owner=user, name=name)
        WebhookConfig.objects.create(instance=instance)

        # Inicia sessão no Node (modo admin)
        success, response_data = node_bridge.create_session(instance.session_id)

        if not success:
            instance.delete()
            return Response(
                {"error": "Falha ao iniciar motor.", "detail": response_data},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(InstanceSerializer(instance).data, status=status.HTTP_201_CREATED)

    def delete(self, request, pk):
        instance = get_object_or_404(Instance, id=pk, owner=request.user)
        try:
            node_bridge.delete_session(instance.session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Erro ao deletar sessão no Node: %s", exc)

        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated, HasActivePlan])
def connect_instance_view(request, instance_id):
    instance = get_object_or_404(Instance, id=instance_id, owner=request.user)
    success, data = node_bridge.create_session(instance.session_id)

    if not success:
        return Response(
            {"error": "Erro ao conectar ao motor", "detail": data},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response(data)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated, HasActivePlan])
def disconnect_instance_view(request, instance_id):
    instance = get_object_or_404(Instance, id=instance_id, owner=request.user)

    try:
        node_bridge.logout_session(instance.session_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Erro ao desconectar sessão no Node: %s", exc)

    instance.status = "DISCONNECTED"
    instance.phone_connected = None
    # Token antigo fica inválido após logout/desconexão; limpamos para evitar "Bearer" quebrado
    instance.token = None
    instance.save(update_fields=["status", "phone_connected", "token"])

    return Response({"status": "disconnected"})


# views.py

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated, HasActivePlan])
def get_instance_status_view(request, instance_id):
    instance = get_object_or_404(Instance, id=instance_id, owner=request.user)

    try:
        # 1. Consulta o status básico/QR Code
        success_qr, data_qr = node_bridge.get_qrcode(instance.session_id)
        qrcode = data_qr.get("qrCode") if success_qr and isinstance(data_qr, dict) else None
        
        # Variável para controlar se precisamos salvar o banco
        changed = False

        if success_qr and isinstance(data_qr, dict):
            new_status = data_qr.get("status")
            
            # Atualiza status se mudou
            if new_status and new_status != instance.status:
                instance.status = new_status
                changed = True

        # ======================================================================
        # LÓGICA DE SINCRONIZAÇÃO FORÇADA (AUTO-HEALING)
        # ======================================================================
        # Se o status é CONNECTED, forçamos uma verificação profunda na rota /sessions
        # para garantir que temos o Token e o Telefone corretos.
        if instance.status == "CONNECTED":
            # Chama o sync que busca na lista de sessões do Node
            synced = sync_instance_token(instance, bridge=node_bridge)
            if synced:
                # Se sync_instance_token salvou algo, recarregamos do banco
                instance.refresh_from_db()

        # Se houve mudança de status e não passou pelo sync (que já salva), salvamos aqui
        if changed and not instance.status == "CONNECTED":
            instance.save(update_fields=["status", "updated_at"])

        return Response(
            {
                "status": instance.status,
                "qrcode": qrcode,
                "phone": instance.phone_connected,
                # RETORNAMOS O TOKEN PARA O FRONTEND ATUALIZAR SEM REFRESH
                "token": instance.token, 
            }
        )

    except Exception as exc:
        logger.warning("Erro ao consultar status da instância: %s", exc)
        return Response(
            {"status": instance.status, "error": "Unreachable"},
            status=status.HTTP_200_OK,
        )


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated, HasActivePlan])
def update_webhook_view(request, instance_id):
    instance = get_object_or_404(Instance, id=instance_id, owner=request.user)
    config = instance.webhook

    serializer = WebhookConfigSerializer(config, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# --- Chat ao vivo e testes (dashboard) ---------------------------------------------------------


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated, HasActivePlan])
def get_instance_messages_view(request, instance_id):
    instance = get_object_or_404(Instance, id=instance_id, owner=request.user)
    messages = Message.objects.filter(instance=instance).order_by("-timestamp")[:50]
    serializer = MessageSerializer(messages, many=True)
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated, HasActivePlan])
def send_test_message_view(request, instance_id):
    instance = get_object_or_404(Instance, id=instance_id, owner=request.user)

    to_number = request.data.get("to")
    message_text = request.data.get("message", "Teste de envio.")

    # --- DEBUG: PRINTS PARA IDENTIFICAR O TOKEN ---
    print("\n" + "="*50)
    print(f"DEBUG - send_test_message_view - Instance ID: {instance_id}")
    print(f"DEBUG - Session ID: {instance.session_id}")
    print(f"DEBUG - Token no Banco (instance.token): '{instance.token}'")
    print(f"DEBUG - Destino: {to_number}")
    print("="*50 + "\n")
    # ---------------------------------------------

    # 1. VALIDAÇÃO DO TOKEN DE SESSÃO
    # Sem token = instância não conectada ou erro de webhook
    if not instance.token:
        # tenta self-healing (puxa o token diretamente do Node) antes de bloquear
        sync_instance_token(instance, bridge=node_bridge)

    if not instance.token:
        print("DEBUG - ERRO: Token ausente no banco de dados!")
        return Response(
            {"error": "Instância não conectada ou token não gerado. Conecte o WhatsApp primeiro."}, 
            status=status.HTTP_403_FORBIDDEN
        )

    if not to_number:
        return Response({"error": "Número obrigatório."}, status=status.HTTP_400_BAD_REQUEST)

    # Sanitização simples do número
    to_number = (
        str(to_number)
        .strip()
        .replace("+", "")
        .replace("-", "")
        .replace(" ", "")
    )
    if "@" not in to_number:
        to_number = f"{to_number}@s.whatsapp.net"

    payload = {"to": to_number, "message": message_text}

    # 2. CHAMADA COM RETRY AUTOMÁTICO PARA TOKEN INVÁLIDO (403)
    print(f"DEBUG - Chamando node_bridge.send_message com token: '{instance.token}'")
    success, node_resp = node_bridge.send_message(
        instance.session_id, 
        payload, 
        session_token=instance.token 
    )
    print(f"DEBUG - Resposta do Node: Sucesso={success}, Body={node_resp}")

    # LOGICA DE SELF-HEALING (AUTOCURA)
    # Se recebermos erro 403 (token inválido), tentamos sincronizar o token com o Node e reenviar 1x.
    if (
        not success
        and isinstance(node_resp, dict)
        and "ACESSO NEGADO" in str(node_resp.get("error", ""))
    ):
        print("DEBUG - ERRO 403 DETECTADO. Tentando sincronizar token com o Node (self-healing)...")

        if sync_instance_token(instance, bridge=node_bridge) and instance.token:
            print(f"DEBUG - Token após sync: '{instance.token}'")
            print("DEBUG - Tentando reenviar mensagem com token sincronizado...")
            success, node_resp = node_bridge.send_message(
                instance.session_id,
                payload,
                session_token=instance.token,
            )
            print(f"DEBUG - Reenvio: Sucesso={success}, Body={node_resp}")


    if success:
        try:
            Message.objects.create(
                instance=instance,
                remote_jid=to_number,
                from_me=True,
                content=message_text,
                message_type="text",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Erro ao salvar mensagem de teste: %s", exc)

        return Response(node_resp)

    return Response(node_resp, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated, HasActivePlan])
@parser_classes([MultiPartParser, FormParser])
def send_test_media_view(request, instance_id):
    """
    Endpoint interno (painel) para teste de envio de mídia.
    """
    instance = get_object_or_404(Instance, id=instance_id, owner=request.user)

    to_number = request.data.get("to")
    caption = request.data.get("caption", "")
    file_obj = request.FILES.get("file")

    # --- DEBUG: PRINTS PARA MÍDIA ---
    print("\n" + "="*50)
    print(f"DEBUG - send_test_media_view - Instance ID: {instance_id}")
    print(f"DEBUG - Session ID: {instance.session_id}")
    print(f"DEBUG - Token no Banco: '{instance.token}'")
    print("="*50 + "\n")
    # --------------------------------

    # Self-healing: garante que o token exista no Django antes de chamar o Node
    if not instance.token:
        sync_instance_token(instance, bridge=node_bridge)

    if not instance.token:
        return Response(
            {"error": "Instância não conectada ou token não gerado. Conecte o WhatsApp primeiro."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if not to_number or not file_obj:
        return Response(
            {"error": "Número e arquivo são obrigatórios."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    to_number = (
        str(to_number)
        .strip()
        .replace("+", "")
        .replace("-", "")
        .replace(" ", "")
    )
    if "@" not in to_number:
        to_number = f"{to_number}@s.whatsapp.net"

    form_data = {"to": to_number, "caption": caption}
    files = {"file": (file_obj.name, file_obj.read(), file_obj.content_type)}
    # Always include the session token so the Node API can authenticate this request
    
    print(f"DEBUG - Chamando node_bridge.send_media com token: '{instance.token}'")
    success, node_resp = node_bridge.send_media(
        instance.session_id,
        form_data,
        files,
        session_token=instance.token,
    )
    print(f"DEBUG - Resposta Mídia do Node: Sucesso={success}, Body={node_resp}")

    # Self-healing: se 403 por token inválido, sincroniza e tenta novamente 1x
    if (
        not success
        and isinstance(node_resp, dict)
        and "ACESSO NEGADO" in str(node_resp.get("error", ""))
    ):
        print("DEBUG - ERRO 403 DETECTADO (MÍDIA). Tentando sincronizar token com o Node (self-healing)...")
        if sync_instance_token(instance, bridge=node_bridge) and instance.token:
            print(f"DEBUG - Token após sync (MÍDIA): '{instance.token}'")
            success, node_resp = node_bridge.send_media(
                instance.session_id,
                form_data,
                files,
                session_token=instance.token,
            )
            print(f"DEBUG - Reenvio Mídia: Sucesso={success}, Body={node_resp}")

    if success:
        msg_type = "document"
        mime_type = file_obj.content_type or ""
        if mime_type.startswith("image"):
            msg_type = "image"
        elif mime_type.startswith("video"):
            msg_type = "video"
        elif mime_type.startswith("audio"):
            msg_type = "audio"

        try:
            Message.objects.create(
                instance=instance,
                remote_jid=to_number,
                from_me=True,
                content=caption,
                message_type=msg_type,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Erro ao salvar mensagem de mídia: %s", exc)

        return Response(node_resp)

    return Response(node_resp, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==============================================================================
# 4. API PÚBLICA V1 - MENSAGENS E MÍDIA
# ==============================================================================


class SendMessageGateway(APIView, InstancePlanCheckMixin):
    """
    Envio de mensagens de texto simples (e imagem por URL, se type=image).
    Requer header: Authorization: Bearer <token-da-instância>.
    """
    authentication_classes = []
    permission_classes = [HasInstanceToken]

    def post(self, request):
        instance, error_response = self.validate_instance_ready(request)
        if error_response:
            return error_response

        serializer = SendMessageSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        payload = serializer.validated_data

        # Pass the instance token to authorize user-level route
        success, node_resp = node_bridge.send_message(
            instance.session_id,
            payload,
            session_token=instance.token,
        )

        if success:
            try:
                Message.objects.create(
                    instance=instance,
                    remote_jid=payload["to"],
                    from_me=True,
                    content=payload.get("message", ""),
                    message_type=payload.get("type", "text"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Erro ao registrar mensagem enviada via API: %s", exc)

            return Response(node_resp)

        return Response(node_resp, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SendMediaView(APIView, InstancePlanCheckMixin):
    """
    Envio de mídia genérica (imagem, vídeo, documento) via multipart/form-data.
    """
    authentication_classes = []
    permission_classes = [HasInstanceToken]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        instance, error_response = self.validate_instance_ready(request)
        if error_response:
            return error_response

        to_number = request.data.get("to")
        caption = request.data.get("caption", "")
        file_obj = request.FILES.get("file")

        if not to_number or not file_obj:
            return Response(
                {"error": 'Campos "to" e "file" são obrigatórios.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        to_number = (
            str(to_number)
            .strip()
            .replace("+", "")
            .replace("-", "")
            .replace(" ", "")
        )
        if "@" not in to_number:
            to_number = f"{to_number}@s.whatsapp.net"

        form_data = {"to": to_number, "caption": caption}
        files = {"file": (file_obj.name, file_obj.read(), file_obj.content_type)}

        # Pass the instance token when sending media to authorize the route
        success, node_resp = node_bridge.send_media(
            instance.session_id,
            form_data,
            files,
            session_token=instance.token,
        )

        if success:
            msg_type = "document"
            mime_type = file_obj.content_type or ""
            if mime_type.startswith("image"):
                msg_type = "image"
            elif mime_type.startswith("video"):
                msg_type = "video"
            elif mime_type.startswith("audio"):
                msg_type = "audio"

            try:
                Message.objects.create(
                    instance=instance,
                    remote_jid=to_number,
                    from_me=True,
                    content=caption,
                    message_type=msg_type,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Erro ao registrar mídia enviada via API: %s", exc)

            return Response(node_resp)

        return Response(node_resp, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SendVoiceView(APIView, InstancePlanCheckMixin):
    """
    Envia áudio / PTT (nota de voz).
    """
    authentication_classes = []
    permission_classes = [HasInstanceToken]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        instance, error_response = self.validate_instance_ready(request)
        if error_response:
            return error_response

        serializer = SendVoiceSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        to_number = serializer.validated_data["to"]
        file_obj = serializer.validated_data["file"]

        to_number = (
            str(to_number)
            .strip()
            .replace("+", "")
            .replace("-", "")
            .replace(" ", "")
        )
        if "@" not in to_number:
            to_number = f"{to_number}@s.whatsapp.net"

        form_data = {"to": to_number, "ptt": "true"}
        files = {"file": (file_obj.name, file_obj.read(), file_obj.content_type)}

        # Pass the instance token when sending voice message
        success, node_resp = node_bridge.send_voice(
            instance.session_id,
            form_data,
            files,
            session_token=instance.token,
        )

        if success:
            try:
                Message.objects.create(
                    instance=instance,
                    remote_jid=to_number,
                    from_me=True,
                    content="[Áudio enviado via API]",
                    message_type="audio",
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Erro ao registrar áudio enviado via API: %s", exc)

            return Response(node_resp)

        return Response(node_resp, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SendInteractiveView(APIView, InstancePlanCheckMixin):
    """
    Endpoint unificado para:
    - /message/poll/
    - /message/location/
    - /message/contact/
    - /message/reaction/
    """
    authentication_classes = []
    permission_classes = [HasInstanceToken]

    def post(self, request, type):  # noqa: A003 - "type" é o path param
        instance, error_response = self.validate_instance_ready(request)
        if error_response:
            return error_response

        type = str(type).lower()

        if type == "location":
            serializer = SendLocationSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.send_location(
                instance.session_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        if type == "poll":
            serializer = SendPollSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            data = serializer.validated_data
            # A API moderna da Baileys espera o campo "options" (array de strings)
            # para enviar enquetes, porém nosso serializer permite tanto "values"
            # quanto "options". Abaixo, priorizamos "values" e, se ausente,
            # utilizamos o campo legado "options".
            opts = data.get("values") or data.get("options") or []
            node_payload = {
                "to": data["to"],
                "name": data["name"],
                "options": opts,
                "selectableCount": data.get("selectable_count", 1),
            }
            success, node_resp = node_bridge.send_poll(
                instance.session_id,
                node_payload,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        if type == "contact":
            serializer = SendContactSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            data = serializer.validated_data
            node_payload = {
                "to": data["to"],
                "fullName": data["full_name"],
                "phoneNumber": data["phone_number"],
            }
            success, node_resp = node_bridge.send_contact(
                instance.session_id,
                node_payload,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        if type == "reaction":
            serializer = SendReactionSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            data = serializer.validated_data
            # Nosso serializer já traz key completo; só mapeamos "emoji" -> "text"
            node_payload = {
                "to": data["to"],
                "text": data["emoji"],
                "key": data["key"],
            }
            success, node_resp = node_bridge.send_reaction(
                instance.session_id,
                node_payload,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"error": "Tipo de mensagem interativa inválido."}, status=status.HTTP_400_BAD_REQUEST)


# ==============================================================================
# 5. API PÚBLICA V1 - GESTÃO DE MENSAGENS E CHATS
# ==============================================================================


class MessageManageView(APIView, InstancePlanCheckMixin):
    """
    Ações sobre mensagens:
    - /message/manage/edit/
    - /message/manage/delete/
    - /message/manage/pin/
    - /message/manage/unpin/
    - /message/manage/star/
    """
    authentication_classes = []
    permission_classes = [HasInstanceToken]

    def post(self, request, action):
        instance, error_response = self.validate_instance_ready(request)
        if error_response:
            return error_response

        action = str(action).lower()

        if action == "edit":
            serializer = EditMessageSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.edit_message(
                instance.session_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        if action == "delete":
            serializer = MessageActionSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.delete_message(
                instance.session_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        if action == "pin":
            serializer = PinMessageSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.pin_message(
                instance.session_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        if action == "unpin":
            serializer = PinMessageSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.unpin_message(
                instance.session_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        if action == "star":
            serializer = StarMessageSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.star_message(
                instance.session_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"error": "Ação de mensagem inválida."}, status=status.HTTP_400_BAD_REQUEST)


class ChatManageView(APIView, InstancePlanCheckMixin):
    """
    Ações de chat:
    - /chat/manage/archive/
    - /chat/manage/mute/
    - /chat/manage/clear/
    - /chat/manage/mark-read/
    """
    authentication_classes = []
    permission_classes = [HasInstanceToken]

    def post(self, request, action):
        instance, error_response = self.validate_instance_ready(request)
        if error_response:
            return error_response

        action = str(action).lower()

        if action == "archive":
            serializer = ChatArchiveSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.archive_chat(
                instance.session_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        if action == "mute":
            serializer = ChatMuteSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.mute_chat(
                instance.session_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        if action == "clear":
            serializer = ChatActionSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.clear_chat(
                instance.session_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        if action == "mark-read":
            serializer = ChatActionSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.mark_chat_read(
                instance.session_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"error": "Ação de chat inválida."}, status=status.HTTP_400_BAD_REQUEST)


# ==============================================================================
# 6. API PÚBLICA V1 - GRUPOS
# ==============================================================================


class GroupView(APIView, InstancePlanCheckMixin):
    """
    - GET /groups/                      -> lista grupos
    - POST /groups/create/             -> cria grupo
    - POST /groups/join/               -> entra por código de convite
    """
    authentication_classes = []
    permission_classes = [HasInstanceToken]

    def get(self, request, action=None):
        """
        GET sem action -> lista grupos.
        """
        print("[DEBUG] GroupView GET chamado.")
        instance, error_response = self.validate_instance_ready(request)
        if error_response:
            print("[DEBUG] GroupView GET bloqueado por validate_instance_ready.")
            return error_response

        print("[DEBUG] GroupView GET: Fetching groups from Node...")
        success, node_resp = node_bridge.fetch_groups(
            instance.session_id,
            session_token=instance.token,
        )
        return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request, action=None):
        instance, error_response = self.validate_instance_ready(request)
        if error_response:
            return error_response

        action = str(action or "").lower()

        if action in ("", "create"):
            serializer = GroupCreateSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.create_group(
                instance.session_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        if action == "join":
            serializer = JoinGroupSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.join_group(
                instance.session_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"error": "Ação de grupo inválida."}, status=status.HTTP_400_BAD_REQUEST)


class GroupDetailView(APIView, InstancePlanCheckMixin):
    """
    Ações específicas sobre um grupo:
    - POST /groups/<id>/participants/      (add/remove/promote/demote)
    - POST /groups/<id>/leave/
    - POST /groups/<id>/revoke-invite/
    - PUT  /groups/<id>/subject/
    - PUT  /groups/<id>/description/
    - PUT  /groups/<id>/settings/
    - GET  /groups/<id>/invite-code/
    """
    authentication_classes = []
    permission_classes = [HasInstanceToken]

    def post(self, request, group_id, action):
        instance, error_response = self.validate_instance_ready(request)
        if error_response:
            return error_response

        action = str(action).lower()

        if action == "participants":
            serializer = GroupParticipantsSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.update_group_participants(
                instance.session_id,
                group_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        if action == "leave":
            success, node_resp = node_bridge.leave_group(
                instance.session_id,
                group_id,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        if action == "revoke-invite":
            success, node_resp = node_bridge.revoke_group_invite_code(
                instance.session_id,
                group_id,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"error": "Ação de grupo inválida."}, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, group_id, action):
        instance, error_response = self.validate_instance_ready(request)
        if error_response:
            return error_response

        action = str(action).lower()

        if action == "subject":
            serializer = GroupUpdateSubjectSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.update_group_subject(
                instance.session_id,
                group_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        if action == "description":
            serializer = GroupUpdateDescriptionSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.update_group_description(
                instance.session_id,
                group_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        if action == "settings":
            serializer = GroupSettingSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.update_group_setting(
                instance.session_id,
                group_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"error": "Ação de grupo inválida."}, status=status.HTTP_400_BAD_REQUEST)

    def get(self, request, group_id, action):
        instance, error_response = self.validate_instance_ready(request)
        if error_response:
            return error_response

        action = str(action).lower()

        if action == "invite-code":
            success, node_resp = node_bridge.get_group_invite_code(
                instance.session_id,
                group_id,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"error": "Ação de grupo inválida."}, status=status.HTTP_400_BAD_REQUEST)


# ==============================================================================
# 7. API PÚBLICA V1 - PERFIL E USUÁRIOS
# ==============================================================================


class ProfileView(APIView, InstancePlanCheckMixin):
    """
    - GET  /profile/info/<jid>/           -> informações de perfil
    - GET  /profile/blocklist/            -> lista de bloqueados
    - PUT  /profile/manage/status/        -> atualiza status
    - PUT  /profile/manage/picture/       -> atualiza foto
    """
    authentication_classes = []
    permission_classes = [HasInstanceToken]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, jid=None, action=None):
        print("[DEBUG] ProfileView GET chamado.")
        instance, error_response = self.validate_instance_ready(request)
        if error_response:
            return error_response

        # Se jid foi passado na URL -> /profile/info/<jid>/
        if jid:
            success, node_resp = node_bridge.fetch_profile(
                instance.session_id,
                jid,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Sem jid -> /profile/blocklist/
        success, node_resp = node_bridge.get_blocklist(
            instance.session_id,
            session_token=instance.token,
        )
        return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request, action=None):
        instance, error_response = self.validate_instance_ready(request)
        if error_response:
            return error_response

        action = str(action or "").lower()

        if action == "status":
            serializer = UpdateProfileStatusSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.update_profile_status(
                instance.session_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        if action == "picture":
            file_obj = request.FILES.get("file")
            if not file_obj:
                return Response(
                    {"error": 'Campo "file" é obrigatório.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            files = {"file": (file_obj.name, file_obj.read(), file_obj.content_type)}
            success, node_resp = node_bridge.update_profile_picture(
                instance.session_id,
                files,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"error": "Ação de perfil inválida."}, status=status.HTTP_400_BAD_REQUEST)


class UserActionView(APIView, InstancePlanCheckMixin):
    """
    - POST /users/block/      -> bloqueia/desbloqueia jid
    - POST /users/check/      -> verifica se está no WhatsApp
    """
    authentication_classes = []
    permission_classes = [HasInstanceToken]

    def post(self, request, action):
        instance, error_response = self.validate_instance_ready(request)
        if error_response:
            return error_response

        action = str(action).lower()

        if action == "block":
            serializer = BlockUserSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            success, node_resp = node_bridge.block_user(
                instance.session_id,
                serializer.validated_data,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        if action == "check":
            serializer = CheckOnWhatsappSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            jid = serializer.validated_data["jid"]
            success, node_resp = node_bridge.check_on_whatsapp(
                instance.session_id,
                jid,
                session_token=instance.token,
            )
            return Response(node_resp, status=status.HTTP_200_OK if success else status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"error": "Ação de usuário inválida."}, status=status.HTTP_400_BAD_REQUEST)


# ==============================================================================
# 8. WEBHOOK INTERNO (NODE -> DJANGO)
# ==============================================================================


@method_decorator(csrf_exempt, name="dispatch")
class InternalWebhookReceiver(View):
    """
    Endpoint chamado pelo servidor Node (WhatsApp Engine) para:
    - Atualizar status da sessão / QRCode.
    - Registrar mensagens recebidas.
    - Repassar eventos para o webhook do cliente, se configurado.
    """

    def post(self, request):
        # --- LOG 1: Recebimento da Requisição ---
        logger.info("[WEBHOOK] Recebido POST. Verificando API Key...") # Log de diagnóstico

        api_key = request.headers.get("x-api-key")
        
        # 1. Autenticação da Chave Mestra
        if api_key != getattr(settings, "NODE_API_KEY", ""):
            logger.error(f"[WEBHOOK] Falha na Autenticação. Chave Node enviada: {api_key}. Chave esperada: {getattr(settings, 'NODE_API_KEY', 'NÃO_CONFIGURADA')}")
            return JsonResponse({"error": "Unauthorized"}, status=401)

        # 2. Parseamento do JSON
        try:
            payload = json.loads(request.body)
        except Exception:  # noqa: BLE001
            logger.error(f"[WEBHOOK] JSON Inválido. Corpo recebido: {request.body.decode()}")
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        event_type = payload.get("type")
        data = payload.get("data") or {}
        session_id = payload.get("sessionId") or data.get("sessionId")
        
        # --- LOG 2: Dados da Sessão e Evento ---
        logger.info(f"[WEBHOOK] Evento: {event_type} | Session ID: {session_id}")

        if not session_id:
            return JsonResponse({"status": "ignored", "reason": "missing_session_id"}, status=400)

        # 3. Busca da Instância no Django
        try:
            instance = Instance.objects.get(session_id=session_id)
        except Instance.DoesNotExist:
            logger.warning(f"[WEBHOOK] Instância DJANGO não encontrada para Session ID: {session_id}")
            return JsonResponse({"status": "ignored", "reason": "instance_not_found"}, status=404)

        # 4. Trava de Recebimento para Planos Expirados
        owner = instance.owner
        plan_valid = owner.is_plan_valid
        
        if not plan_valid:
            logger.warning(f"[WEBHOOK] Evento ignorado. Plano do usuário {owner.username} expirou.")
            return JsonResponse({"status": "plan_expired_ignored"}, status=200)

        # 5. Processamento de Status / QR Code
        if event_type in ("session-update", "connection.update", "qr"):
            status_node = data.get("status")
            qr_code = data.get("qrCode") or data.get("qr") # <--- AQUI PEGA O BASE64
            token = data.get("token")
            me = data.get("me")

            # --- LOG 3: Recebimento do QR Code ---
            if qr_code:
                logger.info("[WEBHOOK] QR CODE RECEBIDO. Base64 com tamanho: %d bytes.", len(qr_code))
                logger.debug(f"[WEBHOOK] QR CODE DATA: {qr_code[:50]}...") # Exibe o começo do Base64
            else:
                logger.info(f"[WEBHOOK] QR Code NÃO está presente no evento {event_type}. Status Node: {status_node}.")

            # Atualização do Status (status_node)
            if status_node:
                if status_node == "open":
                    instance.status = "CONNECTED"
                elif status_node == "close":
                    instance.status = "DISCONNECTED"
                else:
                    instance.status = status_node

            # Atualização do Telefone Conectado (me/phoneNumber)
            if me:
                jid = me.get("id", "")
                if jid:
                    instance.phone_connected = jid.split(":")[0]
            elif data.get("phoneNumber"):
                instance.phone_connected = data.get("phoneNumber")

            # Atualização do Token de Acesso (token)
            if token:
                instance.token = token

            # Se a sessão está conectada mas o token não veio no evento (webhook "perdeu"),
            # fazemos sync direto no Node para persistir no Django.
            if (not token) and (not instance.token) and (
                instance.status == "CONNECTED" or status_node in ("open", "CONNECTED")
            ):
                logger.info("[WEBHOOK] Conectado sem token no evento. Sincronizando via /sessions ...")
                sync_instance_token(instance, bridge=node_bridge)

            # Se há QR, marca status de QR_SCANNED para o painel
            if qr_code and instance.status != "CONNECTED":
                instance.status = "QR_SCANNED"

            instance.save()
            logger.info(f"[WEBHOOK] Instância {session_id} salva com status: {instance.status}.")

        # 6. Processamento de Mensagens Recebidas (event_type == "message")
        if event_type == "message":
            msg_data = data
            key = msg_data.get("key", {}) or {}
            remote_jid = key.get("remoteJid")
            from_me = key.get("fromMe", False)
            wamid = key.get("id")
            push_name = msg_data.get("pushName", "")

            # Função auxiliar de "desembrulhamento" (unwrap_message) permanece igual
            def unwrap_message(msg_obj):
                """
                Remove wrappers (ephemeral, viewOnce etc.) para obter a mensagem "real".
                """
                if not msg_obj or not isinstance(msg_obj, dict):
                    return {}
                wrappers = [
                    "ephemeralMessage",
                    "viewOnceMessage",
                    "viewOnceMessageV2",
                    "documentWithCaptionMessage",
                    "editedMessage",
                ]
                for wrapper in wrappers:
                    if wrapper in msg_obj:
                        inner = msg_obj[wrapper].get("message")
                        return unwrap_message(inner)
                return msg_obj

            raw_msg = msg_data.get("message", {}) or {}
            real_msg = unwrap_message(raw_msg)

            message_content = (
                real_msg.get("conversation")
                or real_msg.get("extendedTextMessage", {}).get("text")
                or real_msg.get("imageMessage", {}).get("caption")
                or real_msg.get("videoMessage", {}).get("caption")
                or real_msg.get("documentMessage", {}).get("caption")
                or msg_data.get("content")
                or ""
            )

            msg_type = "text"
            if "imageMessage" in real_msg:
                msg_type = "image"
            elif "videoMessage" in real_msg:
                msg_type = "video"
            elif "audioMessage" in real_msg:
                msg_type = "audio"
            elif "documentMessage" in real_msg:
                msg_type = "document"

            # Registro da Mensagem no banco (apenas se for nova)
            if wamid and not Message.objects.filter(wamid=wamid).exists():
                try:
                    Message.objects.create(
                        instance=instance,
                        remote_jid=remote_jid,
                        from_me=from_me,
                        push_name=push_name,
                        content=message_content,
                        message_type=msg_type,
                        wamid=wamid,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error("Erro ao salvar mensagem recebida: %s", exc)

        # 7. Repasse para Webhook do Cliente (se configurado)
        try:
            webhook_conf = instance.webhook
        except WebhookConfig.DoesNotExist:
            webhook_conf = None

        if webhook_conf and webhook_conf.url:
            should_send = False

            if event_type == "message" and webhook_conf.send_messages:
                should_send = True
            elif event_type == "presence" and webhook_conf.send_presence:
                should_send = True
            elif event_type == "connection.update":
                should_send = True

            if should_send:
                try:
                    requests.post(webhook_conf.url, json=payload, timeout=5)
                    logger.debug(f"[WEBHOOK] Evento {event_type} repassado para o cliente: {webhook_conf.url}")
                except Exception as exc:  # noqa: BLE001
                    logger.error("Erro ao repassar webhook para cliente: %s", exc)

        return JsonResponse({"status": "processed"})
