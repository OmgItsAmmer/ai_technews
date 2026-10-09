from django.urls import path
from . import views

urlpatterns = [
    path('', views.feed_view, name='feed'),
    path('saved', views.saved_view, name='saved'),
    path('api/save', views.api_save_post, name='api_save'),
    path('api/saved', views.api_get_saved, name='api_get_saved'),
    path('api/fetch-latest', views.api_fetch_latest, name='api_fetch_latest'),
    path('api/fetch-status/<str:run_id>', views.api_fetch_status, name='api_fetch_status'),
    path('api/chat', views.api_chat, name='api_chat'),
    path('api/chat/history', views.api_chat_history, name='api_chat_history'),
    path('api/chat/stream', views.api_chat_stream, name='api_chat_stream'),
    path('api/chat/feedback', views.api_chat_feedback, name='api_chat_feedback'),
]
