from django.urls import path
from . import views

app_name = "flowbot"

urlpatterns = [
    # Dashboard
    path("", views.flowbot_list_view, name="list"),
    path("create/", views.flowbot_create_view, name="create"),
    path("<int:bot_id>/", views.flowbot_detail_view, name="detail"),
    path("<int:bot_id>/delete/", views.flowbot_delete_view, name="delete"),

    # Builder
    path("<int:bot_id>/builder/", views.flowbot_builder_view, name="builder"),

    # Media
    path("<int:bot_id>/media/", views.flowbot_media_view, name="media"),
    path("media/<int:media_id>/delete/", views.flowbot_media_delete_view, name="media_delete"),

    # APIs (usadas pelo editor/simulador)
    path("<int:bot_id>/api/flow/get/", views.api_get_flow, name="api_get_flow"),
    path("<int:bot_id>/api/flow/save/", views.api_save_flow, name="api_save_flow"),
    path("<int:bot_id>/api/media/list/", views.api_media_list, name="api_media_list"),
    path("<int:bot_id>/api/chat/start/", views.api_chat_start, name="api_chat_start"),
    path("<int:bot_id>/api/chat/send/", views.api_chat_send, name="api_chat_send"),
    path("<int:bot_id>/api/chat/reset/", views.api_chat_reset, name="api_chat_reset"),

# APIs públicas (para integrações). Autenticação por token (FlowBot.public_token)
path("public/<uuid:token>/chat/start/", views.api_public_chat_start, name="api_public_chat_start"),
path("public/<uuid:token>/chat/send/", views.api_public_chat_send, name="api_public_chat_send"),
path("public/<uuid:token>/chat/reset/", views.api_public_chat_reset, name="api_public_chat_reset"),

]
