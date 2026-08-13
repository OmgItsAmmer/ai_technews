from django import forms
from django.core.exceptions import ValidationError
from django.contrib import admin

from .models import Post, KeywordSetting, LLMConfig


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


class LLMConfigForm(forms.ModelForm):
    class Meta:
        model = LLMConfig
        fields = "__all__"

    def clean_base_url(self):
        url = (self.cleaned_data.get("base_url") or "").strip()
        if url and not url.startswith(("http://", "https://")):
            raise ValidationError("Base URL must start with http:// or https://")
        return url

    def clean_model_name(self):
        return (self.cleaned_data.get("model_name") or "").strip()


@admin.register(LLMConfig)
class LLMConfigAdmin(admin.ModelAdmin):
    form = LLMConfigForm
    fieldsets = (
        (
            None,
            {
                "fields": ("base_url", "model_name"),
                "description": (
                    "Configure the local or remote OpenAI-compatible LLM used for article extraction. "
                    "Values saved here override LOCAL_LLM_BASE_URL and LOCAL_LLM_MODEL from .env."
                ),
            },
        ),
    )

    def has_add_permission(self, request):
        if LLMConfig.objects.exists():
            return False
        return True

    def add_view(self, request, form_url="", extra_context=None):
        if LLMConfig.objects.exists():
            from django.shortcuts import redirect
            from django.urls import reverse
            obj = LLMConfig.objects.first()
            return redirect(reverse("admin:posts_llmconfig_change", args=[obj.pk]))
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


admin.site.enable_nav_sidebar = False


