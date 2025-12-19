/*
 * whatsapp_robust.js — versão corrigida para 2025
 *
 * Este módulo expõe uma API robusta para gerenciar sessões do WhatsApp
 * através da biblioteca Baileys. A intenção aqui é fornecer um canal
 * único para todas as informações que a Baileys é capaz de enviar,
 * expondo-as através de um mecanismo de broadcast (via WebSocket ou
 * outro canal).
 *
 * MODIFICAÇÕES RECENTES:
 * - Fixação da versão do WhatsApp Web para evitar instabilidades.
 * - Ajuste na configuração do browser via 'Browsers.appropriate'.
 * - Desativação da sincronização completa de histórico ('syncFullHistory')
 *   para otimizar o startup e evitar loops de dados antigos.
 * - Adicionado envio opcional de eventos para um webhook HTTP (Django),
 *   sem quebrar a API existente baseada em WebSocket.
 */

const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  Browsers // IMPORTANTE: para configurar o browser de forma compatível
} = require('@whiskeysockets/baileys');
const pino = require('pino');
const path = require('path');
const fs = require('fs-extra');
const qrcode = require('qrcode');
const { randomBytes } = require('crypto');
const axios = require('axios');

// Fallback broadcast importado para quando nenhuma função personalizada é injetada
const { broadcast: fallbackBroadcast } = require('./websocket');

// Mapeia sessionId -> dados da sessão
const sessions = new Map();

// Logger configurado com pino-pretty para melhor depuração
const logger = pino({
  transport: { target: 'pino-pretty' },
  level: process.env.LOG_LEVEL || 'info'
});

// Diretório onde as credenciais de autenticação de cada sessão são armazenadas
const AUTH_DIR = path.join(__dirname, 'auth');
fs.ensureDirSync(AUTH_DIR);

// Configuração do webhook HTTP (por exemplo, Django)
// Se não houver URL, o webhook fica desativado e NADA muda para outros serviços.
const DJANGO_WEBHOOK_URL =
  process.env.DJANGO_WEBHOOK_URL ||
  process.env.DJANGO_WEBHOOK ||
  null;

// A mesma chave usada pelo Django em settings.NODE_API_KEY
const DJANGO_WEBHOOK_API_KEY =
  process.env.NODE_API_KEY ||
  process.env.DJANGO_WEBHOOK_API_KEY ||
  null;

// ==============================================================================
// CONFIGURAÇÕES DE QR (OTIMIZAÇÃO DE LATÊNCIA)
// ==============================================================================
// QR_IMAGE_MODE:
// - 'svg'  -> gera uma imagem leve em SVG (data:image/svg+xml) de forma assíncrona (recomendado)
// - 'png'  -> gera PNG base64 (mais pesado)
// - 'none' -> NÃO gera imagem, envia apenas o texto do QR (mais rápido)
const QR_IMAGE_MODE = (process.env.QR_IMAGE_MODE || 'svg').toLowerCase();
const QR_ERROR_CORRECTION = (process.env.QR_ERROR_CORRECTION || 'L').toUpperCase();
const QR_MARGIN = Number.isFinite(parseInt(process.env.QR_MARGIN || '1', 10))
  ? parseInt(process.env.QR_MARGIN || '1', 10)
  : 1;
const QR_SCALE = Number.isFinite(parseInt(process.env.QR_SCALE || '4', 10))
  ? parseInt(process.env.QR_SCALE || '4', 10)
  : 4;

// Referência interna para função de broadcast injetada externamente
let injectedBroadcast = null;

/**
 * Injeta uma função de broadcast personalizada no módulo. Caso seja
 * fornecida, essa função será utilizada para emitir eventos para o
 * painel/cliente; caso contrário, será utilizado o broadcast de
 * websocket padrão.
 *
 * @param {function} broadcastFn Função para transmitir eventos para o painel
 */
function initialize(broadcastFn) {
  if (typeof broadcastFn === 'function') {
    injectedBroadcast = broadcastFn;
    logger.info('[INFO] broadcast injetado no módulo whatsapp.');
  } else {
    logger.warn('[WARN] initialize recebeu parâmetro não-função.');
  }
}

/**
 * Emite um evento para o frontend via mecanismo de broadcast (WebSocket)
 * e, opcionalmente, para um webhook HTTP (ex.: Django).
 *
 * IMPORTANTE:
 * - A assinatura e o comportamento para WebSocket permanecem os mesmos
 *   para não quebrar serviços já existentes.
 * - O envio HTTP é "fire-and-forget": não bloqueia nem altera o fluxo.
 *
 * @param {string} type Nome do evento
 * @param {any} data Dados a serem enviados
 */
function emit(type, data) {
  // 1) Broadcast normal (WebSocket) — comportamento antigo preservado
  try {
    const b = injectedBroadcast || fallbackBroadcast || (() => {});
    b(type, data);
  } catch (err) {
    logger.error({ err }, '[ERROR] erro ao emitir evento para o painel (WebSocket)');
  }

  // 2) Envio opcional para webhook HTTP (Django)
  try {
    if (!DJANGO_WEBHOOK_URL) {
      return; // se não tiver URL configurada, não faz nada
    }

    // Tenta extrair um sessionId coerente
    let sessionId = null;
    if (data && typeof data === 'object') {
      if (data.sessionId || data.session_id) {
        sessionId = data.sessionId || data.session_id;
      } else if (data.session && (data.session.sessionId || data.session.session_id)) {
        sessionId = data.session.sessionId || data.session.session_id;
      }
    }

    const payload = {
      type,
      data,
      sessionId
    };

    const headers = {
      'Content-Type': 'application/json'
    };

    if (DJANGO_WEBHOOK_API_KEY) {
      headers['x-api-key'] = DJANGO_WEBHOOK_API_KEY;
    }

    // Fire and forget: não usamos await para não travar o fluxo
    axios
      .post(DJANGO_WEBHOOK_URL, payload, { headers })
      .catch((err) => {
        logger.error(
          { err: err.message },
          '[ERROR] falha ao enviar webhook HTTP para backend'
        );
      });
  } catch (err) {
    logger.error({ err }, '[ERROR] erro inesperado na rotina de webhook HTTP');
  }
}

/**
 * Sanitiza um objeto de sessão removendo propriedades internas (como
 * instâncias de sockets e funções), retornando apenas informações
 * seguras que podem ser enviadas ao cliente.
 *
 * @param {object} session Objeto de sessão armazenado no mapa
 * @returns {object|null} Sessão sanitizada ou null se entrada for nula
 */
function sanitizeSession(session) {
  if (!session) return null;
  return {
    sessionId: session.sessionId,
    status: session.status,
    qr: session.qr || null,
    qrCode: session.qrCode || null,
    lastQrAt: session.lastQrAt || null,
    hasEverConnected: !!session.hasEverConnected,
    token: session.token || null,
    name: session.name || '',
    phoneNumber: session.phoneNumber || ''
  };
}

/**
 * Recupera uma sessão pelo ID. Retorna o objeto interno com socket anexado.
 *
 * @param {string} sessionId Identificador da sessão
 * @returns {object|null} Objeto de sessão ou null se não existir
 */
const getSession = (sessionId) => {
  return sessions.get(sessionId) || null;
};

/**
 * Retorna todas as sessões atualmente armazenadas (objetos internos).
 *
 * @returns {object[]} Array de objetos de sessão
 */
const getAllSessions = () => {
  return Array.from(sessions.values());
};

/**
 * Remove completamente uma sessão: faz logout, remove credenciais
 * e informa o painel.
 *
 * @param {string} sessionId Identificador da sessão a ser removida
 */
async function deleteSession(sessionId) {
  const session = sessions.get(sessionId);
  if (session) {
    try {
      if (session.socket?.logout) {
        await session.socket.logout();
      }
    } catch (error) {
      logger.warn({ error }, `[WARN] erro ao dar logout na sessão ${sessionId}`);
    }
    sessions.delete(sessionId);
  }
  const authDir = path.join(AUTH_DIR, sessionId);
  try {
    await fs.remove(authDir);
  } catch (err) {
    logger.warn({ err }, `[WARN] erro ao remover diretório de autenticação ${authDir}`);
  }
  const sanitized = sanitizeSession(session) || { sessionId };
  emit('session-update', { ...sanitized, status: 'DELETED' });
  logger.info(`[INFO] Sessão ${sessionId} removida.`);
}

/**
 * Inicia ou restaura uma sessão WhatsApp identificada por `sessionId`.
 * Modificações aplicadas para estabilidade em 2025: versão hardcoded,
 * browser desktop e desativação de syncFullHistory.
 *
 * @param {string} sessionId Identificador único da sessão
 * @returns {Promise<object>} Objeto de dados da sessão
 */
async function startSession(sessionId) {
  // Se já existir uma sessão ativa ou pendente, apenas a retorna
  const existing = sessions.get(sessionId);
  if (existing && existing.status !== 'DISCONNECTED') {
    logger.warn(`[WARN] Sessão ${sessionId} já está ativa ou pendente.`);
    emit('session-update', sanitizeSession(existing));
    return existing;
  }

  // Garante que o diretório de autenticação da sessão exista
  const authDir = path.join(AUTH_DIR, sessionId);
  await fs.ensureDir(authDir);

  // Obtém estado e função para salvar credenciais
  const { state, saveCreds } = await useMultiFileAuthState(authDir);

  // Fixação da versão do protocolo WhatsApp Web (Compatível Nov/2025).
  // Removemos fetchLatestBaileysVersion para evitar requests desnecessários
  // e inconsistências de versão.
  const waVersion = [2, 3000, 1029030078];
  logger.info(`[INFO] Usando versão hardcoded do WA: v${waVersion.join('.')}`);

  // Objeto de dados da sessão
  const sessionData = {
    sessionId,
    socket: null,
    status: 'PENDING',
    // qr = texto do QR (rápido para repassar ao Django e para o frontend gerar imagem)
    qr: null,
    // qrCode = imagem (data URL) opcional (pode ser 'svg' ou 'png', ver QR_IMAGE_MODE)
    qrCode: null,
    lastQrAt: null,
    hasEverConnected: false,
    token: null,
    name: '',
    phoneNumber: '',
    // controles internos para evitar loops e duplicidade
    _reconnectTimer: null,
    _qrConvertTimer: null
  };

  sessions.set(sessionId, sessionData);
  emit('session-update', sanitizeSession(sessionData));

  // Cria o socket do WhatsApp com as novas configurações solicitadas
  const sock = makeWASocket({
    version: waVersion,
    logger: pino({ level: 'silent' }), // Desabilita logs internos
    printQRInTerminal: false,
    auth: state,
    // Configura um browser desktop apropriado para garantir pareamento correto
    browser: Browsers.appropriate('Desktop'),
    // Desativa sincronização total do histórico para evitar sobrecarga inicial
    syncFullHistory: false,
    keepAliveIntervalMs: 30000,
    // Função stub para mensagens não disponíveis
    getMessage: async () => ({ conversation: 'message-not-available' })
  });

  // Atualiza o objeto de sessão com o socket ativo
  sessionData.socket = sock;

  // Atualização de credenciais agora utiliza wrapper assíncrono explícito
  sock.ev.on('creds.update', async () => await saveCreds());

  /**
   * Listener para eventos de atualização de conexão.
   */
  let reconnectAttempts = 0;
  const maxReconnectDelay = 60 * 1000;

  sock.ev.on('connection.update', async (update) => {
    try {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        // Guardamos o QR como texto (isso é o que realmente importa para pareamento)
        // e emitimos imediatamente — isso reduz bastante a "demora" percebida.
        sessionData.qr = qr;
        sessionData.lastQrAt = Date.now();

        // Emissão rápida: o Django e/ou frontend já recebem o texto do QR sem esperar imagem/base64.
        emit('qr', { sessionId, qr: sessionData.qr, src: sessionData.qrCode || null });

        // Geração opcional de imagem (data URL) em modo assíncrono + debounce.
        // Isso mantém compatibilidade com frontends que esperam "src",
        // sem bloquear o fluxo crítico do evento.
        if (QR_IMAGE_MODE !== 'none') {
          try {
            if (sessionData._qrConvertTimer) {
              clearTimeout(sessionData._qrConvertTimer);
              sessionData._qrConvertTimer = null;
            }

            sessionData._qrConvertTimer = setTimeout(async () => {
              try {
                const currentQr = sessionData.qr;
                if (!currentQr) return;

                let dataUrl = null;

                if (QR_IMAGE_MODE === 'png') {
                  dataUrl = await qrcode.toDataURL(currentQr, {
                    errorCorrectionLevel: QR_ERROR_CORRECTION,
                    margin: QR_MARGIN,
                    scale: QR_SCALE
                  });
                } else {
                  // default: svg (mais leve)
                  const svg = await qrcode.toString(currentQr, {
                    type: 'svg',
                    errorCorrectionLevel: QR_ERROR_CORRECTION,
                    margin: QR_MARGIN
                  });
                  dataUrl = 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
                }

                // Só atualiza se ainda for o mesmo QR
                if (sessionData.qr === currentQr) {
                  sessionData.qrCode = dataUrl;
                  emit('qr', { sessionId, qr: sessionData.qr, src: sessionData.qrCode });
                  emit('session-update', sanitizeSession(sessionData));
                }
              } catch (err) {
                logger.error({ err }, '[ERROR] Falha ao gerar imagem do QR code');
              } finally {
                sessionData._qrConvertTimer = null;
              }
            }, 0);
          } catch (err) {
            logger.error({ err }, '[ERROR] Falha ao agendar geração de imagem do QR code');
          }
        }
      }

      if (connection === 'open') {
        sessionData.status = 'CONNECTED';
        sessionData.hasEverConnected = true;

        // Após conectar, não precisamos manter QR em memória
        sessionData.qr = null;
        sessionData.qrCode = null;
        sessionData.lastQrAt = null;

        // Cancela timers pendentes (se houver)
        try {
          if (sessionData._qrConvertTimer) {
            clearTimeout(sessionData._qrConvertTimer);
            sessionData._qrConvertTimer = null;
          }
        } catch {}

        try {
          if (sessionData._reconnectTimer) {
            clearTimeout(sessionData._reconnectTimer);
            sessionData._reconnectTimer = null;
          }
        } catch {}

        // Gera (ou regenera) o token da sessão sempre que conecta
        sessionData.token = randomBytes(16).toString('hex');
        sessionData.name = sock.user?.name || '';
        sessionData.phoneNumber = (sock.user?.id || '').split(':')[0] || '';
        reconnectAttempts = 0;

        // Envia estado sanitizado com token para painel + webhook
        emit('session-update', sanitizeSession(sessionData));
      }

      if (connection === 'close') {
        const statusCode = lastDisconnect?.error?.output?.statusCode;
        const isLoggedOut = statusCode === DisconnectReason.loggedOut;

        sessionData.status = 'DISCONNECTED';
        sessionData.token = null;

        // Evita sockets pendurados em reconexões (e possíveis duplicidades)
        try {
          if (sessionData.socket?.end) {
            sessionData.socket.end(new Error('Reconnecting'));
          }
        } catch {}
        sessionData.socket = null;

        // Cancela conversões de QR pendentes
        try {
          if (sessionData._qrConvertTimer) {
            clearTimeout(sessionData._qrConvertTimer);
            sessionData._qrConvertTimer = null;
          }
        } catch {}

        emit('session-update', sanitizeSession(sessionData));

        if (isLoggedOut) {
          logger.error(`[ERROR] Sessão ${sessionId} desconectada permanentemente.`);
          await deleteSession(sessionId);
          return;
        }

        // Evita agendar múltiplas reconexões em cascata
        if (sessionData._reconnectTimer) {
          logger.warn(`[WARN] Reconexão já agendada para sessão ${sessionId}. Ignorando duplicidade.`);
          return;
        }

        let delay = 1500;

        if (sessionData.hasEverConnected) {
          reconnectAttempts += 1;
          delay = Math.min(1000 * Math.pow(2, reconnectAttempts), maxReconnectDelay);
        } else {
          // Sessões que ainda não conectaram (pareamento pendente) podem ter "close" espúrios.
          // Aqui mantemos um delay curto e estável para evitar loop agressivo.
          reconnectAttempts = 0;
          delay = 1500;
        }

        logger.info(`[INFO] Tentando reconectar sessão ${sessionId} em ${delay}ms`);

        sessionData._reconnectTimer = setTimeout(() => {
          sessionData._reconnectTimer = null;
          startSession(sessionId).catch((err) =>
            logger.error({ err }, `[ERROR] falha ao reiniciar sessão ${sessionId}`)
          );
        }, delay);
      }

      // Payload compatível com o painel (WebSocket)
      // e com o webhook do backend (evento connection.update)
      const payloadData = {
        ...update,
        status: connection || update?.status || null, // usado pelo backend
        qr: sessionData.qr || qr || null,             // texto do QR atual (se existir)
        qrCode: sessionData.qrCode || null,            // imagem (data URL) opcional do QR
        lastQrAt: sessionData.lastQrAt || null,        // timestamp (ms) do último QR recebido
        me: sock.user || update?.me || null,          // dados do usuário logado
        token: sessionData.token || null              // token atual da sessão
      };

      emit('connection.update', { sessionId, ...payloadData });
    } catch (err) {
      logger.error({ err }, `[ERROR] Erro em connection.update da sessão ${sessionId}`);
    }
  });

  // Lista de eventos a serem interceptados e retransmitidos
  const eventsToHandle = [
    'messaging-history.set',
    'chats.upsert',
    'chats.update',
    'chats.phoneNumberShare',
    'chats.delete',
    'presence.update',
    'contacts.upsert',
    'contacts.update',
    'messages.delete',
    'messages.update',
    'messages.media-update',
    'messages.upsert',
    'messages.reaction',
    'message-receipt.update',
    'groups.upsert',
    'groups.update',
    'group-participants.update',
    'group.join-request',
    'blocklist.set',
    'blocklist.update',
    'call',
    'labels.edit',
    'labels.association',
    'newsletter-participants.update',
    'newsletter-settings.update',
    'newsletter.reaction',
    'newsletter.view'
  ];

  for (const eventName of eventsToHandle) {
    sock.ev.on(eventName, (data) => {
      try {
        emit(eventName, { sessionId, data });
      } catch (err) {
        logger.error({ err }, `[ERROR] falha ao processar evento ${eventName} da sessão ${sessionId}`);
      }
    });
  }

  /**
   * Listener específico para expandir mensagens recebidas (upsert)
   * em eventos detalhados "message".
   */
  sock.ev.on('messages.upsert', (m) => {
    try {
      const msgs = m.messages || [];
      for (const msg of msgs) {
        if (msg.key && !msg.key.fromMe) {
          emit('message', {
            sessionId,
            key: msg.key,
            pushName: msg.pushName || '',
            message: msg.message,
            messageTimestamp: msg.messageTimestamp,
            status: msg.status,
            participant: msg.key.participant,
            messageCtorType: msg.messageCtorType,
            ...msg
          });
        }
      }
    } catch (err) {
      logger.error({ err }, `[ERROR] falha em messages.upsert para sessão ${sessionId}`);
    }
  });

  // Handler de presença para compatibilidade
  sock.ev.on('presence.update', (presence) => {
    try {
      emit('presence', {
        sessionId,
        id: presence?.id,
        presences: presence?.presences
      });
    } catch (err) {
      logger.error({ err }, `[ERROR] falha em presence.update para sessão ${sessionId}`);
    }
  });

  return sessionData;
}

/**
 * Inicia todas as sessões previamente salvas no diretório de auth.
 */
async function startAllSavedSessions() {
  try {
    const savedDirs = await fs.readdir(AUTH_DIR);
    if (!savedDirs || savedDirs.length === 0) {
      logger.info('[INFO] Nenhuma sessão salva encontrada para iniciar.');
      return;
    }
    for (const dir of savedDirs) {
      try {
        logger.info(`[INFO] Iniciando sessão salva: ${dir}`);
        await startSession(dir);
      } catch (err) {
        logger.warn({ err }, `[WARN] Falha ao iniciar sessão salva ${dir}`);
      }
    }
  } catch (err) {
    if (err.code === 'ENOENT') {
      logger.info('[INFO] Diretório de autenticação não encontrado. Nenhuma sessão para iniciar.');
    } else {
      logger.error({ err }, '[ERROR] Erro ao iniciar sessões salvas:');
    }
  }
}

/**
 * Encerra todas as conexões ativas para desligamento seguro do processo.
 */
async function shutdown() {
  logger.info('[INFO] shutdown iniciado: finalizando conexões ativas...');
  const ids = Array.from(sessions.keys());
  for (const id of ids) {
    try {
      const session = sessions.get(id);
      if (session?.socket?.end) {
        await session.socket.end(new Error('Servidor finalizado'));
      }
    } catch (err) {
      logger.warn({ err }, `[WARN] erro ao finalizar conexão da sessão ${id}`);
    }
  }
  logger.info('[INFO] shutdown finalizado.');
}

module.exports = {
  initialize,
  startSession,
  deleteSession,
  getSession,
  getAllSessions,
  startAllSavedSessions,
  shutdown
};
