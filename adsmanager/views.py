from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import (
    AdsAccountForm,
    UserAdsSettingsForm,
    AdCreativeForm,
    CampaignCreateForm,
    AdScheduleForm,
    AutomationRuleForm,
)
from .models import AdsAccount, AdCampaign, AdCreative, AdSchedule, AutomationRule, AutomationRun
from .services import AdsOrchestrator, ai_generate_ad_variations, get_user_ads_settings


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """
    Template: adsmanager/dashboard.html
    """
    accounts = AdsAccount.objects.filter(user=request.user).order_by("-updated_at")
    campaigns = AdCampaign.objects.filter(account__user=request.user).select_related("account").order_by("-updated_at")[:50]
    runs = AutomationRun.objects.filter(user=request.user).order_by("-started_at")[:25]

    ctx = {
        "accounts": accounts,
        "campaigns": campaigns,
        "runs": runs,
        "settings": get_user_ads_settings(request.user),
    }
    return render(request, "adsmanager/dashboard.html", ctx)


@login_required
def settings_view(request: HttpRequest) -> HttpResponse:
    """
    Template: adsmanager/settings.html
    """
    settings_obj = get_user_ads_settings(request.user)

    if request.method == "POST":
        form = UserAdsSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Configurações salvas.")
            return redirect("adsmanager:settings")
        messages.error(request, "Corrija os erros do formulário.")
    else:
        form = UserAdsSettingsForm(instance=settings_obj)

    return render(request, "adsmanager/settings.html", {"form": form, "settings": settings_obj})


@login_required
def account_list(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "adsmanager/accounts/list.html",
        {"accounts": AdsAccount.objects.filter(user=request.user).order_by("-updated_at")},
    )


@login_required
def account_create(request: HttpRequest) -> HttpResponse:
    """
    Template: adsmanager/accounts/form.html
    """
    if request.method == "POST":
        form = AdsAccountForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.user = request.user
            obj.save()
            messages.success(request, "Integração criada.")
            return redirect("adsmanager:accounts")
        messages.error(request, "Corrija os erros do formulário.")
    else:
        form = AdsAccountForm()

    return render(request, "adsmanager/accounts/form.html", {"form": form})


@login_required
def account_edit(request: HttpRequest, account_id: int) -> HttpResponse:
    """
    Template: adsmanager/accounts/form.html
    """
    account = get_object_or_404(AdsAccount, pk=account_id, user=request.user)
    if request.method == "POST":
        form = AdsAccountForm(request.POST, instance=account)
        if form.is_valid():
            form.save()
            messages.success(request, "Integração atualizada.")
            return redirect("adsmanager:accounts")
        messages.error(request, "Corrija os erros do formulário.")
    else:
        form = AdsAccountForm(instance=account)

    return render(request, "adsmanager/accounts/form.html", {"form": form, "account": account})


@login_required
def account_sync(request: HttpRequest, account_id: int) -> HttpResponse:
    """
    Sync campaigns from platform. (Use button POST in HTML)
    """
    account = get_object_or_404(AdsAccount, pk=account_id, user=request.user)
    orchestrator = AdsOrchestrator(request.user)

    try:
        synced = orchestrator.sync_campaigns(account)
        messages.success(request, f"Sincronizado: {len(synced)} campanha(s).")
    except Exception as e:
        messages.error(request, f"Falha ao sincronizar: {e}")

    return redirect("adsmanager:accounts")


@login_required
def campaign_list(request: HttpRequest) -> HttpResponse:
    campaigns = AdCampaign.objects.filter(account__user=request.user).select_related("account").order_by("-updated_at")
    return render(request, "adsmanager/campaigns/list.html", {"campaigns": campaigns})


@login_required
def campaign_detail(request: HttpRequest, campaign_id: int) -> HttpResponse:
    """
    Template: adsmanager/campaigns/detail.html
    """
    campaign = get_object_or_404(AdCampaign, pk=campaign_id, account__user=request.user)
    runs = campaign.runs.order_by("-started_at")[:20]
    schedules = campaign.schedules.order_by("-active", "next_run")

    ctx = {
        "campaign": campaign,
        "runs": runs,
        "schedules": schedules,
        "rule": getattr(campaign, "rule", None),
        "metrics": campaign.metrics.order_by("-date")[:14],
    }
    return render(request, "adsmanager/campaigns/detail.html", ctx)


@login_required
def campaign_create(request: HttpRequest) -> HttpResponse:
    """
    Template: adsmanager/campaigns/create.html
    """
    orchestrator = AdsOrchestrator(request.user)

    if request.method == "POST":
        form = CampaignCreateForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                account = form.cleaned_data["account"]
                camp = orchestrator.create_campaign_from_form(account=account, cleaned=form.cleaned_data)
                messages.success(request, "Campanha criada (PAUSADA por segurança).")
                return redirect("adsmanager:campaign_detail", campaign_id=camp.id)
            except Exception as e:
                messages.error(request, f"Falha ao criar campanha: {e}")
        else:
            messages.error(request, "Corrija os erros do formulário.")
    else:
        form = CampaignCreateForm(user=request.user)

    return render(request, "adsmanager/campaigns/create.html", {"form": form})


@login_required
def campaign_optimize(request: HttpRequest, campaign_id: int) -> HttpResponse:
    """
    POST-only in UI. Runs an optimisation pass.
    """
    campaign = get_object_or_404(AdCampaign, pk=campaign_id, account__user=request.user)
    orchestrator = AdsOrchestrator(request.user)

    try:
        result = orchestrator.optimise(campaign)
        if result.get("status") == "ok":
            messages.success(request, "Otimização executada.")
        else:
            messages.info(request, f"Otimização ignorada: {result.get('reason')}")
    except Exception as e:
        messages.error(request, f"Falha na otimização: {e}")

    return redirect("adsmanager:campaign_detail", campaign_id=campaign.id)


@login_required
def campaign_sync_metrics(request: HttpRequest, campaign_id: int) -> HttpResponse:
    """
    POST-only. Sync last 7 days metrics.
    """
    campaign = get_object_or_404(AdCampaign, pk=campaign_id, account__user=request.user)
    orchestrator = AdsOrchestrator(request.user)

    try:
        end = timezone.now().date()
        start = end - timedelta(days=7)
        orchestrator.sync_metrics(campaign, start, end)
        messages.success(request, "Métricas sincronizadas (últimos 7 dias).")
    except Exception as e:
        messages.error(request, f"Falha ao sincronizar métricas: {e}")

    return redirect("adsmanager:campaign_detail", campaign_id=campaign.id)


@login_required
def campaign_duplicate(request: HttpRequest, campaign_id: int) -> HttpResponse:
    """
    POST-only. Implemented for Meta Ads (deep copy via /copies).
    """
    campaign = get_object_or_404(AdCampaign, pk=campaign_id, account__user=request.user)
    if campaign.account.platform != AdsAccount.PLATFORM_META_ADS:
        messages.info(request, "Duplicação automática disponível por enquanto apenas para Meta Ads.")
        return redirect("adsmanager:campaign_detail", campaign_id=campaign.id)

    orchestrator = AdsOrchestrator(request.user)
    run = AutomationRun.objects.create(user=request.user, campaign=campaign, run_type=AutomationRun.TYPE_DUPLICATE)

    try:
        client = orchestrator._meta_client(campaign.account)  # internal
        resp = client.duplicate_campaign(campaign.platform_campaign_id, deep_copy=True)
        run.payload = {"meta_response": resp}
        run.summary = "Cópia solicitada no Meta."
        run.finished_at = timezone.now()
        run.save(update_fields=["payload", "summary", "finished_at"])
        messages.success(request, "Cópia criada no Meta (pode levar alguns segundos para aparecer).")
    except Exception as e:
        run.status = AutomationRun.STATUS_FAILED
        run.error = str(e)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "finished_at"])
        messages.error(request, f"Falha ao duplicar: {e}")

    return redirect("adsmanager:campaign_detail", campaign_id=campaign.id)


@login_required
def campaign_rule_edit(request: HttpRequest, campaign_id: int) -> HttpResponse:
    """
    Template: adsmanager/campaigns/rule_form.html
    """
    campaign = get_object_or_404(AdCampaign, pk=campaign_id, account__user=request.user)
    rule, _ = AutomationRule.objects.get_or_create(campaign=campaign)

    if request.method == "POST":
        form = AutomationRuleForm(request.POST, instance=rule)
        if form.is_valid():
            form.save()
            messages.success(request, "Regra salva.")
            return redirect("adsmanager:campaign_detail", campaign_id=campaign.id)
        messages.error(request, "Corrija os erros do formulário.")
    else:
        form = AutomationRuleForm(instance=rule)

    return render(request, "adsmanager/campaigns/rule_form.html", {"form": form, "campaign": campaign})


@login_required
def campaign_schedule_edit(request: HttpRequest, campaign_id: int) -> HttpResponse:
    """
    Template: adsmanager/campaigns/schedule_form.html
    """
    campaign = get_object_or_404(AdCampaign, pk=campaign_id, account__user=request.user)
    schedule, _ = AdSchedule.objects.get_or_create(campaign=campaign)

    if request.method == "POST":
        form = AdScheduleForm(request.POST, instance=schedule)
        if form.is_valid():
            obj = form.save(commit=False)
            if obj.active and (obj.next_run is None or obj.next_run < timezone.now()):
                obj.next_run = timezone.now() + timedelta(minutes=int(obj.interval_minutes))
            obj.save()
            messages.success(request, "Agendamento salvo.")
            return redirect("adsmanager:campaign_detail", campaign_id=campaign.id)
        messages.error(request, "Corrija os erros do formulário.")
    else:
        form = AdScheduleForm(instance=schedule)

    return render(request, "adsmanager/campaigns/schedule_form.html", {"form": form, "campaign": campaign})


@login_required
def creative_list(request: HttpRequest) -> HttpResponse:
    creatives = AdCreative.objects.filter(account__user=request.user).select_related("account").order_by("-updated_at")
    return render(request, "adsmanager/creatives/list.html", {"creatives": creatives})


@login_required
def creative_create(request: HttpRequest) -> HttpResponse:
    """
    Template: adsmanager/creatives/form.html
    """
    if request.method == "POST":
        form = AdCreativeForm(request.POST, request.FILES)
        if form.is_valid():
            creative = form.save(commit=False)

            account = AdsAccount.objects.filter(user=request.user, active=True).exclude(platform=AdsAccount.PLATFORM_ANALYTICS).first()
            if not account:
                messages.error(request, "Crie uma integração (Google/Meta) antes de criar criativos.")
                return redirect("adsmanager:creative_create")

            creative.account = account
            creative.save()

            if form.cleaned_data.get("generate_ai_variations"):
                try:
                    variations = ai_generate_ad_variations(user=request.user, base_text=creative.base_text, n=4)
                    if variations:
                        creative.generated_text = "\n\n".join(f"- {v}" for v in variations)
                        creative.save(update_fields=["generated_text", "updated_at"])
                except Exception as e:
                    messages.warning(request, f"Não foi possível gerar variações com IA: {e}")

            messages.success(request, "Criativo salvo.")
            return redirect("adsmanager:creatives")
        messages.error(request, "Corrija os erros do formulário.")
    else:
        form = AdCreativeForm()

    return render(request, "adsmanager/creatives/form.html", {"form": form})
