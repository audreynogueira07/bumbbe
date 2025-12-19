# API REST para WhatsApp usando Baileys

Este projeto oferece uma API HTTP simples baseada em [Express.js](https://expressjs.com) e na biblioteca não oficial [Baileys](https://baileys.wiki/docs/intro/) para controlar uma conta do WhatsApp Web. O objetivo é permitir que você integre o envio de mensagens, envio de mídias e operações básicas de grupos nos seus projetos próprios, sem depender de serviços externos. Todas as sessões são armazenadas em disco (dentro da pasta `auth/`) para que você não precise escanear o QR‐code toda vez que reiniciar o servidor.

> **Aviso importante:** A biblioteca Baileys **não** é afiliada nem endossada pelo WhatsApp. Ela utiliza o protocolo do **WhatsApp Web** para interagir com o serviço e destina‑se apenas a fins educativos ou pessoais. Conforme descrito na documentação oficial, Baileys é um projeto independente e não se baseia no **WhatsApp Business API**【166920217618065†L22-L39】. Use por sua conta e risco e **não** utilize esta API para envio de spam ou quebra de políticas de uso do WhatsApp【44160331150546†L62-L75】.

## Recursos implementados

Esta API incorpora alguns dos recursos presentes em projetos mais completos, como:

* **Criação e gerenciamento de sessões** – abra várias contas do WhatsApp simultaneamente e armazene as credenciais de cada uma em disco.
* **QRCode de login** – ao iniciar uma sessão nova, a API gera um QR‑code para você escanear no WhatsApp do celular.
* **Envio de mensagens de texto** – envie mensagens para qualquer número ou grupo usando o identificador de WhatsApp (ex.: `5511999999999@s.whatsapp.net`).
* **Envio de mídias** – suporte ao envio de imagens, vídeos, áudios e documentos via formulário `multipart/form-data`.
* **Criação de grupos e gerenciamento de participantes** – crie grupos e adicione ou remova usuários.
* **Encerramento de sessão** – faça logout e exclua credenciais facilmente.

Esses recursos são inspirados em APIs REST completas descritas em outros repositórios, que incluem endpoints como `POST /api/messages/{sessionId}/send` para envio de texto e `POST /api/messages/{sessionId}/send-media` para envio de arquivos, bem como rotas para criação de grupos e adição de participantes【238698478121616†L456-L504】.

## Pré‑requisitos

* **Node.js 18 ou superior** – Baileys requer Node 17+【166920217618065†L57-L58】.
* **NPM** (ou Yarn) – para instalar as dependências.

## Instalação

1. Clone este repositório ou copie os arquivos para sua hospedagem:

   ```bash
   git clone https://exemplo.com/seu-usuario/whatsapp-api.git
   cd whatsapp-api
   ```

2. Instale as dependências:

   ```bash
   npm install
   ```

3. (Opcional) Defina a variável de ambiente `PORT` se quiser alterar a porta padrão (3001). Você pode criar um arquivo `.env` ou exportar diretamente:

   ```bash
   export PORT=8080
   ```

4. Inicie o servidor:

   ```bash
   npm start
   ```

O servidor estará acessível em `http://localhost:3001` (ou na porta definida).

## Uso

### 1. Criar uma sessão

Envie um `POST` para `/session` com um JSON contendo um `sessionId` único:

```bash
curl -X POST http://localhost:3001/session \
  -H "Content-Type: application/json" \
  -d '{"sessionId": "minha-sessao"}'
```

A resposta informará que a sessão foi criada. Em seguida, utilize o endpoint `/session/{sessionId}/qr` para obter o QR‑code e escaneie com o WhatsApp:

```bash
curl http://localhost:3001/session/minha-sessao/qr
```

Repita a chamada até o campo `qr` estar presente na resposta; então abra o link de dados retornado ou use algum visualizador de QR. Após escanear, a sessão ficará ativa e pronta para enviar mensagens.

### 2. Enviar mensagem de texto

Faça um `POST` em `/messages/send` com `sessionId`, o destinatário (`to`) e o texto (`message`):

```bash
curl -X POST http://localhost:3001/messages/send \
  -H "Content-Type: application/json" \
  -d '{"sessionId":"minha-sessao","to":"5511999999999@s.whatsapp.net","message":"Olá!"}'
```

### 3. Enviar mídia

Envie um arquivo via `multipart/form-data` usando o campo `file`. Você pode incluir um `caption` opcional:

```bash
curl -X POST http://localhost:3001/messages/send-media \
  -F sessionId=minha-sessao \
  -F to=5511999999999@s.whatsapp.net \
  -F caption="Veja esta foto" \
  -F file=@/caminho/para/imagem.jpg
```

O servidor detectará automaticamente se é imagem, vídeo, áudio ou documento com base no `Content-Type` do arquivo.

### 4. Criar grupo e gerenciar participantes

Para criar um grupo:

```bash
curl -X POST http://localhost:3001/groups/create \
  -H "Content-Type: application/json" \
  -d '{"sessionId":"minha-sessao","subject":"Meu Grupo","participants":["5511999999999@s.whatsapp.net","5511988888888@s.whatsapp.net"]}'
```

Para adicionar ou remover participantes utilize `action` igual a `add` ou `remove`:

```bash
curl -X POST http://localhost:3001/groups/update-participants \
  -H "Content-Type: application/json" \
  -d '{"sessionId":"minha-sessao","groupId":"123456789-987654@g.us","participants":["5511888888888@s.whatsapp.net"],"action":"add"}'
```

### 5. Encerrar uma sessão

Para encerrar e apagar as credenciais de uma sessão, envie um `DELETE`:

```bash
curl -X DELETE http://localhost:3001/session/minha-sessao
```

## Observações

* **Identificadores de usuário e grupo:** números de telefone e grupos devem seguir o padrão utilizado pelo WhatsApp, como `5511999999999@s.whatsapp.net` para contatos e `123456789-987654@g.us` para grupos【238698478121616†L456-L504】.
* **Políticas de uso:** esta API replica funcionalidades semelhantes às de projetos mais completos (como o repositório Baileys‑2025‑Rest‑API) que oferecem endpoints para autenticação, envio de mensagens, envio de mídias, criação de grupos, etc.【238698478121616†L456-L504】. Use com responsabilidade e jamais para spam ou marketing em massa【44160331150546†L62-L75】.
* **Hospedagem:** para implantar em sua hospedagem, verifique se há suporte a Node.js (versão 18+) e se você pode instalar dependências. Em muitos serviços de hospedagem compartilhada é possível subir este projeto via FTP e configurar um processo Node via painel de controle. Para ambientes mais complexos, considere utilizar um VPS, Docker ou PM2 para gerenciar o serviço.

## Licença

MIT. Consulte o arquivo `LICENSE` para mais detalhes.


npm install ws

npm install sharp

npm install sharp pino-pretty

npm install express-session bcryptjs express-rate-limit

npm install sqlite3 express-session connect-sqlite3 bcryptjs