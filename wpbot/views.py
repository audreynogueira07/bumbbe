from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import WordpressBot, WordpressMedia, WordpressContact, WordpressMessage
from .forms import WordpressBotForm, WordpressMediaForm

# ====================
# GESTÃO DE BOTS
# ====================

@login_required
def bot_list(request):
    bots = WordpressBot.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'wpbot/list.html', {'bots': bots})

@login_required
def bot_create(request):
    if request.method == 'POST':
        form = WordpressBotForm(request.POST)
        if form.is_valid():
            bot = form.save(commit=False)
            bot.user = request.user
            bot.save()
            messages.success(request, "Bot WordPress criado!")
            return redirect('wpbot:edit', bot_id=bot.id)
    else:
        form = WordpressBotForm()
    return render(request, 'wpbot/form.html', {'form': form, 'title': 'Novo Bot WordPress'})

@login_required
def bot_edit(request, bot_id):
    bot = get_object_or_404(WordpressBot, id=bot_id, user=request.user)
    form = WordpressBotForm(instance=bot)
    media_form = WordpressMediaForm()

    if request.method == 'POST':
        if 'update_bot' in request.POST:
            form = WordpressBotForm(request.POST, instance=bot)
            if form.is_valid():
                form.save()
                messages.success(request, "Configurações salvas.")
                return redirect('wpbot:edit', bot_id=bot.id)
        
        elif 'add_media' in request.POST:
            media_form = WordpressMediaForm(request.POST, request.FILES)
            if media_form.is_valid():
                media = media_form.save(commit=False)
                media.bot = bot
                media.save()
                messages.success(request, "Mídia adicionada.")
                return redirect('wpbot:edit', bot_id=bot.id)

    medias = bot.medias.all()
    # URL da API para mostrar ao usuário
    api_endpoint = request.build_absolute_uri('/wpbot/api/chat/')
    
    return render(request, 'wpbot/edit.html', {
        'form': form,
        'media_form': media_form,
        'bot': bot,
        'medias': medias,
        'api_endpoint': api_endpoint
    })

@login_required
def bot_delete(request, bot_id):
    bot = get_object_or_404(WordpressBot, id=bot_id, user=request.user)
    if request.method == 'POST':
        bot.delete()
        messages.success(request, "Bot excluído.")
        return redirect('wpbot:list')
    return render(request, 'wpbot/confirm_delete.html', {'object': bot})

# ====================
# LEADS E CONVERSAS
# ====================

@login_required
def leads_list(request):
    contacts = WordpressContact.objects.filter(bot__user=request.user).order_by('-last_interaction')
    return render(request, 'wpbot/leads.html', {'contacts': contacts})

@login_required
def lead_detail(request, contact_id):
    contact = get_object_or_404(WordpressContact, id=contact_id, bot__user=request.user)
    messages_history = contact.messages.all().order_by('timestamp')
    return render(request, 'wpbot/lead_detail.html', {
        'contact': contact,
        'messages': messages_history
    })