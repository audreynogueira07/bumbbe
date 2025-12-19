const { WebSocketServer } = require('ws');

let wss;

/**
 * Inicializa o WebSocketServer ligado ao HTTP server passado.
 * @param {http.Server} server
 */
function setupWebSocket(server) {
    wss = new WebSocketServer({ server });
    wss.on('connection', (ws) => {
        console.log('[INFO] Cliente do painel conectado via WebSocket.');

        ws.on('message', (message) => {
            try {
                // CORREÇÃO: Converte a mensagem (que pode ser um Buffer) para string
                const parsed = JSON.parse(message.toString());
                const { type } = parsed;
                if (type === 'get-all-sessions') {
                    // quem pedir todas sessões recebe via broadcast apenas para si
                    const { getAllSessions } = require('./whatsapp');
                    const sessions = getAllSessions().map(s => ({
                        sessionId: s.sessionId,
                        status: s.status,
                        qr: s.qr || null,
                        qrCode: s.qrCode || null,
                        lastQrAt: s.lastQrAt || null,
                        hasEverConnected: !!s.hasEverConnected,
                        token: s.token || null,
                        name: s.name || '',
                        phoneNumber: s.phoneNumber || ''
                    }));
                    ws.send(JSON.stringify({ type: 'all-sessions', data: sessions }));
                                    }
            } catch (e) {
                console.error('[ERROR] Mensagem WebSocket inválida (após conversão):', message.toString());
            }
        });

        ws.on('close', () => {
            console.log('[INFO] Cliente do painel desconectado.');
        });

        ws.on('error', (err) => {
            console.error('[ERROR] WebSocket client error:', err);
        });
    });

    wss.on('listening', () => console.log('[INFO] WebSocketServer pronto.'));
}

/**
 * Broadcast helper que normaliza chamadas.
 * Pode ser usado como:
 * broadcast('session-update', { ... })
 * ou
 * broadcast({ type: 'session-update', data: {...} })
 *
 * Ele envia para todos os clients abertos.
 */
function broadcast(typeOrObj, data) {
    if (!wss) return;
    let message;
    if (typeof typeOrObj === 'object' && typeOrObj !== null && typeOrObj.type) {
        message = typeOrObj;
    } else if (typeof typeOrObj === 'string') {
        message = { type: typeOrObj, data: data === undefined ? null : data };
    } else {
        // inválido: ignora
        console.warn('[WARN] broadcast chamado com parâmetros inválidos.', typeOrObj, data);
        return;
    }

    const json = JSON.stringify(message);
    wss.clients.forEach(client => {
        if (client.readyState === client.OPEN) {
            try {
                client.send(json);
            } catch (err) {
                console.error('[ERROR] falha ao enviar broadcast para um client:', err);
            }
        }
    });
}

module.exports = {
    setupWebSocket,
    broadcast
};
