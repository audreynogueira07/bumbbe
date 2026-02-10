import logging
import re
import traceback
from django.utils import timezone
from .models import WordpressBot, WordpressContact, WordpressMessage, WordpressMedia

try:
    import openai
except ImportError:
    openai = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None

logger = logging.getLogger(__name__)

class WordpressBotEngine:
    def __init__(self, bot):
        self.bot = bot

    def process_input(self, session_uuid, user_message, user_name=None, user_phone=None, user_email=None, meta=None):
        """
        meta = meta or {}
        Processa a entrada do usuário e retorna um dicionário com a resposta.
        """
        # 1. Identificar ou Criar Contato
        contact, created = WordpressContact.objects.get_or_create(
            bot=self.bot,
            session_uuid=session_uuid
        )

        # Atualizar dados se vierem na requisição (ex: form pré-chat do plugin)
        if user_name: 
            contact.name = user_name
            if contact.input_state == 1: contact.input_state = 2 # Pula etapa nome
        if user_phone:
            contact.phone = user_phone
        if user_email:
            contact.email = user_email
            if contact.input_state == 2: contact.input_state = 0 # Cadastro completo

        # Salva a mensagem do usuário no histórico
        if user_message:
            WordpressMessage.objects.create(
                contact=contact,
                sender='user',
                content=user_message,  # <-- CORRIGIDO: Adicionada vírgula
                meta=meta,
            )

        # 2. Lógica de Captura de Dados (Se não tiver cadastro completo)
        response_text = ""
        
        # STATE 1: Pedir Nome
        if contact.input_state == 1:
            if user_message and not created:
                # Assume que a mensagem é o nome
                contact.name = user_message.strip()
                contact.input_state = 2 # Vai para pedir telefone
                contact.save()
                response_text = f"Prazer, {contact.name}! Para finalizarmos o cadastro e eu poder te atender melhor, qual o seu número de WhatsApp (com DDD)?"
            else:
                # Primeira mensagem, pede o nome
                response_text = "Olá! Bem-vindo ao nosso atendimento. Para começar, por favor, digite seu *Nome*:"
        
        # STATE 2: Pedir Telefone
        elif contact.input_state == 2:
            if user_message:
                # Assume que a mensagem é o telefone
                contact.phone = user_message.strip()
                contact.input_state = 0 # Libera IA
                contact.save()
                response_text = "Obrigado! Cadastro realizado. Agora pode me contar, como posso ajudar você hoje?"
            else:
                response_text = "Por favor, digite seu número de WhatsApp para continuarmos:"

        # STATE 0: IA Ativa
        else:
            response_text = self._generate_ai_response(contact, user_message)

        # 3. Salvar Resposta do Bot
        bot_msg = WordpressMessage.objects.create(
            contact=contact,
            sender='bot',
            content=response_text, # <-- CORRIGIDO: Adicionada vírgula
            meta=meta,
        )

        # 4. Verificar Mídia na Resposta
        media_url = None
        media_type = None
        
        if "SEND_MEDIA_ID:" in response_text:
            try:
                parts = response_text.split("SEND_MEDIA_ID:")
                clean_text = parts[0].strip()
                media_id = parts[1].strip().split()[0]
                
                media = WordpressMedia.objects.get(id=media_id, bot=self.bot)
                media_url = media.file.url
                media_type = media.media_type
                
                # Atualiza mensagem limpa no banco
                bot_msg.content = clean_text
                bot_msg.media_url = media_url
                bot_msg.save()
                
                response_text = clean_text
            except Exception as e:
                logger.error(f"Erro processando mídia: {e}")

        return {
            "text": response_text,
            "media_url": media_url,
            "media_type": media_type
        }

    def _generate_ai_response(self, contact, user_msg):
        """Gera resposta usando OpenAI ou Gemini."""
        if not user_msg: return "Olá! Em que posso ajudar?"

        # Mensagem de erro amigável (Transbordo)
        FALLBACK_MESSAGE = "Estamos transferindo para um atendente, aguarde um instante"

        # Construir Prompt
        system_prompt = self._build_prompt(contact)
        history = self._get_history(contact)

        try:
            response = None
            
            if self.bot.ai_provider == 'openai':
                response = self._call_openai(system_prompt, user_msg, history)
            elif self.bot.ai_provider == 'gemini':
                response = self._call_gemini(system_prompt, user_msg, history)
            
            # Se a resposta vier vazia ou None, tratamos como erro
            if not response:
                raise Exception("Resposta da IA vazia")

            return response

        except Exception as e:
            # Loga o erro técnico para o desenvolvedor ver no console/arquivo
            logger.error(f"Erro Crítico na IA (Bot {self.bot.name}): {str(e)}")
            logger.error(traceback.format_exc())
            
            # Retorna APENAS a mensagem amigável para o cliente
            return FALLBACK_MESSAGE

    def _build_prompt(self, contact):
        medias = self.bot.medias.all()
        media_context = ""
        if medias:
            media_context = "\n# ARQUIVOS DISPONÍVEIS\n"
            for m in medias:
                media_context += f"- ID: {m.id} ({m.media_type}): {m.description} | Regra: {m.send_rules}\n"
            media_context += "Para enviar, termine a resposta com: SEND_MEDIA_ID: <ID>\n"

        return f"""
        Você é {self.bot.name} da empresa {self.bot.company_name}.
        O cliente se chama {contact.name or 'Visitante'}.
        
        {self.bot.company_summary}
        
        Diretrizes:
        - Tom: {self.bot.conversation_tone}
        - Horários: {self.bot.business_hours}
        - Seja direto e formatado com Markdown simples.
        
        {self.bot.context or ''}
        {self.bot.skills or ''}
        
        {media_context}
        """

    def _get_history(self, contact):
        if not self.bot.use_history: return []
        # Pega ultimas N mensagens
        msgs = contact.messages.order_by('-timestamp')[:self.bot.history_limit]
        history = []
        for m in reversed(msgs):
            role = "assistant" if m.sender == 'bot' else "user"
            history.append({"role": role, "content": m.content})
        return history

    def _call_openai(self, system, user_msg, history):
        # Se não tiver o driver, lança exceção para cair no Fallback
        if not openai: 
            raise ImportError("OpenAI driver (biblioteca 'openai') não instalado no servidor.")
            
        client = openai.Client(api_key=self.bot.api_key)
        messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": user_msg}]
        
        resp = client.chat.completions.create(
            model=self.bot.model_name or "gpt-3.5-turbo",
            messages=messages
        )
        return resp.choices[0].message.content

    def _call_gemini(self, system, user_msg, history):
        # Se não tiver o driver, lança exceção para cair no Fallback
        if not genai: 
            raise ImportError("Gemini driver (biblioteca 'google-generativeai') não instalado no servidor.")
            
        genai.configure(api_key=self.bot.api_key)
        model = genai.GenerativeModel(self.bot.model_name or 'gemini-pro')
        
        # Gemini history format simplificado
        full_prompt = f"{system}\n\n[Histórico]\n"
        for h in history:
            full_prompt += f"{h['role'].title()}: {h['content']}\n"
        full_prompt += f"User: {user_msg}\nAssistant:"
        
        resp = model.generate_content(full_prompt)
        return resp.text