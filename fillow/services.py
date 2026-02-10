import logging
import requests
import json
from django.conf import settings
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)

class NodeConnectionError(APIException):
    status_code = 503
    default_detail = 'O servidor de conexão (WhatsApp Engine) está indisponível ou inacessível.'
    default_code = 'service_unavailable'

class NodeBridge:
    """
    Ponte de comunicação entre Django e Node.js.
    Versão ULTIMATE: Suporta 100% dos endpoints do router.js atualizado.
    """

    def __init__(self):
        self.base_url = getattr(settings, 'NODE_API_URL', 'http://localhost:3000').rstrip('/')
        self.api_key = getattr(settings, 'NODE_API_KEY', '')
        self.default_timeout = getattr(settings, 'NODE_REQUEST_TIMEOUT', 30)
        
        # Headers padrão para rotas de ADMIN (que usam x-api-key)
        self.headers = {
            'Content-Type': 'application/json',
            'x-api-key': self.api_key
        }

    def _request(self, method, endpoint, data=None, files=None, is_multipart=False, timeout=None, session_token=None):
        """
        Método interno para realizar requisições HTTP ao Node.js.
        Aceita session_token para rotas que exigem autenticação de usuário (Bearer).
        """
        if not endpoint.startswith('/'):
            endpoint = f'/{endpoint}'
            
        url = f"{self.base_url}{endpoint}"
        req_headers = self.headers.copy()

        # LÓGICA DE AUTENTICAÇÃO HÍBRIDA:
        # Se um token de sessão for fornecido (rotas do usuário), usamos Authorization: Bearer.
        # Caso contrário, mantemos o x-api-key (rotas de admin).
        if session_token:
            req_headers['Authorization'] = f'Bearer {session_token}'
            # Remove a x-api-key, pois a rota de usuário não precisa dela
            req_headers.pop('x-api-key', None)
        
        if is_multipart:
            # Não pode enviar Content-Type: application/json em multipart, a lib requests define o boundary
            req_headers.pop('Content-Type', None)

        request_timeout = timeout if timeout else self.default_timeout

        try:
            response = requests.request(
                method, 
                url, 
                json=data if not is_multipart else None,
                data=data if is_multipart else None,
                files=files,
                headers=req_headers, 
                timeout=request_timeout
            )
            
            if response.status_code >= 400:
                try:
                    error_json = response.json()
                    logger.error(f"Erro Node ({response.status_code}) em {url}: {error_json}")
                    return False, error_json
                except:
                    logger.error(f"Erro Node ({response.status_code}) em {url}: {response.text}")
                    return False, {'error': response.text}
            
            return True, response.json() if response.content else {}

        except requests.exceptions.Timeout:
            logger.error(f"TIMEOUT Node em {url}")
            return False, {"error": "Timeout no servidor Node."}
        except requests.RequestException as e:
            logger.critical(f"FALHA NODE: {e}")
            return False, {"error": "Node server unreachable"}

    # ==========================================================================
    # SESSÃO E CONEXÃO (Rotas Administrativas ou Públicas)
    # ==========================================================================
    def create_session(self, session_id, timeout=None):
        # Rota de Admin (usa x-api-key)
        # timeout maior reduz falso-positivo de "falhou", quando o Baileys demora para subir sessão
        return self._request('POST', '/sessions/start', {'sessionId': session_id}, timeout=timeout)

    def delete_session(self, session_id):
        # Rota de Admin (usa x-api-key)
        return self._request('DELETE', f'/sessions/{session_id}')

    def logout_session(self, session_id):
        return self.delete_session(session_id)

    def get_status(self, session_id, session_token=None):
        # Rota protegida por token de sessão
        return self._request('GET', f'/{session_id}/status', session_token=session_token)

    def get_qrcode(self, session_id):
        """
        Busca status + QR da sessão.

        1) Tenta rota administrativa /sessions/:id/qr (retorna qr + qrCode + status)
        2) Fallback para rota pública /:id/check-connection (compatibilidade)
        """
        ok, data = self._request('GET', f'/sessions/{session_id}/qr')
        if ok:
            return ok, data
        # fallback de compatibilidade
        return self._request('GET', f'/{session_id}/check-connection')

    def list_sessions(self):
        """Lista todas as sessões no Node (rota administrativa protegida por x-api-key)."""
        return self._request('GET', '/sessions')

    # ==========================================================================
    # MENSAGENS E MÍDIA (Rotas de Usuário - Exigem session_token)
    # ==========================================================================
    def send_message(self, session_id, payload, session_token=None):
        return self._request('POST', f"/{session_id}/messages/send", payload, session_token=session_token)

    def send_media(self, session_id, form_data, files, session_token=None):
        return self._request('POST', f"/{session_id}/messages/send-media", data=form_data, files=files, is_multipart=True, timeout=120, session_token=session_token)

    def send_voice(self, session_id, form_data, files, session_token=None):
        return self._request('POST', f"/{session_id}/messages/send-voice", data=form_data, files=files, is_multipart=True, timeout=120, session_token=session_token)

    def send_poll(self, session_id, payload, session_token=None):
        """
        Envia uma enquete. A API moderna da Baileys expõe /messages/poll em vez
        de /messages/send-poll. Para manter compatibilidade com versões
        anteriores, este método redireciona a rota conforme necessário.
        """
        return self._request('POST', f"/{session_id}/messages/poll", payload, session_token=session_token)

    def send_location(self, session_id, payload, session_token=None):
        return self._request('POST', f"/{session_id}/messages/location", payload, session_token=session_token)

    def send_contact(self, session_id, payload, session_token=None):
        return self._request('POST', f"/{session_id}/messages/contact", payload, session_token=session_token)

    def send_reaction(self, session_id, payload, session_token=None):
        return self._request('POST', f"/{session_id}/messages/reaction", payload, session_token=session_token)

    # ==========================================================================
    # GESTÃO DE MENSAGENS (EDITAR, PINAR, APAGAR, FAVORITAR)
    # ==========================================================================
    def edit_message(self, session_id, payload, session_token=None):
        """
        Edita uma mensagem existente. O payload deve conter:
        { 'to': jid, 'text': novo_texto, 'key': { id, fromMe?, remote_jid? } }
        """
        return self._request('POST', f"/{session_id}/messages/edit", payload, session_token=session_token)

    def delete_message(self, session_id, payload, session_token=None):
        return self._request('POST', f"/{session_id}/messages/delete", payload, session_token=session_token)

    def pin_message(self, session_id, payload, session_token=None):
        """
        Fixa um chat no topo. O payload deve conter { 'to': jid }.
        O campo opcional 'time' é ignorado pela API atual.
        """
        return self._request('POST', f"/{session_id}/messages/pin", payload, session_token=session_token)

    def unpin_message(self, session_id, payload, session_token=None):
        return self._request('POST', f"/{session_id}/messages/unpin", payload, session_token=session_token)

    def star_message(self, session_id, payload, session_token=None):
        """
        (Des)marca uma mensagem como favorita. Payload: { 'to': jid, 'key': { id, from_me }, 'star': bool }
        """
        return self._request('POST', f"/{session_id}/messages/star", payload, session_token=session_token)

    # ==========================================================================
    # GESTÃO DE CHAT (ARQUIVAR, MUTE, LIMPAR)
    # ==========================================================================
    def archive_chat(self, session_id, payload, session_token=None):
        """
        Arquiva ou desarquiva um chat. Payload deve conter { 'to': jid, 'archive': bool }.
        """
        return self._request('POST', f"/{session_id}/chats/archive", payload, session_token=session_token)

    def mute_chat(self, session_id, payload, session_token=None):
        return self._request('POST', f"/{session_id}/chats/mute", payload, session_token=session_token)

    def clear_chat(self, session_id, payload, session_token=None):
        return self._request('POST', f"/{session_id}/chats/clear", payload, session_token=session_token)

    def mark_chat_read(self, session_id, payload, session_token=None):
        return self._request('POST', f"/{session_id}/chats/mark-read", payload, session_token=session_token)

    # ==========================================================================
    # GRUPOS
    # ==========================================================================
    def fetch_groups(self, session_id, session_token=None):
        return self._request('GET', f"/{session_id}/groups", session_token=session_token)

    def create_group(self, session_id, payload, session_token=None):
        return self._request('POST', f"/{session_id}/groups/create", payload, session_token=session_token)

    def update_group_participants(self, session_id, group_id, payload, session_token=None):
        return self._request('POST', f"/{session_id}/groups/{group_id}/participants", payload, session_token=session_token)

    def update_group_setting(self, session_id, group_id, payload, session_token=None):
        return self._request('PUT', f"/{session_id}/groups/{group_id}/settings", payload, session_token=session_token)

    def update_group_subject(self, session_id, group_id, payload, session_token=None):
        return self._request('PUT', f"/{session_id}/groups/{group_id}/subject", payload, session_token=session_token)

    def update_group_description(self, session_id, group_id, payload, session_token=None):
        return self._request('PUT', f"/{session_id}/groups/{group_id}/description", payload, session_token=session_token)

    def get_group_invite_code(self, session_id, group_id, session_token=None):
        return self._request('GET', f"/{session_id}/groups/{group_id}/invite-code", session_token=session_token)

    def revoke_group_invite_code(self, session_id, group_id, session_token=None):
        return self._request('POST', f"/{session_id}/groups/{group_id}/revoke-invite", session_token=session_token)
    
    def leave_group(self, session_id, group_id, session_token=None):
        return self._request('POST', f"/{session_id}/groups/{group_id}/leave", session_token=session_token)

    def join_group(self, session_id, payload, session_token=None):
        return self._request('POST', f"/{session_id}/groups/join", payload, session_token=session_token)

    # ==========================================================================
    # PERFIL E BLOQUEIO
    # ==========================================================================
    def fetch_profile(self, session_id, jid, session_token=None):
        return self._request('GET', f"/{session_id}/profile/{jid}", session_token=session_token)

    def update_profile_status(self, session_id, payload, session_token=None):
        return self._request('PUT', f"/{session_id}/profile/status", payload, session_token=session_token)

    def update_profile_picture(self, session_id, files, session_token=None):
        # Envia apenas arquivo, sem form_data extra, conforme router.js
        return self._request('PUT', f"/{session_id}/profile/picture", files=files, is_multipart=True, session_token=session_token)

    def block_user(self, session_id, payload, session_token=None):
        return self._request('POST', f"/{session_id}/users/block", payload, session_token=session_token)

    def get_blocklist(self, session_id, session_token=None):
        return self._request('GET', f"/{session_id}/users/blocklist", session_token=session_token)

    def check_on_whatsapp(self, session_id, jid, session_token=None):
        return self._request('GET', f"/{session_id}/on-whatsapp/{jid}", session_token=session_token)

# ==============================================================================
# SINCRONIZAÇÃO (SELF-HEALING) — NODE -> DJANGO
# ==============================================================================

def _map_node_status_to_django(status_value):
    """Normaliza status vindos do Node/Baileys para o padrão do Django."""
    if not status_value:
        return None
    sv = str(status_value).strip()
    if sv == "open":
        return "CONNECTED"
    if sv == "close":
        return "DISCONNECTED"
    # Mantém valores já normalizados (CONNECTED, DISCONNECTED, PENDING etc.)
    return sv


def sync_instance_token(instance, bridge=None):
    """
    Sincroniza (best-effort) token/status/telefone do Node -> Django consultando
    a rota administrativa GET /sessions (protegida por x-api-key).

    Retorna True se conseguiu localizar a sessão e aplicar (ou confirmar) token.
    Retorna False se não encontrou sessão, não havia token disponível, ou houve erro.
    """
    try:
        b = bridge or NodeBridge()
        ok, data = b.list_sessions()
        if not ok or not isinstance(data, list):
            return False

        session_id = getattr(instance, "session_id", None) or getattr(instance, "sessionId", None)
        if not session_id:
            return False

        target = next((s for s in data if isinstance(s, dict) and s.get("sessionId") == session_id), None)
        if not target:
            return False

        changed_fields = []

        # Token
        new_token = target.get("token")
        if new_token and new_token != getattr(instance, "token", None):
            instance.token = new_token
            changed_fields.append("token")

        # Status
        node_status = _map_node_status_to_django(target.get("status"))
        if node_status and node_status != getattr(instance, "status", None):
            instance.status = node_status
            changed_fields.append("status")

        # Telefone conectado
        phone = target.get("phoneNumber")
        if phone is not None and phone != getattr(instance, "phone_connected", None):
            instance.phone_connected = phone or None
            changed_fields.append("phone_connected")

        if changed_fields:
            try:
                instance.save(update_fields=changed_fields)
            except Exception:
                instance.save()

        # Se existe token no Node, consideramos sync OK mesmo que já estivesse igual
        return bool(new_token)

    except Exception as exc:  # noqa: BLE001
        logger.warning("Falha ao sincronizar token da instância: %s", exc)
        return False


def wait_for_qr(bridge, session_id, timeout_seconds=45, poll_interval=1.5):
    """
    Faz polling curto para acelerar entrega do QR após clicar em "Iniciar Sessão".

    Retorna dict com:
      {"status": <str|None>, "qrcode": <data-url|None>, "qr": <texto|None>, "raw": <payload>}
    """
    import time

    deadline = time.time() + max(1, int(timeout_seconds))
    last_payload = {}

    while time.time() < deadline:
        ok, payload = bridge.get_qrcode(session_id)
        if ok and isinstance(payload, dict):
            last_payload = payload
            status_raw = payload.get('status')
            status_norm = _map_node_status_to_django(status_raw)
            qrcode = payload.get('qrCode') or payload.get('qrcode')
            qr_text = payload.get('qr')

            # condição de sucesso: já conectou ou já temos QR pra exibir
            if status_norm == 'CONNECTED' or qrcode or qr_text:
                return {
                    'status': status_norm,
                    'qrcode': qrcode,
                    'qr': qr_text,
                    'raw': payload,
                }

        time.sleep(max(0.3, float(poll_interval)))

    return {
        'status': _map_node_status_to_django(last_payload.get('status')) if isinstance(last_payload, dict) else None,
        'qrcode': (last_payload.get('qrCode') or last_payload.get('qrcode')) if isinstance(last_payload, dict) else None,
        'qr': last_payload.get('qr') if isinstance(last_payload, dict) else None,
        'raw': last_payload if isinstance(last_payload, dict) else {},
    }
