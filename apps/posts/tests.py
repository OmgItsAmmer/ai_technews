from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.posts.models import KeywordSetting
from apps.posts.admin import KeywordSettingForm


class KeywordSettingTestCase(TestCase):
    def test_keywords_validation_success(self):
        # 10 keywords
        form = KeywordSettingForm(data={
            "keywords": "ai, ml, llm, agent, python, django, coding, dev, test, search"
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.cleaned_data["keywords"],
            "ai, ml, llm, agent, python, django, coding, dev, test, search"
        )

    def test_keywords_validation_failure(self):
        # 11 keywords
        form = KeywordSettingForm(data={
            "keywords": "ai, ml, llm, agent, python, django, coding, dev, test, search, extra"
        })
        self.assertFalse(form.is_valid())
        self.assertIn("keywords", form.errors)
        self.assertEqual(
            form.errors["keywords"][0],
            "You can enter at most 10 comma-separated keywords."
        )

    def test_singleton_add_permission(self):
        from unittest.mock import Mock
        from apps.posts.admin import KeywordSettingAdmin
        from django.contrib.admin.sites import AdminSite

        admin_instance = KeywordSettingAdmin(KeywordSetting, AdminSite())
        request = Mock()

        # Should be True initially when no settings exist
        self.assertTrue(admin_instance.has_add_permission(request))

        # Create one instance
        KeywordSetting.objects.create(keywords="test")

        # Should return False now
        self.assertFalse(admin_instance.has_add_permission(request))
