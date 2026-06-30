from django import forms
from django.core.exceptions import ValidationError
from django.contrib import admin

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


admin.site.enable_nav_sidebar = False


