// Carrega variáveis de ambiente
try {
  require('dotenv').config();
} catch (_) {
  // dotenv não está instalado; ignore
}

const express = require('express');
const http = require('http');
const path = require('path');
const fs = require('fs-extra');
const pino = require('pino');

// --- PACOTES DE SEGURANÇA ---
const helmet = require('helmet');
const cors = require('cors');
const rateLimit = require('express-rate-limit');

// Importa os módulos da API (Ajustado para sua estrutura ./src)
const apiRouter = require('./src/router');
const { setupWebSocket, broadcast } = require('./src/websocket');
const whatsapp = require('./src/whatsapp');

// Cria a aplicação Express e o servidor HTTP
const app = express();
const server = http.createServer(app);

// Porta configurada no .env ou padrão 9922
const port = process.env.PORT || 9922;

// Configuração do logger
const logger = pino({
  transport: {
    target: 'pino-pretty',
    options: { colorize: true, ignore: 'pid,hostname' }
  },
  level: process.env.LOG_LEVEL || 'info'
});

// Garante diretórios essenciais
fs.ensureDirSync(path.join(__dirname, 'tmp'));
fs.ensureDirSync(path.join(__dirname, 'auth'));

// ==============================================================================
// CONFIGURAÇÕES DE SEGURANÇA (HARDENING)
// ==============================================================================

// 1. HELMET: Protege headers HTTP
app.use(helmet({
    contentSecurityPolicy: false, // Desativado para não quebrar scripts inline do painel
    crossOriginEmbedderPolicy: false
}));

// 2. CORS: Permite acesso externo (ajuste o origin em produção se necessário)
app.use(cors({ origin: '*' }));

// 3. RATE LIMITING GERAL (Proteção básica contra DDOS)
const generalLimiter = rateLimit({
    windowMs: 15 * 60 * 1000, // 15 minutos
    max: 300, // 300 requisições por IP
    standardHeaders: true,
    legacyHeaders: false,
    message: { error: 'Muitas requisições deste IP, tente novamente mais tarde.' }
});

// 4. RATE LIMITING DE LOGIN (Proteção Rígida: 5 tentativas = 2h de bloqueio)
const authLimiter = rateLimit({
    windowMs: 2 * 60 * 60 * 1000, // 2 horas (em milissegundos)
    max: 5, // Limite máximo de 5 tentativas erradas
    message: { 
        error: 'Muitas tentativas de login incorretas. Por segurança, seu IP foi bloqueado por 2 horas.' 
    },
    standardHeaders: true,
    legacyHeaders: false,
});

// Aplica o limitador geral a todas as rotas
app.use(generalLimiter);

// Aplica o limitador RÍGIDO apenas na rota de verificação de senha
app.use('/auth/check', authLimiter);

// ==============================================================================
// CONFIGURAÇÕES PADRÃO
// ==============================================================================

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Injeta a função broadcast no módulo WhatsApp
whatsapp.initialize(broadcast);

// Configura o servidor WebSocket
setupWebSocket(server);

// ✅ Rotas da API expostas em `/`
app.use('/', apiRouter);

// Servir arquivos estáticos da pasta public (Painel)
app.use(express.static(path.join(__dirname, 'public')));

// Rota padrão para entregar o painel
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// Inicia o servidor e carrega sessões salvas
server.listen(port, async () => {
  logger.info(`[INFO] Servidor rodando na porta ${port}`);
  
  // Verificação de segurança da API Key no log
  if (!process.env.API_KEY || process.env.API_KEY === '123456') {
      logger.warn(`[PERIGO] API_KEY insegura ou não definida no .env! O sistema está vulnerável.`);
  } else {
      logger.info(`[SEGURANÇA] API Key configurada. Proteção de Brute Force ativa (5 tentativas/2h).`);
  }

  logger.info(`[INFO] Acesse http://localhost:${port} para ver o painel.`);

  try {
    await whatsapp.startAllSavedSessions();
    logger.info('[INFO] Sessões salvas iniciais carregadas.');
  } catch (err) {
    logger.error({ err }, '[ERROR] Erro ao iniciar sessões salvas:');
  }
});