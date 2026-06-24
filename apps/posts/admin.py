from django.contrib import admin

from .models import Post


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "published_at", "tags")
    list_filter = ("status",)
    search_fields = ("title", "summary")
    readonly_fields = (
        "source",
        "title",
        "original_url",
        "author",
        "published_at",
        "fetched_at",
        "raw_content",
        "summary",
        "tags",
        "status",
        "url_hash",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
