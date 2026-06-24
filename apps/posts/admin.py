from django.contrib import admin
from config.admin_site import admin_site
from apps.posts.models import Post


class PostAdmin(admin.ModelAdmin):
    list_display = ("title", "tags", "published_at", "status")

    def has_add_permission(self, request):
        # Disables the standard "Add" button — posts are added via the intake form
        return False


# Register Post on our custom ainews_admin site
admin_site.register(Post, PostAdmin)
