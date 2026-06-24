from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.frontend.urls")),
    path("", include("apps.fetcher.urls")),
]
