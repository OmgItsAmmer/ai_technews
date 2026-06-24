from django.urls import path

from apps.fetcher import views

urlpatterns = [
    path("internal/trigger-fetch/", views.trigger_fetch, name="trigger-fetch"),
]
