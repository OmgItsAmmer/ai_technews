from django import forms
from django.core.exceptions import ValidationError
from django.contrib import admin
from django.urls import path
from django.shortcuts import redirect
from django.contrib import messages
from django.conf import settings
import httpx

from .models import Post, KeywordSetting


class KeywordSettingForm(forms.ModelForm):
    class Meta:
        model = KeywordSetting
        fields = "__all__"

    def clean_keywords(self):
        keywords_str = self.cleaned_data.get("keywords", "")
        # Split by comma, strip whitespace, exclude empty strings
        kws = [k.strip() for k in keywords_str.split(",") if k.strip()]
        if len(kws) > 10:
            raise ValidationError("You can enter at most 10 comma-separated keywords.")
        return ", ".join(kws)


@admin.register(KeywordSetting)
class KeywordSettingAdmin(admin.ModelAdmin):
    form = KeywordSettingForm

    def has_add_permission(self, request):
        if KeywordSetting.objects.exists():
            return False
        return True

    def add_view(self, request, form_url="", extra_context=None):
        if KeywordSetting.objects.exists():
            from django.shortcuts import redirect
            from django.urls import reverse
            obj = KeywordSetting.objects.first()
            return redirect(reverse("admin:posts_keywordsetting_change", args=[obj.pk]))
        return super().add_view(request, form_url, extra_context)

    def has_delete_permission(self, request, obj=None):
        return False


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

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "embed-latest-30/",
                self.admin_site.admin_view(self.embed_latest_30_view),
                name="posts_post_embed_latest_30",
            ),
        ]
        return custom_urls + urls

    def embed_latest_30_view(self, request):
        latest_posts = Post.objects.all().order_by("-published_at", "-fetched_at")[:30]
        if not latest_posts.exists():
            self.message_user(request, "No articles found to embed.", messages.WARNING)
            return redirect("admin:posts_post_changelist")

        success_count = 0
        error_count = 0

        with httpx.Client(timeout=15.0) as client:
            for post in latest_posts:
                content_parts = [
                    f"Title: {post.title}",
                    f"Author: {post.author or 'Unknown'}",
                    f"Published: {post.published_at.isoformat() if post.published_at else 'Unknown'}",
                    f"URL: {post.original_url or ''}",
                    f"Summary: {post.summary or ''}",
                    f"Tags: {', '.join(post.tags) if isinstance(post.tags, list) else (post.tags or '')}",
                    "\nBody:",
                    post.raw_content or "",
                ]
                file_content = "\n".join(content_parts)
                filename = f"article_{post.id}.txt"

                try:
                    url = f"{settings.SCRUTINIZE_API_BASE_URL.rstrip('/')}/v2/projects/files"
                    headers = {
                        "X-Project-Key": settings.SCRUTINIZE_ADMIN_API_KEY
                    }
                    files = {
                        "file": (filename, file_content.encode("utf-8"), "text/plain")
                    }
                    response = client.post(url, headers=headers, files=files)
                    if response.status_code in (200, 202):
                        res_data = response.json()
                        post.scrutinize_file_id = res_data.get("file_id")
                        post.save(update_fields=["scrutinize_file_id"])
                        success_count += 1
                    else:
                        error_count += 1
                except Exception:
                    error_count += 1

        if success_count > 0:
            self.message_user(
                request,
                f"Successfully submitted {success_count} articles to Scrutinize for embedding.",
                messages.SUCCESS,
            )
        if error_count > 0:
            self.message_user(
                request,
                f"Failed to submit {error_count} articles to Scrutinize.",
                messages.ERROR,
            )

        return redirect("admin:posts_post_changelist")


admin.site.enable_nav_sidebar = False


