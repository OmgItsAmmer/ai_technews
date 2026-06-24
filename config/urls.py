from django.contrib import admin
from django.urls import include, path
from config.admin_site import admin_site

urlpatterns = [
    # Custom admin URLs
    path("admin/", include("apps.posts.admin_urls")),
    path("admin/", admin_site.urls),
    # Frontend URLs
    path("", include("apps.fetcher.urls")),
    path("", include("apps.frontend.urls")),
]
