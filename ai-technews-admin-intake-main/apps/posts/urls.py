from django.urls import path
from apps.posts import views

urlpatterns = [
    path('extract-preview/', views.extract_preview, name='extract_preview'),
    path('publish/', views.publish_post, name='publish_post'),
]
