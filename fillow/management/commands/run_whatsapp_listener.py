import json
import time
import websocket
import threading
from django.core.management.base import BaseCommand
from django.conf import settings
from fillow.models import Instance, Message

# [ADAPTAÇÃO] Importa a função que aciona o motor do chatbot
# Certifique-se de que o app onde está o engine.py se chama 'chatbot'
try:
    from chatbot.engine import process_incoming_message
except ImportError:
    # Fallback caso o import falhe, para não quebrar o listener, mas avisa no log
    process_incoming_message = None
    print("AVISO: chatbot.engine não encontrado. O bot não responderá automaticamente.")

class Command(BaseCommand):
    help = 'Inicia o listener WebSocket para receber mensagens do WhatsApp em tempo real e acionar o Chatbot.'

    def handle(self, *args, **options):
        # Configuração
        node_url = getattr(settings, 'NODE_API_URL', 'http://localhost:3000')
        # Converte http/https para ws/wss
        ws_url = node_url.replace("https://", "wss://").replace("http://", "ws://")
        
        self.stdout.write(self.style.SUCCESS(f'--- Iniciando Listener WhatsApp em {ws_url} ---'))

        def on_message(ws, message):
            try:
                data = json.loads(message)
                msg_type = data.get("type")
                payload = data.get("data", {})

                # Filtra apenas mensagens
                if msg_type == "message":
                    self.process_message(payload)
                
                # Opcional: Atualizar status se receber evento de conexão
                elif msg_type == "connection.update":
                    self.process_connection(payload)

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Erro ao processar mensagem do socket: {e}"))

        def on_error(ws, error):
            self.stdout.write(self.style.ERROR(f"Erro WebSocket: {error}"))

        def on_close(ws, close_status_code, close_msg):
            self.stdout.write(self.style.WARNING("Conexão fechada. Tentando reconectar em 5s..."))
            time.sleep(5)
            start_socket() # Reconexão automática

        def on_open(ws):
            self.stdout.write(self.style.SUCCESS("Conectado ao WebSocket do Node!"))
            # Solicita sessões para garantir sincronia (opcional)
            ws.send(json.dumps({"type": "get-all-sessions"}))

        def start_socket():
            ws = websocket.WebSocketApp(
                ws_url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            ws.run_forever()

        # Inicia o loop
        start_socket()

    def process_message(self, data):
        """Salva a mensagem no banco de dados E ACIONA O CHATBOT"""
        try:
            session_id = data.get("sessionId")
            if not session_id: return

            # Verifica se a instância existe no banco
            try:
                instance = Instance.objects.get(session_id=session_id)
                
                # --- CORREÇÃO IMPORTANTE PARA TOKEN INVÁLIDO ---
                # Garante que temos os dados mais recentes do banco (incluindo tokens renovados)
                instance.refresh_from_db() 
                # -----------------------------------------------

            except Instance.DoesNotExist:
                return # Ignora sessões que não estão no painel

            # Dados da mensagem
            key = data.get("key", {})
            remote_jid = key.get("remoteJid")
            from_me = key.get("fromMe", False)
            wamid = key.get("id")
            push_name = data.get("pushName", "")

            if not remote_jid: return

            # Extração de Conteúdo (Lógica Unwrap)
            msg_obj = data.get("message", {})
            
            def unwrap(m):
                for k in ['ephemeralMessage', 'viewOnceMessage', 'viewOnceMessageV2', 'documentWithCaptionMessage']:
                    if k in m: return unwrap(m[k].get('message', {}))
                return m
            
            real_msg = unwrap(msg_obj)
            
            # Extrai texto ou caption
            content = (
                real_msg.get("conversation") or 
                real_msg.get("extendedTextMessage", {}).get("text") or
                real_msg.get("imageMessage", {}).get("caption") or 
                real_msg.get("videoMessage", {}).get("caption") or 
                real_msg.get("documentMessage", {}).get("caption") or 
                ""
            )

            # Define tipo
            msg_type = 'text'
            if 'imageMessage' in real_msg: msg_type = 'image'
            elif 'videoMessage' in real_msg: msg_type = 'video'
            elif 'audioMessage' in real_msg: msg_type = 'audio'
            elif 'documentMessage' in real_msg: msg_type = 'document'
            elif 'stickerMessage' in real_msg: msg_type = 'sticker'

            # 1. SALVAR NO BANCO DE DADOS
            # Evita duplicidade
            if wamid and not Message.objects.filter(wamid=wamid).exists():
                Message.objects.create(
                    instance=instance,
                    remote_jid=remote_jid,
                    from_me=from_me,
                    push_name=push_name,
                    content=content,
                    message_type=msg_type,
                    wamid=wamid
                )
                
                direction = "Enviada" if from_me else "Recebida"
                self.stdout.write(f"[{instance.name}] Msg {direction}: {content[:30]}...")

                # -----------------------------------------------------------
                # [ADAPTAÇÃO] 2. GATILHO DO CHATBOT
                # -----------------------------------------------------------
                # Verifica se o engine foi importado, se não sou eu quem enviei, e se tem conteúdo
                if process_incoming_message and not from_me and content:
                    self.stdout.write(self.style.NOTICE(f"[{instance.name}] 🤖 Acionando Chatbot..."))
                    
                    try:
                        # Chama a função do engine.py
                        # Como ela já cria uma Thread interna, isso não vai bloquear o WebSocket
                        process_incoming_message(
                            instance=instance, # A instância agora está atualizada pelo refresh_from_db()
                            message_text=content,
                            remote_jid=remote_jid,
                            push_name=push_name
                        )
                    except Exception as bot_error:
                        self.stdout.write(self.style.ERROR(f"Erro ao disparar chatbot: {bot_error}"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Erro ao salvar/processar msg: {e}"))

    def process_connection(self, data):
        """Atualiza status da instância"""
        try:
            session_id = data.get("sessionId")
            status = data.get("status") or data.get("connection")
            qr = data.get("qr")
            
            if not session_id: return
            
            try:
                instance = Instance.objects.get(session_id=session_id)
            except Instance.DoesNotExist: return

            if status == 'open':
                instance.status = 'CONNECTED'
                # Atualiza telefone se vier
                me = data.get("me", {})
                if me and me.get("id"):
                    instance.phone_connected = me.get("id").split(":")[0]
            elif status == 'close':
                instance.status = 'DISCONNECTED'
            elif qr:
                instance.status = 'QR_SCANNED'
            
            instance.save()
            self.stdout.write(f"[{instance.name}] Status atualizado: {instance.status}")

        except Exception as e:
            pass