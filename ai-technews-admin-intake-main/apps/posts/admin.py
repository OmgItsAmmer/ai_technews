from django.contrib import admin
from config.admin_site import admin_site
from apps.posts.models import Post

class ReadOnlyPostAdmin(admin.ModelAdmin):
    list_display = ("title", "tags", "published_at", "status")
    
    def has_add_permission(self, request):
        # Disables the "Add" button
        return False
        
    def has_change_permission(self, request, obj=None):
        # Prevents editing or accessing detail change pages
        return False
        
    def has_delete_permission(self, request, obj=None):
        # Prevents single or bulk deletion
        return False

# Register Post on our custom ainews_admin site
admin_site.register(Post, ReadOnlyPostAdmin)
