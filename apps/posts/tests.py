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

    def test_annotate_matched_keywords(self):
        from apps.posts.models import Post
        from apps.frontend.views import annotate_matched_keywords
        
        # Create setting
        KeywordSetting.objects.create(keywords="GPT-5, OpenAI")
        
        # Create posts
        post1 = Post.objects.create(title="We love GPT-5 and its capabilities", status="approved")
        post2 = Post.objects.create(title="Something completely unrelated", summary="OpenAI released a model", status="approved")
        post3 = Post.objects.create(title="Nothing here", status="approved")
        
        posts = [post1, post2, post3]
        annotate_matched_keywords(posts)
        
        self.assertEqual(post1.matched_keyword, "GPT-5")
        self.assertEqual(post2.matched_keyword, "OpenAI")
        self.assertIsNone(post3.matched_keyword)

    def test_feed_view_featured_on_top(self):
        from django.test import Client
        from apps.posts.models import Post
        
        # Create setting
        KeywordSetting.objects.create(keywords="GPT-5")
        
        # Create posts
        post1 = Post.objects.create(title="We love GPT-5", status="approved")
        post2 = Post.objects.create(title="unrelated news", status="approved")
        
        client = Client()
        response = client.get('/?featured=1')
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        pos1 = content.find("We love GPT-5")
        pos2 = content.find("unrelated news")
        self.assertTrue(pos1 != -1)
        self.assertTrue(pos2 != -1)
        self.assertTrue(pos1 < pos2)



