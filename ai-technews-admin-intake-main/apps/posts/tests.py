import json
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from apps.posts.models import Post

class PostModelTest(TestCase):
    def test_save_generates_url_hash(self):
        post = Post.objects.create(
            title="Test Post",
            original_url="https://example.com/unique-article",
            raw_input="Sample text",
            summary="Sample summary",
            tags=["llms"],
            status="approved"
        )
        self.assertIsNotNone(post.url_hash)
        self.assertEqual(len(post.url_hash), 64)  # SHA-256 hex digest is 64 chars

class AdminAddNewsViewsTest(TestCase):
    def setUp(self):
        self.client = Client()
        # Create a staff user to pass @staff_member_required
        self.username = "admin"
        self.password = "password123"
        self.admin_user = User.objects.create_superuser(
            username=self.username,
            email="admin@example.com",
            password=self.password
        )
        # Log the user in
        self.client.login(username=self.username, password=self.password)

    @patch("apps.posts.views.extract_metadata")
    def test_extract_preview_success(self, mock_extract):
        mock_extract.return_value = {
            "is_valid_news": True,
            "title": "AI Breakthrough",
            "author": "Jane Doe",
            "published_at": "2026-06-20T10:00:00Z",
            "summary": "AI achieves superhuman coding skills.",
            "tags": ["llms"],
            "missing_fields": []
        }
        
        response = self.client.post(
            reverse("extract_preview"),
            data=json.dumps({"mode": "url", "content": "https://example.com/ai-news"}),
            content_type="application/json"
        )
        
        self.assertEqual(response.status_code, 200)
        resp_data = response.json()
        self.assertTrue(resp_data["is_valid_news"])
        self.assertEqual(resp_data["title"], "AI Breakthrough")

    def test_extract_preview_invalid_input(self):
        # Empty content
        response = self.client.post(
            reverse("extract_preview"),
            data=json.dumps({"mode": "url", "content": ""}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        
        # Missing mode
        response = self.client.post(
            reverse("extract_preview"),
            data=json.dumps({"content": "https://example.com"}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_publish_post_success(self):
        payload = {
            "title": "AI in 2026",
            "author": "John Doe",
            "published_at": "2026-06-24T12:00:00Z",
            "summary": "AI is changing the world.",
            "tags": ["llms", "research"],
            "original_url": "https://example.com/ai-2026",
            "raw_input": "Full text body here."
        }
        
        response = self.client.post(
            reverse("publish_post"),
            data=json.dumps(payload),
            content_type="application/json"
        )
        
        self.assertEqual(response.status_code, 201)
        resp_data = response.json()
        self.assertEqual(resp_data["status"], "ok")
        self.assertTrue("post_id" in resp_data)
        
        # Verify in DB
        post = Post.objects.get(id=resp_data["post_id"])
        self.assertEqual(post.title, "AI in 2026")
        self.assertEqual(post.status, "approved")

    def test_publish_post_no_tags_rejected(self):
        payload = {
            "title": "No Tags Post",
            "author": "John Doe",
            "published_at": "2026-06-24T12:00:00Z",
            "summary": "AI is changing the world.",
            "tags": [],  # Empty tags should be rejected
            "original_url": "https://example.com/no-tags",
            "raw_input": "Full text body here."
        }
        
        response = self.client.post(
            reverse("publish_post"),
            data=json.dumps(payload),
            content_type="application/json"
        )
        
        self.assertEqual(response.status_code, 400)
        resp_data = response.json()
        self.assertEqual(resp_data["status"], "error")
        self.assertEqual(resp_data["detail"], "At least one tag is required.")

    def test_publish_post_duplicate_url_rejected(self):
        # Create an existing post first
        url = "https://example.com/duplicate"
        Post.objects.create(
            title="Existing Post",
            original_url=url,
            raw_input="Some input",
            summary="Some summary",
            tags=["llms"],
            status="approved"
        )
        
        # Try to publish another post with the same URL
        payload = {
            "title": "Duplicate URL Post",
            "author": "Jane Doe",
            "published_at": "2026-06-24T12:00:00Z",
            "summary": "Another summary",
            "tags": ["robotics"],
            "original_url": url,
            "raw_input": "Duplicate text."
        }
        
        response = self.client.post(
            reverse("publish_post"),
            data=json.dumps(payload),
            content_type="application/json"
        )
        
        self.assertEqual(response.status_code, 409)
        resp_data = response.json()
        self.assertEqual(resp_data["status"], "error")
        self.assertTrue("post_id" in resp_data)
        self.assertEqual(resp_data["detail"], "A post with this URL already exists.")
