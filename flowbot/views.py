import json
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from .engine import FlowEngine
from .forms import FlowBotForm, FlowMediaForm
from .models import FlowBot, FlowConversation, FlowMedia, FlowMessage


# ==========================================
# HELPERS
# ==========================================

DEFAULT_FLOW = {
    "version": 1,
    "start_node_id": "n_start",
    "nodes": {
        "n_start": {"id": "n_start", "type": "start", "x": 80, "y": 80, "data": {}},
        "n_hi": {
            "id": "n_hi",
            "type": "text",
            "x": 320,
            "y": 80,
            "data": {"text": "Oi! 😊\nSou o assistente da {{empresa}}.\nComo posso te ajudar hoje?"},
        },
        "n_menu": {
            "id": "n_menu",
            "type": "menu",
            "x": 560,
            "y": 80,
            "data": {
                "prompt": "Escolhe uma opção:",
                "options": [
                    {"label": "Quero um orçamento", "port": "opt_1"},
                    {"label": "Quero falar com atendimento", "port": "opt_2"},
                ],
            },
        },
        "n_orc": {
            "id": "n_orc",
            "type": "ask_input",
            "x": 820,
            "y": 20,
            "data": {"prompt": "Perfeito! Me descreve o que você precisa, em 1 ou 2 frases.", "var": "pedido"},
        },
        "n_end": {"id": "n_end", "type": "end", "x": 1080, "y": 20, "data": {"text": "Fechado! Já anotei. ✅"}},
        "n_att": {"id": "n_att", "type": "text", "x": 820, "y": 160, "data": {"text": "Beleza! Me diz seu nome e WhatsApp que eu te encaminho."}},
    },
    "edges": [
        {"id": "e1", "from": "n_start", "fromPort": "out", "to": "n_hi", "toPort": "in"},
        {"id": "e2", "from": "n_hi", "fromPort": "out", "to": "n_menu", "toPort": "in"},
        {"id": "e3", "from": "n_menu", "fromPort": "opt_1", "to": "n_orc", "toPort": "in"},
        {"id": "e4", "from": "n_orc", "fromPort": "next", "to": "n_end", "toPort": "in"},
        {"id": "e5", "from": "n_menu", "fromPort": "opt_2", "to": "n_att", "toPort": "in"},
        {"id": "e6", "from": "n_att", "fromPort": "out", "to": "n_end", "toPort": "in"},
    ],
}

NODE_LIBRARY = [
    # id, label, type, inputs, outputs, fields
    {
        "type": "start",
        "label": "Start",
        "inputs": [],
        "outputs": ["out"],
        "fields": [],
        "help": "Ponto inicial do fluxo. Deve existir 1.",
    },
    {
        "type": "text",
        "label": "Texto",
        "inputs": ["in"],
        "outputs": ["out"],
        "fields": [
            {"key": "text", "label": "Mensagem", "kind": "textarea", "placeholder": "Digite o texto..."},
            {"key": "delay_ms", "label": "Delay (ms)", "kind": "number", "placeholder": "0"},
        ],
        "help": "Envia texto para o usuário. Suporta {{variaveis}} e {{last_user_text}}.",
    },
    {
        "type": "ask_input",
        "label": "Pergunta (captura)",
        "inputs": ["in"],
        "outputs": ["next"],
        "fields": [
            {"key": "prompt", "label": "Pergunta", "kind": "textarea"},
            {"key": "var", "label": "Salvar em variável", "kind": "text", "placeholder": "ex: nome"},
        ],
        "help": "Faz uma pergunta e aguarda a resposta. Salva em variável.",
    },
    {
        "type": "menu",
        "label": "Menu (opções)",
        "inputs": ["in"],
        "outputs": ["opt_1", "opt_2", "opt_3", "opt_4"],
        "fields": [
            {"key": "prompt", "label": "Texto do menu", "kind": "textarea"},
            {"key": "options", "label": "Opções (1 por linha)", "kind": "options_multiline", "placeholder": "Quero orçamento\nQuero atendimento"},
        ],
        "help": "Mostra opções numeradas e ramifica por escolha (1,2,3,4).",
    },
    {
        "type": "condition",
        "label": "Condição",
        "inputs": ["in"],
        "outputs": ["yes", "no"],
        "fields": [
            {"key": "source", "label": "Fonte", "kind": "text", "placeholder": "last_user_text ou nome_variavel"},
            {"key": "kind", "label": "Tipo", "kind": "select", "choices": ["contains", "equals", "startswith", "endswith", "regex"]},
            {"key": "value", "label": "Valor", "kind": "text"},
            {"key": "yes_port", "label": "Porta YES", "kind": "text", "placeholder": "yes"},
            {"key": "no_port", "label": "Porta NO", "kind": "text", "placeholder": "no"},
        ],
        "help": "Se condição for verdadeira, sai por YES; senão por NO.",
    },
    {
        "type": "set_var",
        "label": "Setar Variável",
        "inputs": ["in"],
        "outputs": ["out"],
        "fields": [
            {"key": "key", "label": "Chave", "kind": "text", "placeholder": "ex: empresa"},
            {"key": "value", "label": "Valor", "kind": "text", "placeholder": "ex: Bumbbe"},
        ],
        "help": "Define uma variável do fluxo (ex: empresa=Bumbbe).",
    },
    {
        "type": "media",
        "label": "Enviar Arquivo",
        "inputs": ["in"],
        "outputs": ["out"],
        "fields": [
            {"key": "media_id", "label": "Arquivo", "kind": "media_select"},
            {"key": "caption", "label": "Legenda", "kind": "textarea"},
            {"key": "delay_ms", "label": "Delay (ms)", "kind": "number", "placeholder": "0"},
        ],
        "help": "Envia um arquivo (imagem/áudio/PDF etc.) do seu acervo de mídias.",
    },
    {
        "type": "capture_contact",
        "label": "Capturar Contato",
        "inputs": ["in"],
        "outputs": ["out"],
        "fields": [
            {"key": "mode", "label": "Modo", "kind": "select", "choices": ["both", "name", "whatsapp"]},
            {"key": "ask_name", "label": "Perguntar nome", "kind": "text"},
            {"key": "ask_whatsapp", "label": "Perguntar WhatsApp", "kind": "text"},
        ],
        "help": "Pede nome/WhatsApp do visitante e salva na conversa.",
    },
    {
        "type": "end",
        "label": "Fim",
        "inputs": ["in"],
        "outputs": [],
        "fields": [{"key": "text", "label": "Mensagem final", "kind": "text"}],
        "help": "Finaliza o fluxo.",
    },
]


def _owner_only(request, bot: FlowBot):
    if bot.user_id != request.user.id:
        return False
    return True


# ==========================================
# PÁGINAS
# ==========================================

@login_required
def flowbot_list_view(request):
    bots = FlowBot.objects.filter(user=request.user).order_by("-updated_at")
    return render(request, "flowbot/list.html", {"bots": bots})


@login_required
def flowbot_create_view(request):
    if request.method == "POST":
        form = FlowBotForm(request.POST)
        if form.is_valid():
            bot = form.save(commit=False)
            bot.user = request.user
            # fluxo padrão
            bot.flow_json = DEFAULT_FLOW
            # predefine variável empresa baseado no name
            # (cliente pode mudar no builder)
            bot.save()
            messages.success(request, "FlowBot criado! Agora edite o fluxo.")
            return redirect("flowbot:builder", bot_id=bot.id)
        messages.error(request, "Corrija os erros do formulário.")
    else:
        form = FlowBotForm()
    return render(request, "flowbot/form.html", {"form": form, "title": "Criar FlowBot"})


@login_required
def flowbot_detail_view(request, bot_id):
    bot = get_object_or_404(FlowBot, id=bot_id)
    if not _owner_only(request, bot):
        return HttpResponseForbidden("Sem permissão.")
    return render(request, "flowbot/detail.html", {"bot": bot})


@login_required
def flowbot_delete_view(request, bot_id):
    bot = get_object_or_404(FlowBot, id=bot_id)
    if not _owner_only(request, bot):
        return HttpResponseForbidden("Sem permissão.")
    if request.method == "POST":
        bot.delete()
        messages.success(request, "FlowBot excluído.")
        return redirect("flowbot:list")
    return render(request, "flowbot/delete.html", {"bot": bot})


@login_required
def flowbot_builder_view(request, bot_id):
    bot = get_object_or_404(FlowBot, id=bot_id)
    if not _owner_only(request, bot):
        return HttpResponseForbidden("Sem permissão.")

    # injeta biblioteca e settings iniciais
    return render(
        request,
        "flowbot/builder.html",
        {
            "bot": bot,
            "node_library_json": json.dumps(NODE_LIBRARY, ensure_ascii=False),
        },
    )


@login_required
def flowbot_media_view(request, bot_id):
    bot = get_object_or_404(FlowBot, id=bot_id)
    if not _owner_only(request, bot):
        return HttpResponseForbidden("Sem permissão.")

    if request.method == "POST":
        form = FlowMediaForm(request.POST, request.FILES)
        if form.is_valid():
            m = form.save(commit=False)
            m.bot = bot
            m.save()
            messages.success(request, "Arquivo adicionado.")
            return redirect("flowbot:media", bot_id=bot.id)
        messages.error(request, "Erro ao enviar arquivo.")
    else:
        form = FlowMediaForm()

    medias = bot.medias.all()
    return render(request, "flowbot/media.html", {"bot": bot, "form": form, "medias": medias})


@login_required
def flowbot_media_delete_view(request, media_id):
    media = get_object_or_404(FlowMedia, id=media_id)
    bot = media.bot
    if not _owner_only(request, bot):
        return HttpResponseForbidden("Sem permissão.")
    if request.method == "POST":
        media.delete()
        messages.success(request, "Arquivo removido.")
        return redirect("flowbot:media", bot_id=bot.id)
    return render(request, "flowbot/media_delete.html", {"media": media, "bot": bot})


# ==========================================
# APIs (AJAX)
# ==========================================

@login_required
def api_get_flow(request, bot_id):
    bot = get_object_or_404(FlowBot, id=bot_id)
    if not _owner_only(request, bot):
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)
    return JsonResponse({"ok": True, "flow": bot.flow_json or DEFAULT_FLOW})


@login_required
def api_save_flow(request, bot_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    bot = get_object_or_404(FlowBot, id=bot_id)
    if not _owner_only(request, bot):
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        flow = payload.get("flow") or {}
        # Valida minimamente
        if not isinstance(flow, dict):
            raise ValueError("flow inválido")
        if "nodes" not in flow or "edges" not in flow:
            raise ValueError("flow precisa ter nodes e edges")
        bot.flow_json = flow
        bot.save(update_fields=["flow_json", "updated_at"])
        return JsonResponse({"ok": True})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)


@login_required
def api_media_list(request, bot_id):
    bot = get_object_or_404(FlowBot, id=bot_id)
    if not _owner_only(request, bot):
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)

    items = []
    for m in bot.medias.all():
        items.append(
            {
                "id": m.id,
                "title": m.title or m.file.name.split("/")[-1],
                "media_type": m.media_type,
                "url": m.file.url,
                "caption": m.caption or "",
            }
        )
    return JsonResponse({"ok": True, "items": items})


def _get_or_create_builder_conversation(request, bot: FlowBot) -> FlowConversation:
    key = request.session.get(f"flowbot_conv_{bot.id}")
    conv = None
    if key:
        conv = FlowConversation.objects.filter(bot=bot, session_key=key).first()
    if not conv:
        conv = FlowConversation.objects.create(bot=bot, state={"vars": {"empresa": bot.name}})
        request.session[f"flowbot_conv_{bot.id}"] = str(conv.session_key)
    return conv


@login_required
def api_chat_start(request, bot_id):
    bot = get_object_or_404(FlowBot, id=bot_id)
    if not _owner_only(request, bot):
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)

    conv = _get_or_create_builder_conversation(request, bot)
    # dispara execução inicial: roda até pedir input (sem mensagem do usuário)
    engine = FlowEngine(conv)
    outputs = engine.handle_user_message("")  # inicializa
    return JsonResponse({"ok": True, "session_key": str(conv.session_key), "outputs": [o.__dict__ for o in outputs]})


@login_required
def api_chat_send(request, bot_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    bot = get_object_or_404(FlowBot, id=bot_id)
    if not _owner_only(request, bot):
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)

    conv = _get_or_create_builder_conversation(request, bot)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        text = (payload.get("text") or "").strip()
        st = conv.state or {}
        waiting = st.get("waiting") or {}
        engine = FlowEngine(conv)

        if waiting and waiting.get("type") in ("menu", "capture_name", "capture_whatsapp"):
            outputs = engine.handle_waiting_reply(text)
        else:
            outputs = engine.handle_user_message(text)

        return JsonResponse({"ok": True, "outputs": [o.__dict__ for o in outputs]})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)


@login_required
def api_chat_reset(request, bot_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    bot = get_object_or_404(FlowBot, id=bot_id)
    if not _owner_only(request, bot):
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)

    conv = _get_or_create_builder_conversation(request, bot)
    # limpa histórico
    FlowMessage.objects.filter(conversation=conv).delete()
    conv.state = {"vars": {"empresa": bot.name}}
    conv.visitor_name = ""
    conv.visitor_whatsapp = ""
    conv.save(update_fields=["state", "visitor_name", "visitor_whatsapp", "updated_at"])
    return JsonResponse({"ok": True})


# ==========================================
# APIs PÚBLICAS (para integrações: WordPress, apps, etc.)
#
# Autenticação: token UUID do FlowBot (public_token).
# O cliente (front) deve guardar a session_key retornada e enviá-la nas próximas mensagens.
# ==========================================

def _public_get_or_create_conversation(bot: FlowBot, session_key: str | None) -> FlowConversation:
    conv = None
    if session_key:
        try:
            conv = FlowConversation.objects.filter(bot=bot, session_key=session_key).first()
        except Exception:
            conv = None
    if not conv:
        conv = FlowConversation.objects.create(bot=bot, state={"vars": {"empresa": bot.name}})
    return conv


@csrf_exempt
def api_public_chat_start(request, token):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    bot = FlowBot.objects.filter(public_token=token, active=True).first()
    if not bot:
        return JsonResponse({"ok": False, "error": "Bot inválido ou inativo."}, status=404)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}

    session_key = payload.get("session_key")  # opcional
    conv = _public_get_or_create_conversation(bot, session_key)

    # roda início do fluxo
    engine = FlowEngine(conv)
    outputs = engine.handle_user_message("")  # inicializa

    return JsonResponse(
        {"ok": True, "session_key": str(conv.session_key), "outputs": [o.__dict__ for o in outputs]}
    )


@csrf_exempt
def api_public_chat_send(request, token):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    bot = FlowBot.objects.filter(public_token=token, active=True).first()
    if not bot:
        return JsonResponse({"ok": False, "error": "Bot inválido ou inativo."}, status=404)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}

    session_key = payload.get("session_key")
    text = (payload.get("text") or "").strip()

    conv = _public_get_or_create_conversation(bot, session_key)
    engine = FlowEngine(conv)

    st = conv.state or {}
    waiting = st.get("waiting") or {}

    if waiting and waiting.get("type") in ("menu", "capture_name", "capture_whatsapp"):
        outputs = engine.handle_waiting_reply(text)
    else:
        outputs = engine.handle_user_message(text)

    return JsonResponse({"ok": True, "session_key": str(conv.session_key), "outputs": [o.__dict__ for o in outputs]})


@csrf_exempt
def api_public_chat_reset(request, token):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    bot = FlowBot.objects.filter(public_token=token, active=True).first()
    if not bot:
        return JsonResponse({"ok": False, "error": "Bot inválido ou inativo."}, status=404)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}

    session_key = payload.get("session_key")
    conv = _public_get_or_create_conversation(bot, session_key)

    FlowMessage.objects.filter(conversation=conv).delete()
    conv.state = {"vars": {"empresa": bot.name}}
    conv.visitor_name = ""
    conv.visitor_whatsapp = ""
    conv.save(update_fields=["state", "visitor_name", "visitor_whatsapp", "updated_at"])

    return JsonResponse({"ok": True, "session_key": str(conv.session_key)})
