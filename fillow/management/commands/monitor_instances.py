import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from fillow.models import Instance
from fillow.services import NodeBridge, _map_node_status_to_django

# Configuração de Log
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Verifica e sincroniza o status das instâncias Bailey com o servidor Node.js'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.WARNING(f"[{timezone.now()}] Iniciando monitoramento de instâncias..."))
        
        bridge = NodeBridge()

        # 1. Busca lista completa de sessões no Node (Mais eficiente que verificar uma por uma)
        success, node_data = bridge.list_sessions()

        if not success:
            self.stdout.write(self.style.ERROR("ERRO: Não foi possível conectar ao servidor Node.js. Abortando."))
            return

        # Normaliza a resposta do Node (algumas versões retornam lista direta, outras dentro de 'data' ou 'sessions')
        active_sessions_list = []
        if isinstance(node_data, list):
            active_sessions_list = node_data
        elif isinstance(node_data, dict):
            active_sessions_list = node_data.get('sessions') or node_data.get('data') or node_data.get('result') or []

        # Cria um mapa para busca rápida: { 'session_id': {dados_da_sessao} }
        node_map = {
            s.get('sessionId'): s 
            for s in active_sessions_list 
            if isinstance(s, dict) and s.get('sessionId')
        }

        # 2. Itera sobre todas as instâncias do Banco de Dados
        instances = Instance.objects.all()
        updated_count = 0

        for instance in instances:
            db_status = instance.status
            node_session = node_map.get(instance.session_id)
            
            # --- CENÁRIO A: Sessão existe no Node ---
            if node_session:
                # 1. Verifica Status
                raw_status = node_session.get('status')
                real_status = _map_node_status_to_django(raw_status)
                
                # Se o Node diz "open", mas o banco não está CONNECTED
                if real_status and real_status != db_status:
                    self.stdout.write(f" -> Atualizando {instance.name}: {db_status} -> {real_status}")
                    instance.status = real_status
                    # Se conectou agora, garante updated_at
                    instance.save(update_fields=['status', 'updated_at'])
                    updated_count += 1

                # 2. Sincroniza Token (Self-Healing de Auth)
                # O token pode mudar se a sessão for restaurada no Node
                remote_token = (
                    node_session.get('token') or 
                    node_session.get('sessionToken') or 
                    node_session.get('bearerToken')
                )
                
                # Se achou token novo e é diferente do atual
                if remote_token and remote_token != instance.token:
                    self.stdout.write(f" -> Token atualizado para {instance.name}")
                    instance.token = remote_token
                    instance.save(update_fields=['token'])

                # 3. Sincroniza Telefone (Caso tenha mudado ou perdido)
                remote_phone = node_session.get('phoneNumber')
                if not remote_phone and node_session.get('me'):
                     # Tenta pegar de 'me': { 'id': '55119999999@s.whatsapp.net' }
                     jid = node_session['me'].get('id', '')
                     remote_phone = jid.split(':')[0] if jid else None

                if remote_phone and remote_phone != instance.phone_connected:
                    instance.phone_connected = remote_phone
                    instance.save(update_fields=['phone_connected'])

            # --- CENÁRIO B: Sessão NÃO existe no Node (Queda silenciosa ou reinício do servidor) ---
            else:
                # Se no banco diz que está CONECTADO, mas não está na lista do Node -> Desconectou
                if db_status == 'CONNECTED':
                    self.stdout.write(self.style.ERROR(f" -> DETECTADO ZUMBI: {instance.name} (DB: Connected | Node: Inexistente)"))
                    instance.status = 'DISCONNECTED'
                    instance.phone_connected = None
                    instance.token = None # Token inválido pois sessão morreu
                    instance.save(update_fields=['status', 'phone_connected', 'token', 'updated_at'])
                    updated_count += 1
                
                # Se estava QR_SCANNED ou CREATED e sumiu do Node, volta para CREATED ou DISCONNECTED
                elif db_status == 'QR_SCANNED':
                     instance.status = 'DISCONNECTED'
                     instance.save(update_fields=['status'])

        self.stdout.write(self.style.SUCCESS(f"[{timezone.now()}] Verificação concluída. {updated_count} instâncias atualizadas."))