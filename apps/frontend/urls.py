from django.urls import path
from . import views

urlpatterns = [
    path('', views.feed_view, name='feed'),
    path('saved', views.saved_view, name='saved'),
    path('api/save', views.api_save_post, name='api_save'),
    path('api/saved', views.api_get_saved, name='api_get_saved'),
    path('api/fetch-latest', views.api_fetch_latest, name='api_fetch_latest'),
    path('api/chat', views.api_chat, name='api_chat'),
    path('api/chat/history', views.api_chat_history, name='api_chat_history'),
]
