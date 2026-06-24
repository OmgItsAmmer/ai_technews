from django.contrib import admin

from .models import Source


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "source_type",
        "badge_label",
        "is_active",
        "last_fetched_at",
    )
    list_filter = ("source_type", "is_active")
    search_fields = ("name", "homepage_url", "rss_url")
    readonly_fields = (
        "name",
        "homepage_url",
        "rss_url",
        "source_type",
        "badge_label",
        "is_active",
        "fetch_interval_minutes",
        "last_fetched_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
