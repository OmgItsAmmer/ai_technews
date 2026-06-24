from django.contrib import admin
from apps.posts.constants import TAG_CHOICES

class AddNewsAdminSite(admin.AdminSite):
    site_header = "AI Tech News - Admin"
    index_title = "Add News"
    index_template = "admin/add_news_index.html"

    def index(self, request, extra_context=None):
        if extra_context is None:
            extra_context = {}
        extra_context['tag_choices'] = TAG_CHOICES
        return super().index(request, extra_context)

admin_site = AddNewsAdminSite(name="ainews_admin")
