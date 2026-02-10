from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


def currency_to_micros(amount) -> int:
    """
    Converte um valor monetário (ex.: 1.23) para micros (1 unidade = 1.000.000 micros).
    Aceita Decimal/int/float/str de forma segura.
    """
    if amount is None:
        return 0
    return int(Decimal(str(amount)) * Decimal("1000000"))


def micros_to_currency(micros: int) -> Decimal:
    if micros is None:
        return Decimal("0.00")
    return (Decimal(micros) / Decimal("1000000")).quantize(Decimal("0.01"))


class UserAdsSettings(models.Model):
    AI_PROVIDER_GEMINI = "gemini"
    AI_PROVIDER_CHOICES = [
        (AI_PROVIDER_GEMINI, "Gemini"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ads_settings")

    # IA
    ai_enabled = models.BooleanField(default=True)
    ai_provider = models.CharField(max_length=32, choices=AI_PROVIDER_CHOICES, default=AI_PROVIDER_GEMINI)
    ai_model = models.CharField(max_length=64, default="gemini-2.5-flash")
    ai_daily_limit_usd = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        default=Decimal("2.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    ai_monthly_limit_usd = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        default=Decimal("20.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )

    # Teto global de ads (micros, na moeda da conta)
    global_daily_spend_cap_micros = models.BigIntegerField(null=True, blank=True)
    global_monthly_spend_cap_micros = models.BigIntegerField(null=True, blank=True)

    # Automação
    allow_auto_sync = models.BooleanField(default=True)
    allow_auto_optimize = models.BooleanField(default=True)
    allow_auto_pause = models.BooleanField(default=True)
    allow_auto_duplicate = models.BooleanField(default=False)
    allow_auto_refresh_creatives = models.BooleanField(default=False)

    default_economic_mode = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuração do Usuário (Ads)"
        verbose_name_plural = "Configurações do Usuário (Ads)"

    def __str__(self) -> str:
        return f"Ads settings for {self.user}"


class AdsAccount(models.Model):
    PLATFORM_GOOGLE_ADS = "google_ads"
    PLATFORM_META_ADS = "meta_ads"
    PLATFORM_ANALYTICS = "analytics"
    PLATFORM_CHOICES = [
        (PLATFORM_GOOGLE_ADS, "Google Ads"),
        (PLATFORM_META_ADS, "Meta Ads"),
        (PLATFORM_ANALYTICS, "Analytics (GA4)"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ads_accounts")
    platform = models.CharField(max_length=32, choices=PLATFORM_CHOICES)
    name = models.CharField(max_length=255)

    platform_account_id = models.CharField(max_length=64, blank=True, null=True)

    currency_code = models.CharField(max_length=8, default="BRL")
    currency_minor_unit = models.PositiveSmallIntegerField(default=100)

    credentials = models.JSONField(default=dict, blank=True)

    spend_cap_daily_micros = models.BigIntegerField(null=True, blank=True)
    spend_cap_monthly_micros = models.BigIntegerField(null=True, blank=True)

    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "platform", "name")]
        verbose_name = "Conta de Anúncio"
        verbose_name_plural = "Contas de Anúncio"

    def __str__(self) -> str:
        return f"{self.name} ({self.get_platform_display()})"

    def micros_to_minor_units(self, micros: int) -> int:
        if micros is None:
            return 0
        return int(Decimal(micros) * Decimal(self.currency_minor_unit) / Decimal("1000000"))

    def minor_units_to_micros(self, minor_units: int) -> int:
        if minor_units is None:
            return 0
        return int(Decimal(minor_units) * Decimal("1000000") / Decimal(self.currency_minor_unit))


class AdCampaign(models.Model):
    BUDGET_DAILY = "daily"
    BUDGET_LIFETIME = "lifetime"
    BUDGET_UNKNOWN = "unknown"
    BUDGET_TYPE_CHOICES = [
        (BUDGET_DAILY, "Diário"),
        (BUDGET_LIFETIME, "Vitalício"),
        (BUDGET_UNKNOWN, "Indefinido"),
    ]

    account = models.ForeignKey(AdsAccount, on_delete=models.CASCADE, related_name="campaigns")
    platform_campaign_id = models.CharField(max_length=128)

    platform_budget_ref = models.CharField(max_length=255, blank=True, null=True)  # Google: resource_name do budget
    platform_adset_id = models.CharField(max_length=128, blank=True, null=True)   # Meta: budgets vivem no adset

    name = models.CharField(max_length=255)
    objective = models.CharField(max_length=128, blank=True, null=True)
    status = models.CharField(max_length=64, default="PAUSED")

    budget_type = models.CharField(max_length=16, choices=BUDGET_TYPE_CHOICES, default=BUDGET_UNKNOWN)
    budget_micros = models.BigIntegerField(null=True, blank=True)

    spend_cap_daily_micros = models.BigIntegerField(null=True, blank=True)
    spend_cap_monthly_micros = models.BigIntegerField(null=True, blank=True)

    economic_mode = models.BooleanField(default=False)

    last_synced_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Campanha"
        verbose_name_plural = "Campanhas"
        indexes = [
            models.Index(fields=["account", "platform_campaign_id"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return self.name


class AdCreative(models.Model):
    account = models.ForeignKey(AdsAccount, on_delete=models.CASCADE, related_name="creatives")

    name = models.CharField(max_length=255)
    base_text = models.TextField()
    image = models.ImageField(upload_to="adsmanager/images/", blank=True, null=True)

    headline = models.CharField(max_length=255, blank=True, null=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    destination_url = models.URLField(blank=True, null=True)

    generated_text = models.TextField(blank=True, null=True)

    meta_creative_id = models.CharField(max_length=128, blank=True, null=True)
    google_asset_resource_name = models.CharField(max_length=255, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Criativo"
        verbose_name_plural = "Criativos"

    def __str__(self) -> str:
        return self.name


class AdSchedule(models.Model):
    KIND_SYNC = "sync"
    KIND_OPTIMIZE = "optimize"
    KIND_CHOICES = [
        (KIND_SYNC, "Sincronizar"),
        (KIND_OPTIMIZE, "Otimizar"),
    ]

    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE, related_name="schedules")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_OPTIMIZE)

    interval_minutes = models.PositiveIntegerField(default=60)
    next_run = models.DateTimeField(default=timezone.now)
    last_run = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Agendamento"
        verbose_name_plural = "Agendamentos"
        indexes = [models.Index(fields=["active", "next_run"])]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} • {self.campaign.name} • {self.interval_minutes}m"


class AutomationRule(models.Model):
    campaign = models.OneToOneField(AdCampaign, on_delete=models.CASCADE, related_name="rule")
    active = models.BooleanField(default=True)

    min_clicks = models.PositiveIntegerField(default=30)
    min_conversions = models.PositiveIntegerField(default=1)

    max_cpa_micros = models.BigIntegerField(null=True, blank=True)
    min_roas = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    scale_up_pct = models.PositiveSmallIntegerField(default=10, validators=[MinValueValidator(1)])
    scale_down_pct = models.PositiveSmallIntegerField(default=10, validators=[MinValueValidator(1)])
    max_scale_up_pct_per_day = models.PositiveSmallIntegerField(default=30, validators=[MinValueValidator(1)])

    cooldown_hours = models.PositiveIntegerField(default=12)
    hard_pause_on_zero_conversions_days = models.PositiveIntegerField(default=7)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Regra de Otimização"
        verbose_name_plural = "Regras de Otimização"

    def __str__(self) -> str:
        return f"Rules for {self.campaign.name}"


class CampaignMetricSnapshot(models.Model):
    SOURCE_GOOGLE = "google_ads"
    SOURCE_META = "meta_ads"
    SOURCE_CHOICES = [
        (SOURCE_GOOGLE, "Google Ads"),
        (SOURCE_META, "Meta Ads"),
    ]

    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE, related_name="metrics")
    date = models.DateField()
    source = models.CharField(max_length=32, choices=SOURCE_CHOICES)

    impressions = models.BigIntegerField(default=0)
    clicks = models.BigIntegerField(default=0)
    cost_micros = models.BigIntegerField(default=0)
    conversions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    conversion_value_micros = models.BigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("campaign", "date", "source")]
        verbose_name = "Métrica Diária"
        verbose_name_plural = "Métricas Diárias"
        indexes = [
            models.Index(fields=["campaign", "date"]),
            models.Index(fields=["date"]),
        ]

    def __str__(self) -> str:
        return f"{self.campaign.name} • {self.date} • {self.source}"


class AutomationRun(models.Model):
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"
    STATUS_CHOICES = [
        (STATUS_SUCCESS, "Sucesso"),
        (STATUS_FAILED, "Falhou"),
        (STATUS_SKIPPED, "Ignorado"),
    ]

    TYPE_SYNC = "sync"
    TYPE_OPTIMIZE = "optimize"
    TYPE_CREATE = "create"
    TYPE_DUPLICATE = "duplicate"
    TYPE_CHOICES = [
        (TYPE_SYNC, "Sincronizar"),
        (TYPE_OPTIMIZE, "Otimizar"),
        (TYPE_CREATE, "Criar"),
        (TYPE_DUPLICATE, "Duplicar"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="ads_runs")
    campaign = models.ForeignKey(AdCampaign, on_delete=models.SET_NULL, null=True, blank=True, related_name="runs")

    run_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_SUCCESS)

    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    summary = models.CharField(max_length=255, blank=True, null=True)
    payload = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Execução"
        verbose_name_plural = "Execuções"
        indexes = [models.Index(fields=["run_type", "status", "started_at"])]

    def __str__(self) -> str:
        return f"{self.get_run_type_display()} • {self.get_status_display()} • {self.started_at:%Y-%m-%d %H:%M}"


class AIUsageLog(models.Model):
    PURPOSE_COPY = "copy"
    PURPOSE_AUDIT = "audit"
    PURPOSE_ANALYSIS = "analysis"
    PURPOSE_CHOICES = [
        (PURPOSE_COPY, "Copy/Criação"),
        (PURPOSE_AUDIT, "Auditoria"),
        (PURPOSE_ANALYSIS, "Análise"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_usage")
    provider = models.CharField(max_length=32, default=UserAdsSettings.AI_PROVIDER_GEMINI)
    model = models.CharField(max_length=64, blank=True, null=True)
    purpose = models.CharField(max_length=16, choices=PURPOSE_CHOICES, default=PURPOSE_COPY)

    input_chars = models.PositiveIntegerField(default=0)
    output_chars = models.PositiveIntegerField(default=0)
    tokens_est = models.PositiveIntegerField(default=0)
    cost_est_usd = models.DecimalField(max_digits=9, decimal_places=4, default=Decimal("0.0"))

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Uso de IA"
        verbose_name_plural = "Uso de IA"
        indexes = [models.Index(fields=["user", "created_at"])]

    def __str__(self) -> str:
        return f"AI usage {self.user} • {self.created_at:%Y-%m-%d %H:%M}"
