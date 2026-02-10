"""
Forms for the ads manager app. These forms provide user facing
interfaces for connecting advertising accounts, creating creatives,
and scheduling optimisation tasks.
"""

from django import forms

from .models import (
    AdsAccount, 
    AdCreative, 
    AdSchedule, 
    UserAdsSettings, 
    AutomationRule
)


class AdsAccountForm(forms.ModelForm):
    """
    Form for connecting or editing an advertising/analytics account.
    """
    credentials_json = forms.CharField(
        label="Credenciais (JSON)",
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Insira as credenciais no formato JSON conforme a plataforma escolhida."
    )

    class Meta:
        model = AdsAccount
        fields = ["platform", "name", "credentials_json", "active"]
        widgets = {
            "platform": forms.Select(choices=AdsAccount.PLATFORM_CHOICES),
            "active": forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Populate the credentials_json field with the dict converted to JSON
        if self.instance and self.instance.credentials:
            import json
            self.fields["credentials_json"].initial = json.dumps(self.instance.credentials, indent=2)

    def clean_credentials_json(self):
        value = self.cleaned_data.get("credentials_json")
        import json
        try:
            data = json.loads(value) if value else {}
        except json.JSONDecodeError as e:
            raise forms.ValidationError(f"JSON inválido: {e}")
        return data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.credentials = self.cleaned_data.get("credentials_json", {})
        if commit:
            instance.save()
        return instance


class UserAdsSettingsForm(forms.ModelForm):
    """
    Form for managing user-level settings like AI limits and global spend caps.
    """
    class Meta:
        model = UserAdsSettings
        fields = [
            "ai_enabled",
            "ai_provider",
            "ai_model",
            "ai_daily_limit_usd",
            "ai_monthly_limit_usd",
            "global_daily_spend_cap_micros",
            "global_monthly_spend_cap_micros",
            "allow_auto_sync",
            "allow_auto_optimize",
            "allow_auto_pause",
            "allow_auto_duplicate",
            "allow_auto_refresh_creatives",
            "default_economic_mode",
        ]


class AdCreativeForm(forms.ModelForm):
    """
    Form for creating or updating a creative.
    Includes a non-model field for triggering AI generation.
    """
    generate_ai_variations = forms.BooleanField(
        required=False, 
        label="Gerar variações com IA?", 
        help_text="Se marcado, usa a IA para criar opções baseadas no texto base."
    )

    class Meta:
        model = AdCreative
        fields = ["name", "base_text", "image"]
        widgets = {
            "base_text": forms.Textarea(attrs={"rows": 4}),
        }


class CampaignCreateForm(forms.Form):
    """
    Form for creating a new campaign. This is not a ModelForm because
    creating a campaign involves API calls to the ad platform (Google/Meta)
    before saving to the local database.
    """
    account = forms.ModelChoiceField(
        queryset=AdsAccount.objects.none(), 
        label="Conta de Anúncio"
    )
    name = forms.CharField(max_length=255, label="Nome da Campanha")
    objective = forms.CharField(
        max_length=128, 
        required=False, 
        label="Objetivo (ex: SEARCH, OUTCOME_LEADS)"
    )
    daily_budget = forms.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        label="Orçamento Diário"
    )
    economic_mode = forms.BooleanField(
        required=False, 
        label="Modo Econômico",
        initial=False
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            # Only show accounts belonging to the current user
            self.fields["account"].queryset = AdsAccount.objects.filter(user=user, active=True)


class AdScheduleForm(forms.ModelForm):
    """
    Form for scheduling optimisation tasks.
    """
    class Meta:
        model = AdSchedule
        fields = ["interval_minutes", "active"]


class AutomationRuleForm(forms.ModelForm):
    """
    Form for configuring automation rules (scaling, pausing, etc.) for a campaign.
    """
    class Meta:
        model = AutomationRule
        fields = [
            "active",
            "min_clicks",
            "min_conversions",
            "max_cpa_micros",
            "min_roas",
            "scale_up_pct",
            "scale_down_pct",
            "max_scale_up_pct_per_day",
            "cooldown_hours",
            "hard_pause_on_zero_conversions_days",
        ]