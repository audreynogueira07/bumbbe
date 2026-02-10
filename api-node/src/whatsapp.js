// whatsapp.js
/*
 * whatsapp.js — hotfix de performance/estabilidade para QR (Baileys)
 *
 * Principais objetivos:
 * - QR aparecer rápido (emite texto imediatamente)
 * - geração de imagem do QR em paralelo (sem bloquear)
 * - reduzir ruído de webhook quando backend HTTP está fora do ar
 * - manter compatibilidade com WebSocket/painel existente
 */

const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  Browsers
} = require('@whiskeysockets/baileys');

const pino = require('pino');
const path = require('path');
const fs = require('fs-extra');
const qrcode = require('qrcode');
const { randomBytes } = require('crypto');
const axios = require('axios');

const { broadcast: fallbackBroadcast } = require('./websocket');

// sessionId -> session data
const sessions = new Map();

const logger = pino({
  transport: { target: 'pino-pretty' },
  level: process.env.LOG_LEVEL || 'info'
});

logger.info('[BOOT] whatsapp.js hotfix carregado (2026-02-09).');

const AUTH_DIR = path.join(__dirname, 'auth');
fs.ensureDirSync(AUTH_DIR);

// ============================================================================
// WEBHOOK HTTP (OPCIONAL)
// ============================================================================

const WEBHOOK_URLS_RAW =
  process.env.WEBHOOK_URLS ||
  process.env.PROJECT_WEBHOOK_URLS ||
  process.env.DJANGO_WEBHOOK_URL ||
  process.env.DJANGO_WEBHOOK ||
  '';

const WEBHOOK_URLS = WEBHOOK_URLS_RAW
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);

const WEBHOOK_API_KEYS_RAW =
  process.env.WEBHOOK_API_KEYS ||
  process.env.NODE_API_KEY ||
  process.env.DJANGO_WEBHOOK_API_KEY ||
  '';

const WEBHOOK_API_KEYS = WEBHOOK_API_KEYS_RAW
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);

const TRUE_VALUES = new Set(['1', 'true', 'yes', 'on']);

// IMPORTANTE: default = false para não travar em loop quando backend está fora.
const WEBHOOK_ENABLED = TRUE_VALUES.has(String(process.env.WEBHOOK_ENABLED || '').toLowerCase());

const WEBHOOK_TIMEOUT_MS = Number.parseInt(process.env.WEBHOOK_TIMEOUT_MS || '2000', 10);
const WEBHOOK_FAILS_BEFORE_COOLDOWN = Number.parseInt(process.env.WEBHOOK_FAILS_BEFORE_COOLDOWN || '3', 10);
const WEBHOOK_COOLDOWN_MS = Number.parseInt(process.env.WEBHOOK_COOLDOWN_MS || '300000', 10); // 5min
const WEBHOOK_LOG_THROTTLE_MS = Number.parseInt(process.env.WEBHOOK_LOG_THROTTLE_MS || '30000', 10);

// Para evitar sobrecarga por padrão no webhook: eventos essenciais
const WEBHOOK_EVENTS = (process.env.WEBHOOK_EVENTS || 'connection.update,session-update,qr,message')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);

const WEBHOOK_EVENTS_SET = new Set(WEBHOOK_EVENTS);

const webhookHealth = new Map();

function getWebhookApiKeyForIndex(i) {
  if (WEBHOOK_API_KEYS.length > 1 && WEBHOOK_API_KEYS[i]) return WEBHOOK_API_KEYS[i];
  return WEBHOOK_API_KEYS[0] || null;
}

function getWebhookState(url) {
  if (!webhookHealth.has(url)) {
    webhookHealth.set(url, {
      failures: 0,
      disabledUntil: 0,
      lastLogAt: 0
    });
  }
  return webhookHealth.get(url);
}

function isWebhookDisabled(url) {
  const st = getWebhookState(url);
  return Date.now() < st.disabledUntil;
}

function shouldSendEventToWebhook(eventType) {
  if (!WEBHOOK_EVENTS_SET.size) return true;
  return WEBHOOK_EVENTS_SET.has(eventType);
}

function maybeLogWebhookError(url, errMsg) {
  const st = getWebhookState(url);
  const now = Date.now();
  if (now - st.lastLogAt >= WEBHOOK_LOG_THROTTLE_MS) {
    st.lastLogAt = now;
    logger.error({ err: errMsg, url }, '[ERROR] falha ao enviar webhook HTTP para backend');
  }
}

function maybeLogWebhookWarn(url, msg) {
  const st = getWebhookState(url);
  const now = Date.now();
  if (now - st.lastLogAt >= WEBHOOK_LOG_THROTTLE_MS) {
    st.lastLogAt = now;
    logger.warn({ url }, msg);
  }
}

function markWebhookSuccess(url) {
  const st = getWebhookState(url);
  st.failures = 0;
  st.disabledUntil = 0;
}

function markWebhookFailure(url, err) {
  const st = getWebhookState(url);
  st.failures += 1;

  const code = err?.code || err?.errno || err?.name || 'UNKNOWN';
  const msg = err?.message || String(err);
  maybeLogWebhookError(url, `${code}: ${msg}`);

  if (st.failures >= WEBHOOK_FAILS_BEFORE_COOLDOWN) {
    st.disabledUntil = Date.now() + WEBHOOK_COOLDOWN_MS;
    st.failures = 0;
    maybeLogWebhookWarn(
      url,
      `[WARN] webhook temporariamente desativado por ${Math.round(WEBHOOK_COOLDOWN_MS / 1000)}s devido a falhas repetidas`
    );
  }
}

if (WEBHOOK_URLS.length && !WEBHOOK_ENABLED) {
  logger.warn('[WARN] WEBHOOK_URLS detectado(s), mas WEBHOOK_ENABLED=false. HTTP webhook desativado.');
} else if (WEBHOOK_URLS.length && WEBHOOK_ENABLED) {
  logger.info(`[INFO] Webhook HTTP ativo para ${WEBHOOK_URLS.length} destino(s).`);
} else {
  logger.info('[INFO] Webhook HTTP desativado (nenhuma URL configurada).');
}

// ============================================================================
// CONFIG QR
// ============================================================================

// svg: mais leve que png para data URL; none: só texto do qr
const QR_IMAGE_MODE = (process.env.QR_IMAGE_MODE || 'svg').toLowerCase(); // svg|png|none
const QR_ERROR_CORRECTION = (process.env.QR_ERROR_CORRECTION || 'L').toUpperCase();
const QR_MARGIN = Number.parseInt(process.env.QR_MARGIN || '1', 10);
const QR_SCALE = Number.parseInt(process.env.QR_SCALE || '4', 10);

let injectedBroadcast = null;

function initialize(broadcastFn) {
  if (typeof broadcastFn === 'function') {
    injectedBroadcast = broadcastFn;
    logger.info('[INFO] broadcast injetado no módulo whatsapp.');
  } else {
    logger.warn('[WARN] initialize recebeu parâmetro não-função.');
  }
}

function emit(type, data) {
  // 1) WebSocket (fluxo principal)
  try {
    const b = injectedBroadcast || fallbackBroadcast || (() => {});
    b(type, data);
  } catch (err) {
    logger.error({ err }, '[ERROR] erro ao emitir evento para painel (WebSocket)');
  }

  // 2) Webhook HTTP (opcional)
  try {
    if (!WEBHOOK_ENABLED || !WEBHOOK_URLS.length) return;
    if (!shouldSendEventToWebhook(type)) return;

    let sessionId = null;
    if (data && typeof data === 'object') {
      if (data.sessionId || data.session_id) {
        sessionId = data.sessionId || data.session_id;
      } else if (data.session && (data.session.sessionId || data.session.session_id)) {
        sessionId = data.session.sessionId || data.session.session_id;
      }
    }

    const payload = { type, data, sessionId };

    WEBHOOK_URLS.forEach((url, idx) => {
      if (isWebhookDisabled(url)) return;

      const headers = { 'Content-Type': 'application/json' };
      const apiKey = getWebhookApiKeyForIndex(idx);
      if (apiKey) headers['x-api-key'] = apiKey;

      axios
        .post(url, payload, { headers, timeout: WEBHOOK_TIMEOUT_MS })
        .then((resp) => {
          if (resp.status >= 200 && resp.status < 300) {
            markWebhookSuccess(url);
          } else {
            markWebhookFailure(url, {
              code: `HTTP_${resp.status}`,
              message: `status ${resp.status}`
            });
          }
        })
        .catch((err) => {
          markWebhookFailure(url, err);
        });
    });
  } catch (err) {
    logger.error({ err }, '[ERROR] erro inesperado na rotina de webhook HTTP');
  }
}

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

const getSession = (sessionId) => sessions.get(sessionId) || null;
const getAllSessions = () => Array.from(sessions.values());

async function deleteSession(sessionId) {
  const session = sessions.get(sessionId);

  if (session) {
    try {
      if (session._reconnectTimer) {
        clearTimeout(session._reconnectTimer);
        session._reconnectTimer = null;
      }
      if (session._qrConvertTimer) {
        clearTimeout(session._qrConvertTimer);
        session._qrConvertTimer = null;
      }
    } catch {}

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

function parseVersionFromEnv() {
  const raw = (process.env.WA_VERSION || '').trim();
  if (!raw) return null;

  const parts = raw
    .split(/[.,]/)
    .map((s) => Number.parseInt(String(s).trim(), 10))
    .filter((n) => Number.isFinite(n));

  if (parts.length >= 3) return [parts[0], parts[1], parts[2]];
  return null;
}

function getBrowserConfig() {
  // Pode customizar por env, mantendo padrão compatível
  const browserName = process.env.WA_BROWSER_NAME || 'Desktop';
  try {
    return Browsers.appropriate(browserName);
  } catch {
    // fallback seguro
    return Browsers.macOS('Desktop');
  }
}

async function startSession(sessionId) {
  const existing = sessions.get(sessionId);
  if (existing && existing.status !== 'DISCONNECTED') {
    logger.warn(`[WARN] Sessão ${sessionId} já está ativa ou pendente.`);
    emit('session-update', sanitizeSession(existing));
    return existing;
  }

  const authDir = path.join(AUTH_DIR, sessionId);
  await fs.ensureDir(authDir);

  // Atenção: useMultiFileAuthState é simples, mas pesado em I/O para alta escala
  const { state, saveCreds } = await useMultiFileAuthState(authDir);

  // Mantemos versão fixa estável por padrão; pode sobrescrever via WA_VERSION=2.3000.1029030078
  const waVersion = parseVersionFromEnv() || [2, 3000, 1029030078];
  logger.info(`[INFO] Usando versão hardcoded do WA: v${waVersion.join('.')}`);

  const sessionData = {
    sessionId,
    socket: null,
    status: 'PENDING',
    qr: null,
    qrCode: null,
    lastQrAt: null,
    hasEverConnected: false,
    token: null,
    name: '',
    phoneNumber: '',
    _reconnectTimer: null,
    _qrConvertTimer: null,
    _lastQrValue: null
  };

  sessions.set(sessionId, sessionData);
  emit('session-update', sanitizeSession(sessionData));

  const sock = makeWASocket({
    version: waVersion,
    logger: pino({ level: 'silent' }),
    printQRInTerminal: false,
    auth: state,
    browser: getBrowserConfig(),
    syncFullHistory: false,
    markOnlineOnConnect: false,
    keepAliveIntervalMs: 30000,
    connectTimeoutMs: Number.parseInt(process.env.WA_CONNECT_TIMEOUT_MS || '20000', 10),
    getMessage: async () => ({ conversation: 'message-not-available' })
  });

  sessionData.socket = sock;

  sock.ev.on('creds.update', async () => {
    try {
      await saveCreds();
    } catch (err) {
      logger.warn({ err }, `[WARN] saveCreds falhou na sessão ${sessionId}`);
    }
  });

  let reconnectAttempts = 0;
  const maxReconnectDelay = 60 * 1000;

  sock.ev.on('connection.update', async (update) => {
    try {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        // Evita trabalho redundante para mesmo QR repetido
        const isSameQr = sessionData._lastQrValue === qr;
        sessionData.qr = qr;
        sessionData.lastQrAt = Date.now();
        sessionData._lastQrValue = qr;

        // 1) emissão imediata (texto) para latência mínima
        // compatibilidade: enviamos qr, src e qrCode
        emit('qr', {
          sessionId,
          qr: sessionData.qr,
          src: sessionData.qrCode || null,
          qrCode: sessionData.qrCode || null,
          lastQrAt: sessionData.lastQrAt
        });

        // 2) geração opcional da imagem em paralelo
        if (QR_IMAGE_MODE !== 'none' && !isSameQr) {
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
                    margin: Number.isFinite(QR_MARGIN) ? QR_MARGIN : 1,
                    scale: Number.isFinite(QR_SCALE) ? QR_SCALE : 4
                  });
                } else {
                  const svg = await qrcode.toString(currentQr, {
                    type: 'svg',
                    errorCorrectionLevel: QR_ERROR_CORRECTION,
                    margin: Number.isFinite(QR_MARGIN) ? QR_MARGIN : 1
                  });
                  dataUrl = 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
                }

                if (sessionData.qr === currentQr) {
                  sessionData.qrCode = dataUrl;

                  emit('qr', {
                    sessionId,
                    qr: sessionData.qr,
                    src: sessionData.qrCode,
                    qrCode: sessionData.qrCode,
                    lastQrAt: sessionData.lastQrAt
                  });

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

        sessionData.qr = null;
        sessionData.qrCode = null;
        sessionData.lastQrAt = null;
        sessionData._lastQrValue = null;

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

        sessionData.token = randomBytes(16).toString('hex');
        sessionData.name = sock.user?.name || '';
        sessionData.phoneNumber = (sock.user?.id || '').split(':')[0] || '';

        reconnectAttempts = 0;
        emit('session-update', sanitizeSession(sessionData));
      }

      if (connection === 'close') {
        const statusCode = lastDisconnect?.error?.output?.statusCode;
        const isLoggedOut = statusCode === DisconnectReason.loggedOut;
        const isRestartRequired = statusCode === DisconnectReason.restartRequired;

        sessionData.status = 'DISCONNECTED';
        sessionData.token = null;

        try {
          if (sessionData.socket?.end) {
            sessionData.socket.end(new Error('Reconnecting'));
          }
        } catch {}
        sessionData.socket = null;

        try {
          if (sessionData._qrConvertTimer) {
            clearTimeout(sessionData._qrConvertTimer);
            sessionData._qrConvertTimer = null;
          }
        } catch {}

        emit('session-update', sanitizeSession(sessionData));

        if (isLoggedOut) {
          logger.error(`[ERROR] Sessão ${sessionId} desconectada permanentemente (loggedOut).`);
          await deleteSession(sessionId);
          return;
        }

        if (sessionData._reconnectTimer) {
          logger.warn(`[WARN] Reconexão já agendada para sessão ${sessionId}. Ignorando duplicidade.`);
          return;
        }

        let delay;

        if (isRestartRequired) {
          delay = 500;
          reconnectAttempts = 0;
        } else if (sessionData.hasEverConnected) {
          reconnectAttempts += 1;
          delay = Math.min(1000 * Math.pow(2, reconnectAttempts), maxReconnectDelay);
        } else {
          reconnectAttempts = 0;
          delay = 1500;
        }

        logger.info(`[INFO] Tentando reconectar sessão ${sessionId} em ${delay}ms`);

        sessionData._reconnectTimer = setTimeout(() => {
          sessionData._reconnectTimer = null;
          startSession(sessionId).catch((err) => {
            logger.error({ err }, `[ERROR] falha ao reiniciar sessão ${sessionId}`);
          });
        }, delay);
      }

      const payloadData = {
        ...update,
        status: connection || update?.status || null,
        qr: sessionData.qr || qr || null,
        qrCode: sessionData.qrCode || null,
        lastQrAt: sessionData.lastQrAt || null,
        me: sock.user || update?.me || null,
        token: sessionData.token || null
      };

      emit('connection.update', { sessionId, ...payloadData });
    } catch (err) {
      logger.error({ err }, `[ERROR] Erro em connection.update da sessão ${sessionId}`);
    }
  });

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

async function shutdown() {
  logger.info('[INFO] shutdown iniciado: finalizando conexões ativas...');
  const ids = Array.from(sessions.keys());

  for (const id of ids) {
    try {
      const session = sessions.get(id);

      if (session?._reconnectTimer) {
        clearTimeout(session._reconnectTimer);
        session._reconnectTimer = null;
      }

      if (session?._qrConvertTimer) {
        clearTimeout(session._qrConvertTimer);
        session._qrConvertTimer = null;
      }

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
