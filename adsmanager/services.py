from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from .models import (
    AdsAccount,
    AdCampaign,
    AutomationRule,
    AutomationRun,
    CampaignMetricSnapshot,
    UserAdsSettings,
    AIUsageLog,
    currency_to_micros,
    micros_to_currency,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Utilities
# =============================================================================

def utc_today() -> date:
    return timezone.now().date()


def daterange(start: date, end: date) -> Iterable[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def clamp_int(x: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, x))


def safe_div(n: Decimal, d: Decimal) -> Decimal:
    if d == 0:
        return Decimal("0")
    return n / d


def estimate_tokens_from_chars(n_chars: int) -> int:
    # Rough: ~4 chars per token.
    return int(math.ceil(n_chars / 4))


class BudgetGuardError(Exception):
    pass


@dataclass
class GuardrailContext:
    user_settings: UserAdsSettings
    account: AdsAccount
    campaign: Optional[AdCampaign] = None


class BudgetGuard:
    """
    Enforces spend guardrails for:
      - user global caps
      - account caps
      - campaign caps

    This does NOT replace platform-enforced constraints and is only as good as
    the metric snapshots you sync in.
    """

    def __init__(self, ctx: GuardrailContext):
        self.ctx = ctx

    def _month_range(self, today: date) -> Tuple[date, date]:
        start = today.replace(day=1)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month - timedelta(days=1)
        return start, end

    def spent_today_micros(self, today: Optional[date] = None) -> int:
        today = today or utc_today()
        qs = CampaignMetricSnapshot.objects.filter(
            campaign__account=self.ctx.account,
            date=today,
        )
        if self.ctx.campaign:
            qs = qs.filter(campaign=self.ctx.campaign)
        return int(qs.aggregate(models_sum=models.Sum("cost_micros"))["models_sum"] or 0)

    def spent_month_micros(self, today: Optional[date] = None) -> int:
        today = today or utc_today()
        start, end = self._month_range(today)
        qs = CampaignMetricSnapshot.objects.filter(
            campaign__account=self.ctx.account,
            date__gte=start,
            date__lte=end,
        )
        if self.ctx.campaign:
            qs = qs.filter(campaign=self.ctx.campaign)
        return int(qs.aggregate(models_sum=models.Sum("cost_micros"))["models_sum"] or 0)

    def assert_can_increase_budget(self, add_micros: int) -> None:
        if add_micros <= 0:
            return

        today = utc_today()
        spent_today = self.spent_today_micros(today)
        spent_month = self.spent_month_micros(today)

        def check_cap(cap: Optional[int], spent: int, add: int, label: str):
            if cap is None:
                return
            if spent + add > cap:
                raise BudgetGuardError(
                    f"Bloqueado por teto {label}. Gasto atual={micros_to_currency(spent)} "
                    f"+ aumento={micros_to_currency(add)} > teto={micros_to_currency(cap)}"
                )

        us = self.ctx.user_settings
        acc = self.ctx.account
        camp = self.ctx.campaign

        check_cap(us.global_daily_spend_cap_micros, spent_today, add_micros, "diário (usuário)")
        check_cap(us.global_monthly_spend_cap_micros, spent_month, add_micros, "mensal (usuário)")

        check_cap(acc.spend_cap_daily_micros, spent_today, add_micros, "diário (conta)")
        check_cap(acc.spend_cap_monthly_micros, spent_month, add_micros, "mensal (conta)")

        if camp:
            check_cap(camp.spend_cap_daily_micros, 0, add_micros, "diário (campanha)")
            check_cap(camp.spend_cap_monthly_micros, 0, add_micros, "mensal (campanha)")


# =============================================================================
# AI wrapper (Gemini) – optional
# =============================================================================

class AIQuotaError(Exception):
    pass


class GeminiClientWrapper:
    """
    Thin wrapper around Gemini SDK if available.
    """

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

        try:
            import google.generativeai as genai  # type: ignore
        except Exception as e:
            raise ImportError(
                "Instale `google-generativeai` para usar Gemini: pip install google-generativeai"
            ) from e

        genai.configure(api_key=api_key)
        self._genai = genai

    def generate_text(self, prompt: str, temperature: float = 0.4) -> str:
        mdl = self._genai.GenerativeModel(self.model)
        resp = mdl.generate_content(
            prompt,
            generation_config={"temperature": temperature},
        )
        return (getattr(resp, "text", None) or "").strip()


def get_user_ads_settings(user) -> UserAdsSettings:
    obj, _ = UserAdsSettings.objects.get_or_create(user=user)
    return obj


def check_ai_quota(user_settings: UserAdsSettings, user) -> None:
    today = utc_today()
    start_of_month = today.replace(day=1)

    daily = AIUsageLog.objects.filter(user=user, created_at__date=today).aggregate(s=models.Sum("cost_est_usd"))["s"] or Decimal("0")
    monthly = AIUsageLog.objects.filter(user=user, created_at__date__gte=start_of_month).aggregate(s=models.Sum("cost_est_usd"))["s"] or Decimal("0")

    if user_settings.ai_daily_limit_usd is not None and daily >= user_settings.ai_daily_limit_usd:
        raise AIQuotaError("Limite diário de IA atingido.")
    if user_settings.ai_monthly_limit_usd is not None and monthly >= user_settings.ai_monthly_limit_usd:
        raise AIQuotaError("Limite mensal de IA atingido.")


def ai_generate_ad_variations(
    *,
    user,
    base_text: str,
    goal: str = "vender mais com orçamento baixo",
    n: int = 4,
    temperature: float = 0.4,
) -> List[str]:
    us = get_user_ads_settings(user)
    if not us.ai_enabled:
        return []

    check_ai_quota(us, user)

    api_key = getattr(settings, "GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("Defina GEMINI_API_KEY no settings.py para usar IA.")

    client = GeminiClientWrapper(api_key=api_key, model=us.ai_model)

    prompt = (
        "Você é um gestor de tráfego sênior. Gere variações curtas e objetivas de copy "
        "para anúncio (Meta/Google), focadas em conversão e eficiência.\n\n"
        f"Objetivo: {goal}\n"
        "Regras:\n"
        "- Não invente informações.\n"
        "- Use linguagem simples.\n"
        "- Se possível, inclua CTA.\n"
        f"- Gere {n} variações numeradas.\n\n"
        f"Texto base:\n{base_text}\n"
    )
    text = client.generate_text(prompt, temperature=temperature)

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    variations: List[str] = []
    for ln in lines:
        if ln[0].isdigit():
            parts = ln.split(".", 1)
            if len(parts) == 2:
                variations.append(parts[1].strip())
            else:
                variations.append(ln)
        else:
            variations.append(ln)

    variations = [v for v in variations if len(v) >= 10][:n]

    in_chars = len(prompt)
    out_chars = len(text)
    tokens_est = estimate_tokens_from_chars(in_chars + out_chars)

    cost_est = Decimal("0.0")  # configure later if you want real estimates

    AIUsageLog.objects.create(
        user=user,
        provider=us.ai_provider,
        model=us.ai_model,
        purpose=AIUsageLog.PURPOSE_COPY,
        input_chars=in_chars,
        output_chars=out_chars,
        tokens_est=tokens_est,
        cost_est_usd=cost_est,
    )

    return variations


# =============================================================================
# Google Ads API wrapper
# =============================================================================

@dataclass
class GoogleAdsCredentials:
    developer_token: str
    client_id: str
    client_secret: str
    refresh_token: str
    customer_id: str
    login_customer_id: Optional[str] = None


class GoogleAdsClientWrapper:
    """
    Wrapper around the official `google-ads` Python library.
    """

    def __init__(self, creds: GoogleAdsCredentials):
        self.creds = creds
        try:
            from google.ads.googleads.client import GoogleAdsClient  # type: ignore
        except Exception as e:
            raise ImportError(
                "Instale `google-ads` para integração com Google Ads API: pip install google-ads"
            ) from e

        config = {
            "developer_token": creds.developer_token,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "refresh_token": creds.refresh_token,
            "use_proto_plus": True,
        }
        if creds.login_customer_id:
            config["login_customer_id"] = creds.login_customer_id

        self.client = GoogleAdsClient.load_from_dict(config)
        self.customer_id = creds.customer_id

    def _service(self, name: str):
        return self.client.get_service(name)

    def list_campaigns(self, limit: int = 50) -> List[Dict[str, Any]]:
        ga_service = self._service("GoogleAdsService")
        query = f"""
            SELECT
              campaign.id,
              campaign.name,
              campaign.status,
              campaign.advertising_channel_type,
              campaign.campaign_budget,
              campaign_budget.amount_micros,
              campaign_budget.resource_name
            FROM campaign
            ORDER BY campaign.id DESC
            LIMIT {int(limit)}
        """
        resp = ga_service.search(customer_id=self.customer_id, query=query)
        out: List[Dict[str, Any]] = []
        for row in resp:
            out.append({
                "id": str(row.campaign.id),
                "name": row.campaign.name,
                "status": row.campaign.status.name if hasattr(row.campaign.status, "name") else str(row.campaign.status),
                "channel": row.campaign.advertising_channel_type.name if hasattr(row.campaign.advertising_channel_type, "name") else str(row.campaign.advertising_channel_type),
                "budget_micros": int(getattr(row.campaign_budget, "amount_micros", 0) or 0),
                "budget_resource_name": getattr(row.campaign_budget, "resource_name", "") or "",
            })
        return out

    def campaign_metrics(self, campaign_id: str, start: date, end: date) -> Dict[str, Any]:
        ga_service = self._service("GoogleAdsService")
        query = f"""
            SELECT
              campaign.id,
              metrics.impressions,
              metrics.clicks,
              metrics.cost_micros,
              metrics.conversions,
              metrics.conversions_value
            FROM campaign
            WHERE campaign.id = {int(campaign_id)}
              AND segments.date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'
        """
        resp = ga_service.search(customer_id=self.customer_id, query=query)

        impressions = clicks = cost_micros = 0
        conversions = Decimal("0")
        conv_value_units = Decimal("0")

        for row in resp:
            impressions += int(getattr(row.metrics, "impressions", 0) or 0)
            clicks += int(getattr(row.metrics, "clicks", 0) or 0)
            cost_micros += int(getattr(row.metrics, "cost_micros", 0) or 0)
            conversions += Decimal(str(getattr(row.metrics, "conversions", 0) or 0))
            conv_value_units += Decimal(str(getattr(row.metrics, "conversions_value", 0) or 0))

        return {
            "impressions": impressions,
            "clicks": clicks,
            "cost_micros": cost_micros,
            "conversions": conversions,
            "conversion_value_micros": currency_to_micros(conv_value_units),
        }

    def set_campaign_status(self, campaign_id: str, status: str) -> None:
        from google.protobuf import field_mask_pb2  # type: ignore

        campaign_service = self._service("CampaignService")
        operation = self.client.get_type("CampaignOperation")
        campaign = operation.update
        campaign.resource_name = campaign_service.campaign_path(self.customer_id, campaign_id)
        campaign.status = self.client.enums.CampaignStatusEnum.CampaignStatus[status]

        operation.update_mask.CopyFrom(field_mask_pb2.FieldMask(paths=["status"]))
        campaign_service.mutate_campaigns(customer_id=self.customer_id, operations=[operation])

    def update_campaign_budget(self, budget_resource_name: str, new_amount_micros: int) -> None:
        from google.protobuf import field_mask_pb2  # type: ignore

        budget_service = self._service("CampaignBudgetService")
        op = self.client.get_type("CampaignBudgetOperation")
        budget = op.update
        budget.resource_name = budget_resource_name
        budget.amount_micros = int(new_amount_micros)

        op.update_mask.CopyFrom(field_mask_pb2.FieldMask(paths=["amount_micros"]))
        budget_service.mutate_campaign_budgets(customer_id=self.customer_id, operations=[op])

    def create_campaign(self, *, name: str, daily_budget_micros: int, channel_type: str = "SEARCH") -> Dict[str, str]:
        budget_service = self._service("CampaignBudgetService")
        campaign_service = self._service("CampaignService")

        budget_op = self.client.get_type("CampaignBudgetOperation")
        budget = budget_op.create
        budget.name = f"{name} - Budget"
        budget.delivery_method = self.client.enums.BudgetDeliveryMethodEnum.BudgetDeliveryMethod.STANDARD
        budget.amount_micros = int(daily_budget_micros)

        budget_resp = budget_service.mutate_campaign_budgets(customer_id=self.customer_id, operations=[budget_op])
        budget_resource_name = budget_resp.results[0].resource_name

        camp_op = self.client.get_type("CampaignOperation")
        camp = camp_op.create
        camp.name = name
        camp.campaign_budget = budget_resource_name
        camp.status = self.client.enums.CampaignStatusEnum.CampaignStatus.PAUSED
        camp.advertising_channel_type = self.client.enums.AdvertisingChannelTypeEnum.AdvertisingChannelType[channel_type]

        camp_resp = campaign_service.mutate_campaigns(customer_id=self.customer_id, operations=[camp_op])
        campaign_resource_name = camp_resp.results[0].resource_name
        campaign_id = campaign_resource_name.split("/")[-1]

        return {
            "campaign_id": campaign_id,
            "campaign_resource_name": campaign_resource_name,
            "budget_resource_name": budget_resource_name,
        }


# =============================================================================
# Meta Marketing API wrapper
# =============================================================================

class MetaAdsClientWrapper:
    """
    Wrapper around Meta Marketing API (Graph API).
    """

    def __init__(self, access_token: str, ad_account_id: str, version: Optional[str] = None):
        self.access_token = access_token
        self.ad_account_id = ad_account_id.replace("act_", "")
        self.version = version or getattr(settings, "META_GRAPH_VERSION", "v24.0")
        self.base_url = f"https://graph.facebook.com/{self.version}"

    def _req(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        params = params or {}
        params["access_token"] = self.access_token

        for attempt in range(1, 4):
            try:
                resp = requests.request(method, url, params=params, json=json_body, timeout=30)
                data = resp.json() if resp.content else {}
                if resp.status_code >= 400:
                    err = data.get("error") or {}
                    raise RuntimeError(f"Meta API error ({resp.status_code}): {err.get('message') or data}")
                return data
            except Exception as e:
                if attempt == 3:
                    raise
                logger.warning("Meta request failed (attempt %s): %s", attempt, e)
                time.sleep(0.6 * attempt)
        return {}

    def list_campaigns(self, limit: int = 50) -> List[Dict[str, Any]]:
        fields = "id,name,status,objective,created_time,updated_time"
        data = self._req("GET", f"/act_{self.ad_account_id}/campaigns", params={"fields": fields, "limit": limit})
        return data.get("data", []) or []

    def campaign_insights(self, campaign_id: str, start: date, end: date) -> Dict[str, Any]:
        fields = "impressions,clicks,spend,actions,action_values"
        params = {
            "fields": fields,
            "time_range": json.dumps({"since": start.isoformat(), "until": end.isoformat()}),
            "level": "campaign",
        }
        data = self._req("GET", f"/{campaign_id}/insights", params=params)
        rows = data.get("data", []) or []
        if not rows:
            return {"impressions": 0, "clicks": 0, "cost_micros": 0, "conversions": Decimal("0"), "conversion_value_micros": 0}

        row = rows[0]
        impressions = int(row.get("impressions") or 0)
        clicks = int(row.get("clicks") or 0)
        spend_units = Decimal(str(row.get("spend") or "0"))
        cost_micros = currency_to_micros(spend_units)

        conversions = Decimal("0")
        conversion_value_units = Decimal("0")
        actions = row.get("actions") or []
        action_values = row.get("action_values") or []

        preferred_actions = {"purchase", "lead", "complete_registration"}

        for a in actions:
            try:
                if a.get("action_type") in preferred_actions:
                    conversions += Decimal(str(a.get("value") or "0"))
            except Exception:
                continue

        for av in action_values:
            try:
                if av.get("action_type") == "purchase":
                    conversion_value_units += Decimal(str(av.get("value") or "0"))
            except Exception:
                continue

        return {
            "impressions": impressions,
            "clicks": clicks,
            "cost_micros": cost_micros,
            "conversions": conversions,
            "conversion_value_micros": currency_to_micros(conversion_value_units),
        }

    def update_adset_budget_minor_units(self, adset_id: str, *, daily_budget_minor_units: int) -> Dict[str, Any]:
        return self._req("POST", f"/{adset_id}", params={"daily_budget": str(int(daily_budget_minor_units))})

    def duplicate_campaign(self, campaign_id: str, *, deep_copy: bool = True, rename_suffix: str = " (Cópia)") -> Dict[str, Any]:
        params = {
            "deep_copy": "true" if deep_copy else "false",
            "rename_options": json.dumps({"rename_suffix": rename_suffix}),
        }
        return self._req("POST", f"/{campaign_id}/copies", params=params)

    def create_campaign(self, *, name: str, objective: str = "OUTCOME_LEADS", status: str = "PAUSED") -> Dict[str, Any]:
        params = {"name": name, "objective": objective, "status": status}
        return self._req("POST", f"/act_{self.ad_account_id}/campaigns", params=params)

    def create_adset(
        self,
        *,
        name: str,
        campaign_id: str,
        daily_budget_minor_units: int,
        billing_event: str = "IMPRESSIONS",
        optimization_goal: str = "LEAD_GENERATION",
        status: str = "PAUSED",
        targeting: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "name": name,
            "campaign_id": campaign_id,
            "daily_budget": str(int(daily_budget_minor_units)),
            "billing_event": billing_event,
            "optimization_goal": optimization_goal,
            "status": status,
        }
        if targeting:
            params["targeting"] = json.dumps(targeting)
        return self._req("POST", f"/act_{self.ad_account_id}/adsets", params=params)

    def create_adcreative(self, *, name: str, object_story_spec: Dict[str, Any]) -> Dict[str, Any]:
        params = {"name": name, "object_story_spec": json.dumps(object_story_spec)}
        return self._req("POST", f"/act_{self.ad_account_id}/adcreatives", params=params)

    def create_ad(self, *, name: str, adset_id: str, creative_id: str, status: str = "PAUSED") -> Dict[str, Any]:
        params = {"name": name, "adset_id": adset_id, "creative": json.dumps({"creative_id": creative_id}), "status": status}
        return self._req("POST", f"/act_{self.ad_account_id}/ads", params=params)


# =============================================================================
# Orchestrator: sync + metrics + optimise + create
# =============================================================================

@dataclass
class Metrics:
    impressions: int = 0
    clicks: int = 0
    cost_micros: int = 0
    conversions: Decimal = Decimal("0")
    conversion_value_micros: int = 0

    @property
    def ctr(self) -> Decimal:
        return safe_div(Decimal(self.clicks), Decimal(self.impressions))

    @property
    def cpc_micros(self) -> int:
        if self.clicks <= 0:
            return 0
        return int(Decimal(self.cost_micros) / Decimal(self.clicks))

    @property
    def cpa_micros(self) -> int:
        if self.conversions <= 0:
            return 0
        return int(Decimal(self.cost_micros) / Decimal(self.conversions))

    @property
    def roas(self) -> Decimal:
        if self.cost_micros <= 0:
            return Decimal("0")
        return safe_div(Decimal(self.conversion_value_micros), Decimal(self.cost_micros))


class AdsOrchestrator:
    def __init__(self, user):
        self.user = user
        self.user_settings = get_user_ads_settings(user)

    def _google_client(self, account: AdsAccount) -> GoogleAdsClientWrapper:
        c = account.credentials or {}
        creds = GoogleAdsCredentials(
            developer_token=c.get("developer_token", ""),
            client_id=c.get("client_id", ""),
            client_secret=c.get("client_secret", ""),
            refresh_token=c.get("refresh_token", ""),
            customer_id=str(c.get("customer_id") or account.platform_account_id or ""),
            login_customer_id=c.get("login_customer_id"),
        )
        return GoogleAdsClientWrapper(creds)

    def _meta_client(self, account: AdsAccount) -> MetaAdsClientWrapper:
        c = account.credentials or {}
        access_token = c.get("access_token", "")
        ad_account_id = str(c.get("ad_account_id") or account.platform_account_id or "")
        return MetaAdsClientWrapper(access_token=access_token, ad_account_id=ad_account_id)

    def sync_campaigns(self, account: AdsAccount, limit: int = 50) -> List[AdCampaign]:
        run = AutomationRun.objects.create(
            user=self.user,
            run_type=AutomationRun.TYPE_SYNC,
            status=AutomationRun.STATUS_SUCCESS,
            payload={"account_id": account.id, "platform": account.platform},
        )

        try:
            if account.platform == AdsAccount.PLATFORM_GOOGLE_ADS:
                remote = self._google_client(account).list_campaigns(limit=limit)
                synced = self._upsert_google_campaigns(account, remote)
            elif account.platform == AdsAccount.PLATFORM_META_ADS:
                remote = self._meta_client(account).list_campaigns(limit=limit)
                synced = self._upsert_meta_campaigns(account, remote)
            else:
                synced = []

            run.summary = f"Sincronizadas {len(synced)} campanhas."
            run.finished_at = timezone.now()
            run.save(update_fields=["summary", "finished_at"])
            return synced

        except Exception as e:
            run.status = AutomationRun.STATUS_FAILED
            run.error = str(e)
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "error", "finished_at"])
            raise

    def _upsert_google_campaigns(self, account: AdsAccount, remote: List[Dict[str, Any]]) -> List[AdCampaign]:
        synced: List[AdCampaign] = []
        now = timezone.now()

        for r in remote:
            camp, _ = AdCampaign.objects.update_or_create(
                account=account,
                platform_campaign_id=str(r["id"]),
                defaults={
                    "name": r.get("name") or f"Campaign {r['id']}",
                    "status": r.get("status") or "UNKNOWN",
                    "objective": r.get("channel"),
                    "budget_type": AdCampaign.BUDGET_DAILY,
                    "budget_micros": int(r.get("budget_micros") or 0) or None,
                    "platform_budget_ref": r.get("budget_resource_name") or None,
                    "last_synced_at": now,
                    "economic_mode": self.user_settings.default_economic_mode,
                },
            )
            synced.append(camp)
        return synced

    def _upsert_meta_campaigns(self, account: AdsAccount, remote: List[Dict[str, Any]]) -> List[AdCampaign]:
        synced: List[AdCampaign] = []
        now = timezone.now()

        for r in remote:
            camp, _ = AdCampaign.objects.update_or_create(
                account=account,
                platform_campaign_id=str(r.get("id")),
                defaults={
                    "name": r.get("name") or f"Campaign {r.get('id')}",
                    "status": r.get("status") or "UNKNOWN",
                    "objective": r.get("objective"),
                    "budget_type": AdCampaign.BUDGET_UNKNOWN,
                    "budget_micros": None,
                    "last_synced_at": now,
                    "economic_mode": self.user_settings.default_economic_mode,
                },
            )
            synced.append(camp)
        return synced

    def get_metrics(self, campaign: AdCampaign, start: date, end: date) -> Metrics:
        if campaign.account.platform == AdsAccount.PLATFORM_GOOGLE_ADS:
            data = self._google_client(campaign.account).campaign_metrics(campaign.platform_campaign_id, start, end)
        else:
            data = self._meta_client(campaign.account).campaign_insights(campaign.platform_campaign_id, start, end)

        return Metrics(
            impressions=int(data.get("impressions") or 0),
            clicks=int(data.get("clicks") or 0),
            cost_micros=int(data.get("cost_micros") or 0),
            conversions=Decimal(str(data.get("conversions") or "0")),
            conversion_value_micros=int(data.get("conversion_value_micros") or 0),
        )

    def sync_metrics(self, campaign: AdCampaign, start: date, end: date) -> List[CampaignMetricSnapshot]:
        run = AutomationRun.objects.create(
            user=self.user,
            campaign=campaign,
            run_type=AutomationRun.TYPE_SYNC,
            status=AutomationRun.STATUS_SUCCESS,
            payload={"campaign_id": campaign.id, "start": start.isoformat(), "end": end.isoformat()},
        )

        try:
            m = self.get_metrics(campaign, start=start, end=end)
            source = CampaignMetricSnapshot.SOURCE_GOOGLE if campaign.account.platform == AdsAccount.PLATFORM_GOOGLE_ADS else CampaignMetricSnapshot.SOURCE_META

            snap, _ = CampaignMetricSnapshot.objects.update_or_create(
                campaign=campaign,
                date=end,
                source=source,
                defaults={
                    "impressions": m.impressions,
                    "clicks": m.clicks,
                    "cost_micros": m.cost_micros,
                    "conversions": m.conversions,
                    "conversion_value_micros": m.conversion_value_micros,
                },
            )
            run.summary = "Métricas sincronizadas."
            run.finished_at = timezone.now()
            run.save(update_fields=["summary", "finished_at"])
            return [snap]
        except Exception as e:
            run.status = AutomationRun.STATUS_FAILED
            run.error = str(e)
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "error", "finished_at"])
            raise

    def optimise(self, campaign: AdCampaign, *, start: Optional[date] = None, end: Optional[date] = None) -> Dict[str, Any]:
        if not self.user_settings.allow_auto_optimize:
            return {"status": "skipped", "reason": "Auto-optimize desativado pelo usuário."}

        start = start or (utc_today() - timedelta(days=7))
        end = end or utc_today()

        run = AutomationRun.objects.create(
            user=self.user,
            campaign=campaign,
            run_type=AutomationRun.TYPE_OPTIMIZE,
            status=AutomationRun.STATUS_SUCCESS,
            payload={"start": start.isoformat(), "end": end.isoformat()},
        )

        try:
            rule = getattr(campaign, "rule", None)
            if rule is None:
                rule = AutomationRule.objects.create(campaign=campaign)

            if not rule.active:
                run.status = AutomationRun.STATUS_SKIPPED
                run.summary = "Regra desativada."
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "summary", "finished_at"])
                return {"status": "skipped", "reason": "Rule disabled"}

            metrics = self.get_metrics(campaign, start, end)
            self.sync_metrics(campaign, start, end)

            actions: List[Dict[str, Any]] = []
            reason: List[str] = []

            if metrics.clicks < rule.min_clicks:
                return {"status": "skipped", "reason": f"Poucos cliques ({metrics.clicks} < {rule.min_clicks})."}

            cpa_micros = metrics.cpa_micros
            roas = metrics.roas

            scale = 0
            if rule.max_cpa_micros and cpa_micros and cpa_micros > rule.max_cpa_micros:
                scale = -rule.scale_down_pct
                reason.append(f"CPA alto: {micros_to_currency(cpa_micros)} > {micros_to_currency(rule.max_cpa_micros)}")
            elif rule.min_roas and roas and roas < rule.min_roas:
                scale = -rule.scale_down_pct
                reason.append(f"ROAS baixo: {roas:.2f} < {rule.min_roas:.2f}")
            else:
                scale = rule.scale_up_pct
                reason.append("Indicadores OK: escala leve para cima.")

            if campaign.economic_mode or self.user_settings.default_economic_mode:
                scale = int(Decimal(scale) * Decimal("0.6"))
                if scale == 0:
                    scale = 5 if scale >= 0 else -5

            if campaign.budget_micros:
                new_budget = int(Decimal(campaign.budget_micros) * (Decimal("1") + (Decimal(scale) / Decimal("100"))))
                delta = max(0, new_budget - int(campaign.budget_micros))

                if scale > 0:
                    max_up = clamp_int(rule.max_scale_up_pct_per_day, 1, 200)
                    max_budget = int(Decimal(campaign.budget_micros) * (Decimal("1") + Decimal(max_up) / Decimal("100")))
                    new_budget = min(new_budget, max_budget)
                    delta = max(0, new_budget - int(campaign.budget_micros))

                guard = BudgetGuard(GuardrailContext(user_settings=self.user_settings, account=campaign.account, campaign=campaign))
                guard.assert_can_increase_budget(delta)

                actions.append({"type": "update_budget", "from_micros": campaign.budget_micros, "to_micros": new_budget})
            else:
                reason.append("Campanha sem budget conhecido (sincronize orçamento).")

            if self.user_settings.allow_auto_pause and metrics.conversions <= 0:
                lookback_days = int(rule.hard_pause_on_zero_conversions_days or 0)
                if lookback_days >= 3:
                    since = utc_today() - timedelta(days=lookback_days)
                    total_conv = CampaignMetricSnapshot.objects.filter(campaign=campaign, date__gte=since).aggregate(s=models.Sum("conversions"))["s"] or 0
                    if Decimal(str(total_conv)) <= 0:
                        actions.append({"type": "pause_campaign"})
                        reason.append(f"Zero conversões por {lookback_days} dias: pausar.")

            result = self.apply_actions(campaign, actions)

            run.summary = "; ".join(reason)[:240]
            run.payload = {**run.payload, "reason": reason, "actions": actions, "result": result}
            run.finished_at = timezone.now()
            run.save(update_fields=["summary", "payload", "finished_at"])
            return {"status": "ok", "reason": reason, "actions": actions, "result": result}

        except Exception as e:
            run.status = AutomationRun.STATUS_FAILED
            run.error = str(e)
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "error", "finished_at"])
            raise

    def apply_actions(self, campaign: AdCampaign, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not actions:
            return {"applied": 0, "details": []}

        details: List[Dict[str, Any]] = []
        account = campaign.account

        if account.platform == AdsAccount.PLATFORM_GOOGLE_ADS:
            client = self._google_client(account)
            for a in actions:
                if a["type"] == "update_budget":
                    if not campaign.platform_budget_ref:
                        raise RuntimeError("Google: budget ref ausente. Rode sync_campaigns para preencher.")
                    client.update_campaign_budget(campaign.platform_budget_ref, int(a["to_micros"]))
                    campaign.budget_micros = int(a["to_micros"])
                    campaign.save(update_fields=["budget_micros", "updated_at"])
                    details.append({"ok": True, "action": a})
                elif a["type"] == "pause_campaign":
                    client.set_campaign_status(campaign.platform_campaign_id, "PAUSED")
                    campaign.status = "PAUSED"
                    campaign.save(update_fields=["status", "updated_at"])
                    details.append({"ok": True, "action": a})

        elif account.platform == AdsAccount.PLATFORM_META_ADS:
            client = self._meta_client(account)
            for a in actions:
                if a["type"] == "update_budget":
                    if not campaign.platform_adset_id:
                        details.append({"ok": False, "action": a, "error": "Meta: adset_id ausente (implementar sync de adsets)."})
                        continue
                    minor_units = account.micros_to_minor_units(int(a["to_micros"]))
                    client.update_adset_budget_minor_units(campaign.platform_adset_id, daily_budget_minor_units=minor_units)
                    campaign.budget_micros = int(a["to_micros"])
                    campaign.save(update_fields=["budget_micros", "updated_at"])
                    details.append({"ok": True, "action": a})
                elif a["type"] == "pause_campaign":
                    client._req("POST", f"/{campaign.platform_campaign_id}", params={"status": "PAUSED"})
                    campaign.status = "PAUSED"
                    campaign.save(update_fields=["status", "updated_at"])
                    details.append({"ok": True, "action": a})

        return {"applied": len(details), "details": details}

    def create_campaign_from_form(self, *, account: AdsAccount, cleaned: Dict[str, Any]) -> AdCampaign:
        run = AutomationRun.objects.create(
            user=self.user,
            run_type=AutomationRun.TYPE_CREATE,
            status=AutomationRun.STATUS_SUCCESS,
            payload={"platform": account.platform, "name": cleaned.get("name")},
        )

        try:
            daily_budget_units: Decimal = cleaned["daily_budget"]
            daily_budget_micros = currency_to_micros(daily_budget_units)

            guard = BudgetGuard(GuardrailContext(user_settings=self.user_settings, account=account, campaign=None))
            guard.assert_can_increase_budget(int(daily_budget_micros))

            if account.platform == AdsAccount.PLATFORM_GOOGLE_ADS:
                client = self._google_client(account)
                created = client.create_campaign(
                    name=cleaned["name"],
                    daily_budget_micros=int(daily_budget_micros),
                    channel_type="SEARCH",
                )
                camp = AdCampaign.objects.create(
                    account=account,
                    platform_campaign_id=created["campaign_id"],
                    platform_budget_ref=created["budget_resource_name"],
                    name=cleaned["name"],
                    objective=cleaned.get("objective") or "SEARCH",
                    status="PAUSED",
                    budget_type=AdCampaign.BUDGET_DAILY,
                    budget_micros=int(daily_budget_micros),
                    economic_mode=bool(cleaned.get("economic_mode")),
                    last_synced_at=timezone.now(),
                )
            else:
                client = self._meta_client(account)
                created = client.create_campaign(
                    name=cleaned["name"],
                    objective=cleaned.get("objective") or "OUTCOME_LEADS",
                    status="PAUSED",
                )
                campaign_id = created.get("id")
                if not campaign_id:
                    raise RuntimeError(f"Meta: resposta inesperada: {created}")

                adset = client.create_adset(
                    name=f"{cleaned['name']} - Conjunto 1",
                    campaign_id=campaign_id,
                    daily_budget_minor_units=account.micros_to_minor_units(int(daily_budget_micros)),
                    status="PAUSED",
                )
                adset_id = adset.get("id")

                camp = AdCampaign.objects.create(
                    account=account,
                    platform_campaign_id=str(campaign_id),
                    platform_adset_id=str(adset_id) if adset_id else None,
                    name=cleaned["name"],
                    objective=cleaned.get("objective") or "OUTCOME_LEADS",
                    status="PAUSED",
                    budget_type=AdCampaign.BUDGET_DAILY,
                    budget_micros=int(daily_budget_micros),
                    economic_mode=bool(cleaned.get("economic_mode")),
                    last_synced_at=timezone.now(),
                )

            run.summary = f"Criada campanha: {camp.name}"
            run.campaign = camp
            run.finished_at = timezone.now()
            run.save(update_fields=["summary", "campaign", "finished_at"])
            return camp

        except Exception as e:
            run.status = AutomationRun.STATUS_FAILED
            run.error = str(e)
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "error", "finished_at"])
            raise
