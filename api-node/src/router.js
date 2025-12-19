// router.js — Rotas API (Express) - CORRIGIDO PARA EXPOR TOKEN AO DJANGO

const express = require('express');
const multer = require('multer');
const path = require('path');
const fs = require('fs-extra');
const { 
    startSession, 
    deleteSession, 
    getSession, 
    getAllSessions,
} = require('./whatsapp');

const router = express.Router();
const upload = multer({ dest: path.join(__dirname, '..', 'tmp') });

// ==============================================================================
// 1. MIDDLEWARES DE SEGURANÇA
// ==============================================================================

const apiKeyAuth = (req, res, next) => {
  const apiKey = req.headers['x-api-key'] || req.query.apiKey;
  if (!process.env.API_KEY || !apiKey || apiKey !== process.env.API_KEY) {
    return res.status(401).json({ error: 'ACESSO NEGADO: Chave de API Mestra inválida.' });
  }
  next();
};

const sessionTokenAuth = (req, res, next) => {
    const requestedSessionId = req.params.sessionId;
    const session = getSession(requestedSessionId);
    
    if (!session || session.status !== 'CONNECTED') {
        return res.status(404).json({ error: 'Sessão não encontrada ou não conectada.' });
    }

    if (!session.token) {
        return res.status(403).json({ error: 'Sessão conectada, mas token de segurança ainda não gerado.'});
    }

    const authHeader = req.headers['authorization'];
    const clientToken = authHeader && authHeader.split(' ')[1];

    if (!clientToken || clientToken !== session.token) {
        return res.status(403).json({ error: 'ACESSO NEGADO: Token inválido para esta sessão.' });
    }

    req.session = session;
    next();
};

// ==============================================================================
// 2. ROTAS PÚBLICAS / UTILITÁRIAS
// ==============================================================================

router.get('/:sessionId/check-connection', (req, res) => {
    const session = getSession(req.params.sessionId);
    if (!session) {
        return res.status(404).json({ status: 'NOT_FOUND', error: 'Sessão não existe' });
    }
    
    // --- ALTERAÇÃO IMPORTANTE: ---
    // Retornamos o token se ele existir, para facilitar debugging e sync rápido se necessário.
    // Cuidado: Em produção, proteja esta rota se possível, ou dependa apenas da rota /sessions (Admin).
    res.json({ 
        sessionId: session.sessionId,
        status: session.status,
        hasToken: !!session.token,
        token: session.token || null // Adicionado para garantir visibilidade
    });
});

// ==============================================================================
// 3. ROTAS ADMINISTRATIVAS (USADAS PELO DJANGO PARA SYNC)
// ==============================================================================

router.get('/auth/check', apiKeyAuth, (req, res) => {
    res.status(200).json({ status: 'authenticated', message: 'Login bem sucedido.' });
});

router.post('/sessions/start', apiKeyAuth, async (req, res) => {
  try {
    const { sessionId } = req.body;
    if (!sessionId) return res.status(400).json({ error: 'O campo "sessionId" é obrigatório.' });
    
    if (sessionId === 'sessions' || sessionId === 'admin' || sessionId.includes('/')) {
        return res.status(400).json({ error: 'Nome de sessão inválido.' });
    }

    const session = await startSession(sessionId); 
    
    // Retorna o token se a sessão já estiver recuperada/ativa
    res.status(201).json({ 
        message: 'Sessão iniciada.', 
        sessionId: session.sessionId, 
        status: session.status,
        token: session.token || null 
    });
  } catch (err) {
    console.error(`Erro em /sessions/start:`, err);
    res.status(500).json({ error: 'Falha ao criar sessão.' });
  }
});

router.delete('/sessions/:sessionId', apiKeyAuth, async (req, res) => {
  await deleteSession(req.params.sessionId);
  res.status(200).json({ message: 'Sessão removida.' });
});

// --- AQUI ESTAVA O PROBLEMA ---
router.get('/sessions', apiKeyAuth, (req, res) => {
    // Agora incluímos explicitamente o TOKEN na lista
    const allSessions = getAllSessions().map(s => ({
        sessionId: s.sessionId,
        status: s.status,
        name: s.name,
        phoneNumber: s.phoneNumber,
        // QR em texto (rápido) e QR em imagem (data URL) opcional
        qr: s.qr || null,
        qrCode: s.qrCode || null,
        lastQrAt: s.lastQrAt || null,
        hasEverConnected: !!s.hasEverConnected,
        token: s.token // <--- OBRIGATÓRIO PARA O DJANGO CONSEGUIR LER
    }));
    res.status(200).json(allSessions);
});

// -----------------------------------------------------------------------------
// QR rápido (ADMIN): permite ao Django/painel puxar o QR sem depender do webhook.
// Útil para eliminar o "não repassou" e para reduzir latência percebida.
// -----------------------------------------------------------------------------
router.get('/sessions/:sessionId/qr', apiKeyAuth, (req, res) => {
    const session = getSession(req.params.sessionId);
    if (!session) {
        return res.status(404).json({ error: 'Sessão não encontrada.' });
    }

    res.status(200).json({
        sessionId: session.sessionId,
        status: session.status,
        qr: session.qr || null,         // texto do QR (o mais importante)
        qrCode: session.qrCode || null, // imagem opcional (data URL)
        lastQrAt: session.lastQrAt || null,
        hasEverConnected: !!session.hasEverConnected
    });
});

router.post('/sessions/:sessionId/pairing-code', apiKeyAuth, async (req, res) => {
    try {
        const { phoneNumber } = req.body;
        if (!phoneNumber) return res.status(400).json({ error: 'Campo "phoneNumber" é obrigatório.' });
        const session = getSession(req.params.sessionId);
        
        if (!session) return res.status(404).json({ error: 'Sessão não encontrada.' });
        
        if (session.status !== 'DISCONNECTED' && session.status !== 'PENDING') {
             return res.status(400).json({ error: 'Sessão precisa estar pendente para parear.' });
        }
        
        const sock = session.socket;
        if (!sock?.requestPairingCode) return res.status(400).json({ error: 'Função de pareamento indisponível.' });
        
        const code = await sock.requestPairingCode(phoneNumber);
        res.json({ sessionId: req.params.sessionId, pairingCode: code });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao solicitar código.' });
    }
});

// ==============================================================================
// 4. ROTAS DO USUÁRIO (MANTIDAS IGUAIS)
// ==============================================================================

router.get('/:sessionId/status', sessionTokenAuth, (req, res) => {
    const s = req.session;
    res.json({
        sessionId: s.sessionId,
        status: s.status,
        name: s.name,
        phoneNumber: s.phoneNumber,
        platform: s.socket?.user?.platform || 'unknown'
    });
});

router.post('/:sessionId/messages/send', sessionTokenAuth, async (req, res) => {
    try {
      const { to, message, options } = req.body;
      if (!to || !message) return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
      
      const result = await req.session.socket.sendMessage(to, { text: message }, options || {});
      res.json({ status: 'sent', to, result });
    } catch (err) {
      console.error(err);
      res.status(500).json({ error: 'Falha ao enviar mensagem' });
    }
});

router.post('/:sessionId/messages/send-quote', sessionTokenAuth, async (req, res) => {
    try {
        const { to, message, quoted, options } = req.body;
        if (!to || !message || !quoted) return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
        const result = await req.session.socket.sendMessage(to, { text: message }, { quoted, ...(options || {}) });
        res.json({ status: 'sent', to, result });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao enviar mensagem citada.' });
    }
});

router.post('/:sessionId/messages/send-mention', sessionTokenAuth, async (req, res) => {
    try {
        const { to, message, mentions, options } = req.body;
        if (!to || !message || !Array.isArray(mentions)) return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
        const result = await req.session.socket.sendMessage(to, { text: message, mentions }, options || {});
        res.json({ status: 'sent', to, result });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao enviar menção.' });
    }
});

router.post('/:sessionId/messages/forward', sessionTokenAuth, async (req, res) => {
    try {
        const { to, message, options } = req.body;
        if (!to || !message) return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
        const result = await req.session.socket.sendMessage(to, { forward: message }, options || {});
        res.json({ status: 'sent', to, result });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao encaminhar.' });
    }
});

router.post('/:sessionId/messages/location', sessionTokenAuth, async (req, res) => {
    try {
        const { to, latitude, longitude, name, address } = req.body;
        if (!to || latitude === undefined || longitude === undefined) return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
        const loc = { degreesLatitude: parseFloat(latitude), degreesLongitude: parseFloat(longitude) };
        if (name) loc.name = name;
        if (address) loc.address = address;
        const result = await req.session.socket.sendMessage(to, { location: loc });
        res.json({ status: 'sent', to, result });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao enviar localização.' });
    }
});

router.post('/:sessionId/messages/contact', sessionTokenAuth, async (req, res) => {
    try {
        const { to, displayName, vcard } = req.body;
        if (!to || !displayName || !vcard) return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
        const contact = { displayName, contacts: [{ vcard }] };
        const result = await req.session.socket.sendMessage(to, { contact });
        res.json({ status: 'sent', to, result });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao enviar contato.' });
    }
});

router.post('/:sessionId/messages/reaction', sessionTokenAuth, async (req, res) => {
    try {
        const { to, key, emoji } = req.body;
        if (!to || !key || !emoji) return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
        const result = await req.session.socket.sendMessage(to, { react: { text: emoji, key } });
        res.json({ status: 'sent', to, result });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao enviar reação.' });
    }
});

router.post('/:sessionId/messages/poll', sessionTokenAuth, async (req, res) => {
    try {
        // Suporta tanto "options" (legado) quanto "values" (moderno) para as opções
        const { to, name, options, values, selectableCount } = req.body;
        const opts = Array.isArray(values) && values.length ? values : options;
        if (!to || !name || !Array.isArray(opts)) return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
        const poll = {
            name,
            options: opts,
            selectableCount: selectableCount ? parseInt(selectableCount, 10) : 1
        };
        const result = await req.session.socket.sendMessage(to, { poll });
        res.json({ status: 'sent', to, result });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao enviar enquete.' });
    }
});

router.post('/:sessionId/messages/buttons', sessionTokenAuth, async (req, res) => {
    try {
        const { to, message, footer, buttons } = req.body;
        if (!to || !message || !Array.isArray(buttons)) return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
        for (const btn of buttons) {
            if (!btn.id || !btn.text) return res.status(400).json({ error: 'Botões inválidos.' });
        }
        const buttonMessage = {
            text: message,
            footer: footer || '',
            buttons: buttons.map((btn) => ({
                buttonId: btn.id,
                buttonText: { displayText: btn.text },
                type: 1
            })),
            headerType: 1
        };
        const result = await req.session.socket.sendMessage(to, buttonMessage);
        res.json({ status: 'sent', to, result });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao enviar botões.' });
    }
});

router.post('/:sessionId/messages/send-gif', sessionTokenAuth, upload.single('file'), async (req, res) => {
    try {
        const { to, caption } = req.body;
        if (!to || !req.file) {
            if (req.file) await fs.unlink(req.file.path);
            return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
        }
        const filePath = req.file.path;
        const result = await req.session.socket.sendMessage(to, { video: { url: filePath }, caption, gifPlayback: true });
        await fs.unlink(filePath);
        res.json({ status: 'sent', to, result });
    } catch (err) {
        console.error(err);
        if (req.file) try { await fs.unlink(req.file.path); } catch {}
        res.status(500).json({ error: 'Falha ao enviar GIF.' });
    }
});

router.post('/:sessionId/messages/view-once', sessionTokenAuth, upload.single('file'), async (req, res) => {
    try {
        const { to, caption } = req.body;
        if (!to || !req.file) {
            if (req.file) await fs.unlink(req.file.path);
            return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
        }
        const filePath = req.file.path;
        const mimeType = req.file.mimetype;
        let content = {};
        if (mimeType.startsWith('image/')) content.image = { url: filePath };
        else if (mimeType.startsWith('video/')) content.video = { url: filePath };
        else {
            await fs.unlink(filePath);
            return res.status(400).json({ error: 'Tipo de arquivo inválido para View Once.' });
        }
        content.caption = caption;
        content.viewOnce = true;
        const result = await req.session.socket.sendMessage(to, content);
        await fs.unlink(filePath);
        res.json({ status: 'sent', to, result });
    } catch (err) {
        console.error(err);
        if (req.file) try { await fs.unlink(req.file.path); } catch {}
        res.status(500).json({ error: 'Falha ao enviar View Once.' });
    }
});

router.post('/:sessionId/messages/send-media', sessionTokenAuth, upload.single('file'), async (req, res) => {
    try {
        const { to, caption } = req.body;
        if (!to || !req.file) {
            if (req.file) await fs.unlink(req.file.path);
            return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
        }
        const filePath = req.file.path;
        const mimeType = req.file.mimetype;
        const messageOptions = { caption };
        
        if (mimeType.startsWith('image/')) { messageOptions.image = { url: filePath }; }
        else if (mimeType.startsWith('video/')) { messageOptions.video = { url: filePath }; }
        else if (mimeType.startsWith('audio/')) { messageOptions.audio = { url: filePath }; messageOptions.ptt = false; }
        else { messageOptions.document = { url: filePath }; messageOptions.mimetype = mimeType; messageOptions.fileName = req.file.originalname; }

        const result = await req.session.socket.sendMessage(to, messageOptions);
        await fs.unlink(filePath);
        res.json({ status: 'sent', to, result });
    } catch (err) {
        console.error(err);
        if (req.file) try { await fs.unlink(req.file.path); } catch {}
        res.status(500).json({ error: 'Falha ao enviar mídia.' });
    }
});

router.post('/:sessionId/messages/send-voice', sessionTokenAuth, upload.single('file'), async (req, res) => {
    try {
        const { to } = req.body;
        if (!to || !req.file) {
            if (req.file) await fs.unlink(req.file.path);
            return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
        }
        const filePath = req.file.path;
        const result = await req.session.socket.sendMessage(to, { audio: { url: filePath }, ptt: true });
        await fs.unlink(filePath);
        res.json({ status: 'sent', to, result });
    } catch (err) {
        console.error(err);
        if (req.file) try { await fs.unlink(req.file.path); } catch {}
        res.status(500).json({ error: 'Falha ao enviar voz.' });
    }
});

router.post('/:sessionId/messages/read', sessionTokenAuth, async (req, res) => {
    try {
        const { keys } = req.body;
        if (!keys || !Array.isArray(keys)) return res.status(400).json({ error: 'Campo "keys" obrigatório.' });
        await req.session.socket.readMessages(keys);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao marcar como lido.' });
    }
});

router.post('/:sessionId/chat/:jid/history', sessionTokenAuth, async (req, res) => {
    try {
        const { count, key, timestamp } = req.body;
        if (!count || !key || !timestamp) return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
        const result = await req.session.socket.fetchMessageHistory(parseInt(count, 10), key, timestamp);
        res.json(result);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao obter histórico.' });
    }
});

router.post('/:sessionId/users/presence-subscribe', sessionTokenAuth, async (req, res) => {
    try {
        const { jid } = req.body;
        if (!jid) return res.status(400).json({ error: 'Campo "jid" obrigatório.' });
        await req.session.socket.presenceSubscribe(jid);
        res.json({ status: 'subscribed', jid });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao inscrever presença.' });
    }
});

router.post('/:sessionId/messages/broadcast', sessionTokenAuth, async (req, res) => {
    try {
        const { message, recipients } = req.body;
        if (!message || !Array.isArray(recipients)) return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
        const result = await req.session.socket.sendMessage('status@broadcast', { text: message }, { broadcast: true, statusJidList: recipients });
        res.json({ status: 'sent', result });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao enviar broadcast.' });
    }
});

router.get('/:sessionId/broadcast/:broadcastId', sessionTokenAuth, async (req, res) => {
    try {
        const info = await req.session.socket.getBroadcastListInfo(req.params.broadcastId);
        res.json(info);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao obter info broadcast.' });
    }
});

router.get('/:sessionId/users/:jid/exists', sessionTokenAuth, async (req, res) => {
    try {
      const [result] = await req.session.socket.onWhatsApp(req.params.jid);
      res.json({ exists: !!result?.exists, jid: result?.jid || req.params.jid });
    } catch (err) {
      console.error(err);
      res.status(500).json({ error: 'Falha ao verificar usuário.' });
    }
});
  
router.get('/:sessionId/users/:jid/avatar', sessionTokenAuth, async (req, res) => {
    try {
      const url = await req.session.socket.profilePictureUrl(req.params.jid, 'image');
      res.json({ avatarUrl: url });
    } catch (err) {
      console.error(err);
      res.status(404).json({ error: 'Avatar não encontrado.' });
    }
});
  
router.post('/:sessionId/users/presence', sessionTokenAuth, async (req, res) => {
    try {
      const { to, presence } = req.body;
      if (!to || !presence) return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
      await req.session.socket.sendPresenceUpdate(presence, to);
      res.json({ status: 'presence updated', to, presence });
    } catch (err) {
      console.error(err);
      res.status(500).json({ error: 'Falha ao atualizar presença.' });
    }
});

router.get('/:sessionId/users/:jid/status', sessionTokenAuth, async (req, res) => {
    try {
        const status = await req.session.socket.fetchStatus(req.params.jid);
        res.json(status);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao obter status.' });
    }
});

router.get('/:sessionId/users/:jid/business-profile', sessionTokenAuth, async (req, res) => {
    try {
        const profile = await req.session.socket.getBusinessProfile(req.params.jid);
        res.json(profile);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao obter perfil business.' });
    }
});

router.put('/:sessionId/profile/name', sessionTokenAuth, async (req, res) => {
    try {
        const { name } = req.body;
        if (!name) return res.status(400).json({ error: 'Campo "name" obrigatório.' });
        await req.session.socket.updateProfileName(name);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao atualizar nome.' });
    }
});

router.put('/:sessionId/profile/status', sessionTokenAuth, async (req, res) => {
    try {
        const { status } = req.body;
        if (!status) return res.status(400).json({ error: 'Campo "status" obrigatório.' });
        await req.session.socket.updateProfileStatus(status);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao atualizar status.' });
    }
});

router.put('/:sessionId/profile/picture', sessionTokenAuth, upload.single('file'), async (req, res) => {
    try {
        if (!req.file) return res.status(400).json({ error: 'Campo "file" obrigatório.' });
        const filePath = req.file.path;
        const jid = req.session.socket.user?.id;
        if (!jid) {
            await fs.unlink(filePath);
            return res.status(500).json({ error: 'Usuário não identificado.' });
        }
        await req.session.socket.updateProfilePicture(jid, { url: filePath });
        await fs.remove(filePath);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        if (req.file) try { await fs.unlink(req.file.path); } catch {}
        res.status(500).json({ error: 'Falha ao atualizar foto.' });
    }
});

router.delete('/:sessionId/profile/picture', sessionTokenAuth, async (req, res) => {
    try {
        const jid = req.session.socket.user?.id;
        if (!jid) return res.status(500).json({ error: 'Usuário não identificado.' });
        await req.session.socket.removeProfilePicture(jid);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao remover foto.' });
    }
});

router.post('/:sessionId/users/:jid/block', sessionTokenAuth, async (req, res) => {
    try {
        const { action } = req.body;
        if (!action) return res.status(400).json({ error: 'Campo "action" obrigatório.' });
        await req.session.socket.updateBlockStatus(req.params.jid, action);
        res.json({ status: 'success', action });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao bloquear/desbloquear.' });
    }
});

router.get('/:sessionId/users/blocklist', sessionTokenAuth, async (req, res) => {
    try {
        const list = await req.session.socket.fetchBlocklist();
        res.json(list);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao obter blocklist.' });
    }
});

router.get('/:sessionId/groups', sessionTokenAuth, async (req, res) => {
    try {
        const groups = await req.session.socket.groupFetchAllParticipating();
        res.json(groups);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao obter grupos.' });
    }
});

router.post('/:sessionId/groups/create', sessionTokenAuth, async (req, res) => {
    try {
      const { subject, participants } = req.body;
      if (!subject || !participants?.length) return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
      const group = await req.session.socket.groupCreate(subject, participants);
      res.status(201).json(group);
    } catch (err) {
      console.error(err);
      res.status(500).json({ error: 'Falha ao criar grupo.' });
    }
});

router.get('/:sessionId/groups/:groupId/metadata', sessionTokenAuth, async (req, res) => {
    try {
      const metadata = await req.session.socket.groupMetadata(req.params.groupId);
      res.json(metadata);
    } catch (err) {
      console.error(err);
      res.status(500).json({ error: 'Falha ao obter metadados.' });
    }
});

router.post('/:sessionId/groups/:groupId/participants', sessionTokenAuth, async (req, res) => {
    try {
        const { action, participants } = req.body;
        if (!action || !participants?.length) return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
        const result = await req.session.socket.groupParticipantsUpdate(req.params.groupId, participants, action);
        res.json(result);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao atualizar participantes.' });
    }
});

router.put('/:sessionId/groups/:groupId/subject', sessionTokenAuth, async (req, res) => {
    try {
      const { subject } = req.body;
      if (!subject) return res.status(400).json({ error: 'Campo "subject" obrigatório.' });
      await req.session.socket.groupUpdateSubject(req.params.groupId, subject);
      res.json({ status: 'success' });
    } catch (err) {
      console.error(err);
      res.status(500).json({ error: 'Falha ao atualizar assunto.' });
    }
});

router.post('/:sessionId/groups/:groupId/leave', sessionTokenAuth, async (req, res) => {
    try {
      await req.session.socket.groupLeave(req.params.groupId);
      res.json({ status: 'success' });
    } catch (err) {
      console.error(err);
      res.status(500).json({ error: 'Falha ao sair do grupo.' });
    }
});

router.get('/:sessionId/groups/:groupId/invite-code', sessionTokenAuth, async (req, res) => {
    try {
        const code = await req.session.socket.groupInviteCode(req.params.groupId);
        res.json({ inviteCode: code });
    } catch(err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao obter código de convite.' });
    }
});

router.put('/:sessionId/groups/:groupId/description', sessionTokenAuth, async (req, res) => {
    try {
        const { description } = req.body;
        if (!description) return res.status(400).json({ error: 'Campo "description" obrigatório.' });
        await req.session.socket.groupUpdateDescription(req.params.groupId, description);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao atualizar descrição.' });
    }
});

router.put('/:sessionId/groups/:groupId/settings', sessionTokenAuth, async (req, res) => {
    try {
        const { setting } = req.body;
        if (!setting) return res.status(400).json({ error: 'Campo "setting" obrigatório.' });
        await req.session.socket.groupSettingUpdate(req.params.groupId, setting);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao atualizar configuração.' });
    }
});

router.post('/:sessionId/groups/:groupId/revoke-invite', sessionTokenAuth, async (req, res) => {
    try {
        const code = await req.session.socket.groupRevokeInvite(req.params.groupId);
        res.json({ newInviteCode: code });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao revogar convite.' });
    }
});

router.post('/:sessionId/groups/join', sessionTokenAuth, async (req, res) => {
    try {
        const { code } = req.body;
        if (!code) return res.status(400).json({ error: 'Campo "code" obrigatório.' });
        const response = await req.session.socket.groupAcceptInvite(code);
        res.json({ status: 'joined', response });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao entrar no grupo.' });
    }
});

router.get('/:sessionId/groups/invite-info/:code', sessionTokenAuth, async (req, res) => {
    try {
        const info = await req.session.socket.groupGetInviteInfo(req.params.code);
        res.json(info);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao obter info convite.' });
    }
});

router.get('/:sessionId/groups/:groupId/requests', sessionTokenAuth, async (req, res) => {
    try {
        const list = await req.session.socket.groupRequestParticipantsList(req.params.groupId);
        res.json(list);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao obter requests.' });
    }
});

router.post('/:sessionId/groups/:groupId/requests', sessionTokenAuth, async (req, res) => {
    try {
        const { action, participants } = req.body;
        if (!action || !Array.isArray(participants)) return res.status(400).json({ error: 'Campos obrigatórios ausentes.' });
        const result = await req.session.socket.groupRequestParticipantsUpdate(req.params.groupId, participants, action);
        res.json(result);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao atualizar requests.' });
    }
});

router.post('/:sessionId/groups/:groupId/ephemeral', sessionTokenAuth, async (req, res) => {
    try {
        const { seconds } = req.body;
        if (seconds === undefined) return res.status(400).json({ error: 'Campo "seconds" obrigatório.' });
        await req.session.socket.groupToggleEphemeral(req.params.groupId, parseInt(seconds, 10));
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao mudar ephemeral.' });
    }
});

router.post('/:sessionId/groups/:groupId/member-add-mode', sessionTokenAuth, async (req, res) => {
    try {
        const { mode } = req.body;
        if (!mode) return res.status(400).json({ error: 'Campo "mode" obrigatório.' });
        await req.session.socket.groupMemberAddMode(req.params.groupId, mode);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao atualizar member-add-mode.' });
    }
});

router.put('/:sessionId/groups/:groupId/picture', sessionTokenAuth, upload.single('file'), async (req, res) => {
    try {
        if (!req.file) return res.status(400).json({ error: 'Campo "file" obrigatório.' });
        const filePath = req.file.path;
        await req.session.socket.updateProfilePicture(req.params.groupId, { url: filePath });
        await fs.remove(filePath);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        if (req.file) try { await fs.unlink(req.file.path); } catch {}
        res.status(500).json({ error: 'Falha ao atualizar foto grupo.' });
    }
});

router.delete('/:sessionId/groups/:groupId/picture', sessionTokenAuth, async (req, res) => {
    try {
        await req.session.socket.removeProfilePicture(req.params.groupId);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao remover foto grupo.' });
    }
});

router.post('/:sessionId/chat/:jid/modify', sessionTokenAuth, async (req, res) => {
    try {
        const update = req.body;
        if (!update || typeof update !== 'object') return res.status(400).json({ error: 'Corpo inválido.' });
        await req.session.socket.chatModify(update, req.params.jid);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao modificar chat.' });
    }
});

router.post('/:sessionId/messages/delete', sessionTokenAuth, async (req, res) => {
    try {
        const { to, key } = req.body;
        if (!to || !key) return res.status(400).json({ error: 'Campos "to" e "key" obrigatórios.' });
        const result = await req.session.socket.sendMessage(to, { delete: key });
        res.json({ status: 'success', result });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao excluir mensagem.' });
    }
});

// ==============================================================================
// ROTAS DE MANIPULAÇÃO DE MENSAGENS (NOVAS)
// Estas rotas foram adicionadas para suportar recursos modernos da API Baileys
// como edição de mensagens, fixação de chats e favoritar mensagens. Elas
// complementam a rota genérica chatModify existente e permitem que o cliente
// continue utilizando endpoints específicos.
// ============================================================================

// Editar uma mensagem existente. Requer o jid do chat em "to", o novo
// conteúdo da mensagem em "text" e a chave original em "key". O
// parâmetro "key" deve conter pelo menos { id, fromMe } e, opcionalmente,
// remoteJid. Internamente, a função sendMessage é invocada com o
// campo "edit" contendo a chave original conforme documentação
// atual da biblioteca【875783813627243†L1104-L1113】.
router.post('/:sessionId/messages/edit', sessionTokenAuth, async (req, res) => {
    try {
        const { to, text, key } = req.body;
        if (!to || !text || !key) {
            return res.status(400).json({ error: 'Campos "to", "text" e "key" são obrigatórios.' });
        }
        // Envia mensagem com o campo "edit" especificando a mensagem a ser editada
        const result = await req.session.socket.sendMessage(to, { text, edit: key });
        res.json({ status: 'edited', to, result });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao editar mensagem.' });
    }
});

// Favoritar (estrelar) ou desfavoritar uma mensagem. O corpo deve conter
// "to" (chat jid), "key" com { id, fromMe }, e o campo booleano
// "star" indicando se deve marcar (true) ou desmarcar (false) a estrela. A
// implementação utiliza chatModify com a opção star, conforme
// documentação oficial【875783813627243†L1275-L1294】.
router.post('/:sessionId/messages/star', sessionTokenAuth, async (req, res) => {
    try {
        const { to, key, star } = req.body;
        if (!to || !key || typeof star === 'undefined') {
            return res.status(400).json({ error: 'Campos "to", "key" e "star" são obrigatórios.' });
        }
        const messageObj = { id: key.id, fromMe: !!key.fromMe };
        // star: { messages: [ ... ], star: boolean }
        const mod = { star: { messages: [ messageObj ], star: !!star } };
        await req.session.socket.chatModify(mod, to);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao (des)favoritar mensagem.' });
    }
});

// Fixar um chat no topo (pin). Recebe "to" (jid do chat). Opcionalmente, um
// tempo de pin pode ser fornecido, porém a API Baileys atualmente só aceita
// booleano. Este endpoint ignora qualquer "key" recebido e simplesmente
// utiliza chatModify com { pin: true }【875783813627243†L1275-L1281】.
router.post('/:sessionId/messages/pin', sessionTokenAuth, async (req, res) => {
    try {
        const { to } = req.body;
        if (!to) return res.status(400).json({ error: 'Campo "to" obrigatório.' });
        await req.session.socket.chatModify({ pin: true }, to);
        res.json({ status: 'pinned' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao fixar chat.' });
    }
});

// Desfixar (unpin) um chat. Utiliza chatModify com { pin: false }【875783813627243†L1275-L1281】.
router.post('/:sessionId/messages/unpin', sessionTokenAuth, async (req, res) => {
    try {
        const { to } = req.body;
        if (!to) return res.status(400).json({ error: 'Campo "to" obrigatório.' });
        await req.session.socket.chatModify({ pin: false }, to);
        res.json({ status: 'unpinned' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao desfixar chat.' });
    }
});

// ============================================================================
// ROTAS DE CHATS (ARQUIVAR, MUTE, LIMPAR, MARCAR COMO LIDO)
// Estas rotas utilizam chatModify para realizar ações sobre um chat. A
// nomenclatura mantém retrocompatibilidade com versões anteriores da API.
// ============================================================================

// Arquivar ou desarquivar um chat. Payload: { to, archive }
router.post('/:sessionId/chats/archive', sessionTokenAuth, async (req, res) => {
    try {
        const { to, archive } = req.body;
        if (!to || typeof archive === 'undefined') {
            return res.status(400).json({ error: 'Campos "to" e "archive" são obrigatórios.' });
        }
        // A API Baileys requer lastMessages para arquivar; entretanto, omitir
        // esse campo ainda funciona nas versões recentes. Usamos apenas { archive }
        await req.session.socket.chatModify({ archive: !!archive }, to);
        res.json({ status: archive ? 'archived' : 'unarchived' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao arquivar/desarquivar chat.' });
    }
});

// Silenciar ou dessilenciar um chat. Payload: { to, time }. "time" em ms ou null.
router.post('/:sessionId/chats/mute', sessionTokenAuth, async (req, res) => {
    try {
        const { to, time } = req.body;
        if (!to) return res.status(400).json({ error: 'Campo "to" obrigatório.' });
        // time null dessilencia; caso contrário, deve ser um número (ms)
        const muteVal = time === null || time === undefined ? null : parseInt(time, 10);
        await req.session.socket.chatModify({ mute: muteVal }, to);
        res.json({ status: muteVal ? 'muted' : 'unmuted' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao (des)silenciar chat.' });
    }
});

// Limpar (apagar) um chat apenas para você. Payload: { to }
router.post('/:sessionId/chats/clear', sessionTokenAuth, async (req, res) => {
    try {
        const { to } = req.body;
        if (!to) return res.status(400).json({ error: 'Campo "to" obrigatório.' });
        // "clear": "all" remove todas as mensagens para este usuário【875783813627243†L1242-L1255】
        await req.session.socket.chatModify({ clear: 'all' }, to);
        res.json({ status: 'cleared' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao limpar chat.' });
    }
});

// Marcar chat como lido ou não lido. Payload: { to, read }
router.post('/:sessionId/chats/mark-read', sessionTokenAuth, async (req, res) => {
    try {
        const { to, read } = req.body;
        if (!to || typeof read === 'undefined') {
            return res.status(400).json({ error: 'Campos "to" e "read" são obrigatórios.' });
        }
        // markRead: true marca como lido, false marca como não lido【875783813627243†L1234-L1241】
        await req.session.socket.chatModify({ markRead: !!read }, to);
        res.json({ status: read ? 'read' : 'unread' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao marcar chat.' });
    }
});

router.get('/:sessionId/privacy', sessionTokenAuth, async (req, res) => {
    try {
        const settings = await req.session.socket.fetchPrivacySettings(true);
        res.json(settings);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao obter privacidade.' });
    }
});

router.put('/:sessionId/privacy/last-seen', sessionTokenAuth, async (req, res) => {
    try {
        const { value } = req.body;
        if (!value) return res.status(400).json({ error: 'Campo "value" obrigatório.' });
        await req.session.socket.updateLastSeenPrivacy(value);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao atualizar last-seen.' });
    }
});

router.put('/:sessionId/privacy/online', sessionTokenAuth, async (req, res) => {
    try {
        const { value } = req.body;
        if (!value) return res.status(400).json({ error: 'Campo "value" obrigatório.' });
        await req.session.socket.updateOnlinePrivacy(value);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao atualizar online.' });
    }
});

router.put('/:sessionId/privacy/profile-picture', sessionTokenAuth, async (req, res) => {
    try {
        const { value } = req.body;
        if (!value) return res.status(400).json({ error: 'Campo "value" obrigatório.' });
        await req.session.socket.updateProfilePicturePrivacy(value);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao atualizar privacidade foto.' });
    }
});

router.put('/:sessionId/privacy/status', sessionTokenAuth, async (req, res) => {
    try {
        const { value } = req.body;
        if (!value) return res.status(400).json({ error: 'Campo "value" obrigatório.' });
        await req.session.socket.updateStatusPrivacy(value);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao atualizar privacidade status.' });
    }
});

router.put('/:sessionId/privacy/read-receipts', sessionTokenAuth, async (req, res) => {
    try {
        const { value } = req.body;
        if (!value) return res.status(400).json({ error: 'Campo "value" obrigatório.' });
        await req.session.socket.updateReadReceiptsPrivacy(value);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao atualizar recibos leitura.' });
    }
});

router.put('/:sessionId/privacy/groups-add', sessionTokenAuth, async (req, res) => {
    try {
        const { value } = req.body;
        if (!value) return res.status(400).json({ error: 'Campo "value" obrigatório.' });
        await req.session.socket.updateGroupsAddPrivacy(value);
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao atualizar add grupos.' });
    }
});

router.put('/:sessionId/privacy/default-disappearing', sessionTokenAuth, async (req, res) => {
    try {
        const { seconds } = req.body;
        if (seconds === undefined) return res.status(400).json({ error: 'Campo "seconds" obrigatório.' });
        await req.session.socket.updateDefaultDisappearingMode(parseInt(seconds, 10));
        res.json({ status: 'success' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Falha ao atualizar disappearing.' });
    }
});

module.exports = router;
