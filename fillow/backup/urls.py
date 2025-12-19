from django.urls import path
from . import views
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.contrib.auth import logout
# ==============================================================================
# ROTAS COMPLETAS (DASHBOARD + API V1)
# ==============================================================================

app_name = 'fillow'
# ==============================================================================
# FUNÇÃO AUXILIAR DE LOGOUT
# ==============================================================================
def dashboard_logout(request):
    """
    Função manual de Logout.
    Aceita GET e POST, contornando a restrição do Django 5+ (Method Not Allowed).
    """
    logout(request)
    return redirect('fillow:login')

urlpatterns = [
    # --- FRONTEND E PAINEL ---
    path('', views.dashboard_view, name='index'),
    path('api/v1/', views.api_dashboard_view, name='api-v1'),
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', dashboard_logout, name='logout'),
    path('docs/', views.docs_view, name='docs'),
    path('instance/<uuid:instance_id>/manage/', views.instance_dashboard_view, name='instance_dashboard'),

    # --- API INTERNA (Gerenciamento via Painel AJAX) ---
    path('api/internal/instances/create/', views.InstanceActionView.as_view(), name='api_create_instance'),
    path('api/internal/instances/<uuid:pk>/delete/', views.InstanceActionView.as_view(), name='api_delete_instance'),
    path('api/internal/instances/<uuid:instance_id>/connect/', views.connect_instance_view, name='api_connect_instance'),
    path('api/internal/instances/<uuid:instance_id>/disconnect/', views.disconnect_instance_view, name='api_disconnect_instance'),
    path('api/internal/instances/<uuid:instance_id>/status/', views.get_instance_status_view, name='api_get_status'),
    path('api/internal/instances/<uuid:instance_id>/webhook/', views.update_webhook_view, name='api_update_webhook'),
    path('api/internal/instances/<uuid:instance_id>/messages/', views.get_instance_messages_view, name='api_get_messages'),
    path('api/internal/instances/<uuid:instance_id>/test-send/', views.send_test_message_view, name='api_send_test'),
    path('api/internal/instances/<uuid:instance_id>/test-media/', views.send_test_media_view, name='api_send_media'),
    path('internal/webhook/node/', views.InternalWebhookReceiver.as_view(), name='node_webhook_receiver'),

    # --- API PÚBLICA V1 ---
    
    # 1. Mensagens e Mídia
    path('api/v1/message/send/', views.SendMessageGateway.as_view(), name='v1_send_message'),
    path('api/v1/message/send-media/', views.SendMediaView.as_view(), name='v1_send_media'), 
    path('api/v1/message/send-voice/', views.SendVoiceView.as_view(), name='v1_send_voice'),
    path('api/v1/message/<str:type>/', views.SendInteractiveView.as_view(), name='v1_send_interactive'), # poll, location, contact, reaction
    
    # 2. Gestão de Mensagens
    path('api/v1/message/manage/<str:action>/', views.MessageManageView.as_view(), name='v1_message_manage'), # edit, delete, pin, unpin, star
    
    # 3. Gestão de Chat
    path('api/v1/chat/manage/<str:action>/', views.ChatManageView.as_view(), name='v1_chat_manage'), # archive, mute, clear, mark-read

    # 4. Grupos
    path('api/v1/groups/', views.GroupView.as_view(), name='v1_groups_list'),
    path('api/v1/groups/<str:action>/', views.GroupView.as_view(), name='v1_groups_action'), # create, join
    
    # 5. Detalhes de Grupos (Ações Específicas por ID)
    path('api/v1/groups/<str:group_id>/<str:action>/', views.GroupDetailView.as_view(), name='v1_group_detail_action'),
    # POST: participants, leave, revoke-invite
    # PUT: subject, description, settings
    # GET: invite-code

    # 6. Perfil e Usuários
    path('api/v1/profile/info/<str:jid>/', views.ProfileView.as_view(), name='v1_profile_info'),
    path('api/v1/profile/blocklist/', views.ProfileView.as_view(), name='v1_blocklist'),
    path('api/v1/profile/manage/<str:action>/', views.ProfileView.as_view(), name='v1_profile_manage'), # PUT status, PUT picture
    path('api/v1/users/<str:action>/', views.UserActionView.as_view(), name='v1_user_action'), # block, check
]