from django.urls import path
from . import views

app_name = 'chatbot'

urlpatterns = [
    # Bot Management
    path('', views.chatbot_list_view, name='list'),
    path('create/', views.chatbot_create_view, name='create'),
    path('<int:bot_id>/edit/', views.chatbot_edit_view, name='edit'),
    path('<int:bot_id>/delete/', views.chatbot_delete_view, name='delete'),
    
    # Media Management
    path('media/<int:media_id>/delete/', views.chatbot_media_delete_view, name='delete_media'),
    
    # Contact Management
    path('contacts/', views.contact_list_view, name='contacts'),
    path('contacts/<int:contact_id>/manage/', views.contact_edit_view, name='contact_edit'),
]
