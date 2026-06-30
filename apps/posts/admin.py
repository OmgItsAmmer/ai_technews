from django import forms
from django.core.exceptions import ValidationError
from django.contrib import admin
from config.admin_site import admin_site

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


class PostAdmin(admin.ModelAdmin):
    list_display = ("title", "tags", "published_at", "status")

    def has_add_permission(self, request):
        # Disables the standard "Add" button — posts are added via the intake form
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# Register models on our custom admin site
admin_site.register(KeywordSetting, KeywordSettingAdmin)
admin_site.register(Post, PostAdmin)

# Disable the navigation sidebar globally on our custom admin site
admin_site.enable_nav_sidebar = False
