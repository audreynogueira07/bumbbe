from django.urls import path

from .api import WordpressChatAPI, WordpressBotConfigAPI, WordpressBotSyncAPI
app_name = 'wpbot'

urlpatterns = [
    path("api/chat/", WordpressChatAPI.as_view(), name="wpbot_api_chat"),
    path("api/bot/config/", WordpressBotConfigAPI.as_view(), name="wpbot_api_config"),
    path("api/bot/sync/", WordpressBotSyncAPI.as_view(), name="wpbot_api_sync"),
]
