"""
URL configuration for config project.
"""
from django.urls import path, include
from config.admin_site import admin_site

urlpatterns = [
    # Include posts URLs directly under the admin path prefix
    path("admin/", include("apps.posts.urls")),
    # Mount custom admin site
    path("admin/", admin_site.urls),
]
