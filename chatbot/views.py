from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.urls import reverse
from django.db.models import Q
from django.utils import timezone

# Importando os modelos e forms
from .models import Chatbot, ChatbotContact, ChatbotMedia, UserSubscription
from .forms import ChatbotContactForm, ChatbotForm, ChatbotMediaForm

# ==============================================================================
# GERENCIAMENTO DE CHATBOTS (DASHBOARD)
# ==============================================================================

@login_required
def chatbot_list_view(request):
    """Lista todos os chatbots do usuário e verifica permissão de criação baseada no Plano."""
    bots = Chatbot.objects.filter(user=request.user).order_by('-created_at')
    
    # --- LÓGICA DE VERIFICAÇÃO DE PLANO ---
    can_create = False
    try:
        # Tenta pegar a assinatura
        subscription = getattr(request.user, 'chatbot_subscription', None)
        
        if subscription and subscription.active and subscription.plan:
            # Verifica expiração se houver data definida
            if not subscription.expires_at or subscription.expires_at > timezone.now():
                current_count = bots.count()
                max_allowed = subscription.plan.max_chatbots
                if current_count < max_allowed:
                    can_create = True
    except Exception:
        can_create = False

    return render(request, 'chatbot/list.html', {
        'bots': bots,
        'can_create': can_create
    })

@login_required
def chatbot_create_view(request):
    """Cria um novo chatbot respeitando o limite do plano."""
    
    # --- VERIFICAÇÃO RÍGIDA DE PLANO ANTES DE CRIAR ---
    subscription = getattr(request.user, 'chatbot_subscription', None)
    
    if not subscription or not subscription.active or not subscription.plan:
        messages.error(request, "Você precisa de um plano ativo para criar um Chatbot.")
        return redirect('chatbot:list')
    
    current_count = Chatbot.objects.filter(user=request.user).count()
    if current_count >= subscription.plan.max_chatbots:
        messages.error(request, f"Seu plano '{subscription.plan.name}' atingiu o limite de {subscription.plan.max_chatbots} chatbots.")
        return redirect('chatbot:list')

    # --- PROCESSAMENTO DO FORMULÁRIO ---
    if request.method == 'POST':
        # Removemos 'user=request.user' do construtor para evitar TypeError se o form for padrão
        form = ChatbotForm(request.POST) 
        
        # --- CORREÇÃO DO ERRO 'Chatbot has no user' ---
        # Atribuímos o usuário à instância ANTES de validar
        form.instance.user = request.user 
        
        if form.is_valid():
            chatbot = form.save()
            messages.success(request, "Chatbot criado com sucesso!")
            return redirect('chatbot:edit', bot_id=chatbot.id)
        else:
            messages.error(request, "Corrija os erros abaixo.")
    else:
        form = ChatbotForm()

    return render(request, 'chatbot/form.html', {'form': form, 'title': 'Novo Chatbot'})

@login_required
def chatbot_edit_view(request, bot_id):
    """Edita configurações e gerencia mídias do chatbot."""
    chatbot = get_object_or_404(Chatbot, id=bot_id, user=request.user)

    form = ChatbotForm(instance=chatbot, user=request.user)
    media_form = ChatbotMediaForm()

    if request.method == 'POST':
        # --- UPDATE BOT CONFIG ---
        if 'update_bot' in request.POST:
            # 2. CORREÇÃO AQUI: Passar user=request.user no POST
            form = ChatbotForm(request.POST, instance=chatbot, user=request.user)
            
            # Nota: Não precisa de form.instance.user = request.user aqui
            # porque o save() do ModelForm já usa a instância carregada do banco
            
            if form.is_valid():
                form.save()
                messages.success(request, "Configurações atualizadas!")
                return redirect('chatbot:edit', bot_id=chatbot.id)
            else:
                 # Isso vai mostrar na tela qual campo está dando erro
                 messages.error(request, f"Erro ao salvar: {form.errors.as_text()}")

        # --- ADD MEDIA ---
        elif 'add_media' in request.POST:
            media_form = ChatbotMediaForm(request.POST, request.FILES)
            
            if media_form.is_valid():
                media = media_form.save(commit=False)
                media.chatbot = chatbot
                media.save()
                messages.success(request, "Mídia adicionada à base de conhecimento!")
                return redirect('chatbot:edit', bot_id=chatbot.id)
            else:
                messages.error(request, f"Erro ao enviar mídia: {media_form.errors.as_text()}")

    # --- Lógica Comum (Renderização) ---
    medias = chatbot.medias.all().order_by('-created_at')

    # Cálculo de uso do plano
    usage_percent = 0
    limit_conversations = 0
    subscription = getattr(request.user, 'chatbot_subscription', None)
    
    if subscription and subscription.plan:
        limit_conversations = subscription.plan.max_conversations
        if limit_conversations > 0:
            usage_percent = (chatbot.conversations_count / limit_conversations) * 100
        elif limit_conversations == 0:
            usage_percent = 0 

    return render(request, 'chatbot/edit.html', {
        'form': form,
        'media_form': media_form,
        'chatbot': chatbot,
        'medias': medias,
        'usage_info': {
            'count': chatbot.conversations_count, 
            'limit': limit_conversations,
            'percent': min(usage_percent, 100)
        }
    })
    
@login_required
def chatbot_delete_view(request, bot_id):
    """Deleta um chatbot."""
    chatbot = get_object_or_404(Chatbot, id=bot_id, user=request.user)
    
    # Se for GET, renderiza confirmação (opcional) ou deleta direto no POST
    # Aqui assumindo que você tem um link que leva a uma página de confirmação ou um modal
    if request.method == 'POST' or request.GET.get('confirm') == 'true':
        chatbot.delete()
        messages.success(request, "Chatbot removido com sucesso.")
        return redirect('chatbot:list')
        
    # Se você tiver um template de confirmação de exclusão:
    return render(request, 'chatbot/confirm_delete.html', {'object': chatbot})

@login_required
def chatbot_media_delete_view(request, media_id):
    """Deleta uma mídia específica."""
    media = get_object_or_404(ChatbotMedia, id=media_id, chatbot__user=request.user)
    bot_id = media.chatbot.id
    media.delete()
    messages.success(request, "Mídia removida.")
    return redirect('chatbot:edit', bot_id=bot_id)

# ==============================================================================
# GESTÃO DE CONTATOS (CRM)
# ==============================================================================

@login_required
def contact_list_view(request):
    """Lista todos os contatos que interagiram."""
    contacts = ChatbotContact.objects.filter(chatbot__user=request.user).order_by('-last_interaction')
    
    query = request.GET.get('q')
    if query:
        contacts = contacts.filter(
            Q(remote_jid__icontains=query) | 
            Q(push_name__icontains=query) |
            Q(notes__icontains=query)
        )

    status_filter = request.GET.get('status')
    if status_filter == 'blocked':
        contacts = contacts.filter(is_blocked=True)
    
    context = {
        'contacts': contacts,
        'total_contacts': contacts.count(),
        'blocked_count': ChatbotContact.objects.filter(chatbot__user=request.user, is_blocked=True).count()
    }
    return render(request, 'chatbot/contacts.html', context)

@login_required
def contact_edit_view(request, contact_id):
    """Edita notas ou status de um contato."""
    contact = get_object_or_404(ChatbotContact, id=contact_id, chatbot__user=request.user)
    
    if request.method == 'POST':
        form = ChatbotContactForm(request.POST, instance=contact)
        if form.is_valid():
            form.save()
            messages.success(request, f"Contato {contact.remote_jid} atualizado.")
            return redirect('chatbot:contacts')
    else:
        form = ChatbotContactForm(instance=contact)
        
    return render(request, 'chatbot/contact_edit.html', {
        'form': form,
        'contact': contact,
        # Histórico fictício ou real, dependendo do seu modelo Message
        'history': getattr(contact, 'history', None) 
    })