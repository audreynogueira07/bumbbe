from django.urls import include, path
from . import views
from .api import WordpressChatAPI

app_name = 'wpbot'

urlpatterns = [
    # Dashboard UI
    path('', views.bot_list, name='list'),
    path('create/', views.bot_create, name='create'),
    path('<int:bot_id>/edit/', views.bot_edit, name='edit'),
    path('<int:bot_id>/delete/', views.bot_delete, name='delete'),
    
    path('leads/', views.leads_list, name='leads'),
    path('leads/<int:contact_id>/', views.lead_detail, name='lead_detail'),

    # API Endpoint (Para o Plugin WordPress)
    path('api/chat/', WordpressChatAPI.as_view(), name='api_chat'),

]