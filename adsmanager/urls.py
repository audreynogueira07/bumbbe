from django.urls import path

from . import views

app_name = "adsmanager"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),

    # settings
    path("settings/", views.settings_view, name="settings"),

    # accounts
    path("accounts/", views.account_list, name="accounts"),
    path("accounts/new/", views.account_create, name="account_create"),
    path("accounts/<int:account_id>/edit/", views.account_edit, name="account_edit"),
    path("accounts/<int:account_id>/sync/", views.account_sync, name="account_sync"),

    # campaigns
    path("campaigns/", views.campaign_list, name="campaigns"),
    path("campaigns/new/", views.campaign_create, name="campaign_create"),
    path("campaigns/<int:campaign_id>/", views.campaign_detail, name="campaign_detail"),
    path("campaigns/<int:campaign_id>/optimize/", views.campaign_optimize, name="campaign_optimize"),
    path("campaigns/<int:campaign_id>/sync-metrics/", views.campaign_sync_metrics, name="campaign_sync_metrics"),
    path("campaigns/<int:campaign_id>/duplicate/", views.campaign_duplicate, name="campaign_duplicate"),
    path("campaigns/<int:campaign_id>/rule/", views.campaign_rule_edit, name="campaign_rule_edit"),
    path("campaigns/<int:campaign_id>/schedule/", views.campaign_schedule_edit, name="campaign_schedule_edit"),

    # creatives
    path("creatives/", views.creative_list, name="creatives"),
    path("creatives/new/", views.creative_create, name="creative_create"),
]
