from django.urls import path
from . import views

urlpatterns = [
    path('', views.feed_view, name='feed'),
    path('saved', views.saved_view, name='saved'),
    path('api/save', views.api_save_post, name='api_save'),
    path('api/saved', views.api_get_saved, name='api_get_saved'),
]
