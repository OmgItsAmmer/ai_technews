import json
from unittest import mock

import pytest
from django.test import Client, override_settings

from apps.ai.client import AIClient, AIUnavailable, parse_sse
from apps.frontend import chat
from apps.posts.models import Post

AI_RESULT = {
    "answer": "Anthropic raised $4 billion [S2].",
    "citations": [{"sid": "S2", "post_id": 7, "title": "Anthropic raises", "source_name": "The Verge",
                   "url": "https://x/7", "date": "2026-10-07"}],
    "trace_id": "t-1",
    "grounding": 1.0,
}


@pytest.fixture(autouse=True)
def _ai_settings(settings):
    settings.AI_SERVICE_URL = "http://ai.test"
    settings.AI_SERVICE_KEY = "k" * 32
    settings.AI_FALLBACK_TO_SCRUTINIZE = False
    chat._CHAT_SESSIONS.clear()


def test_client_requires_key(settings):
    settings.AI_SERVICE_KEY = ""
    with pytest.raises(AIUnavailable):
        AIClient()


def test_client_sends_service_key_and_maps_errors():
    with mock.patch("apps.ai.client.requests.request") as req:
        req.return_value.json.return_value = {"ok": 1}
        req.return_value.raise_for_status.return_value = None
        AIClient().ask("hi", session_id="s")
        assert req.call_args.kwargs["headers"] == {"X-Service-Key": "k" * 32}
        assert req.call_args.args[:2] == ("POST", "http://ai.test/v1/ask/sync")
    import requests

    with mock.patch("apps.ai.client.requests.request", side_effect=requests.ConnectionError("down")):
        with pytest.raises(AIUnavailable):
            AIClient().ask("hi")


def test_parse_sse_handles_split_chunks():
    raw = [b'event: token\ndata: {"type": "tok', b'en", "text": "Hi"}\n\nevent: end\ndata: {}\n\n']
    assert list(parse_sse(iter(raw))) == [{"type": "token", "text": "Hi"}]


def test_ui_formatting():
    assert chat._to_ui_answer("Raised $4B [S2][S10].") == "Raised $4B [#2][#10]."
    cits = chat._to_ui_citations(AI_RESULT["citations"])
    assert cits[0]["index"] == 2 and cits[0]["post_id"] == 7 and cits[0]["snippet"] == ""


def test_session_id_is_bounded_and_stable():
    long = chat.ai_session_id("t" * 200, "p")
    assert len(long) == 64 and long == chat.ai_session_id("t" * 200, "p")
    assert chat.ai_session_id("tok", "page") == "tok:page"


@override_settings(AI_BACKEND="antix")
def test_chat_uses_antix_backend():
    with mock.patch.object(AIClient, "ask", return_value=AI_RESULT) as ask, \
         mock.patch.object(AIClient, "conversation", return_value=[]):
        out = chat.handle_chat_message("tok", "page", "How much did Anthropic raise?")
    ask.assert_called_once_with("How much did Anthropic raise?", session_id="tok:page")
    assert out["answer"] == "Anthropic raised $4 billion [#2]."
    assert out["citations"][0]["index"] == 2 and out["trace_id"] == "t-1"


@override_settings(AI_BACKEND="antix")
def test_antix_failure_shows_error_not_scrutinize():
    with mock.patch.object(AIClient, "ask", side_effect=AIUnavailable("down")), \
         mock.patch.object(AIClient, "conversation", return_value=[]), \
         mock.patch.object(chat, "_handle_scrutinize") as legacy:
        out = chat.handle_chat_message("tok", "page", "q")
    legacy.assert_not_called()
    assert "couldn't reach" in out["answer"]


@override_settings(AI_BACKEND="antix", AI_FALLBACK_TO_SCRUTINIZE=True)
def test_antix_failure_can_fall_back_to_scrutinize():
    with mock.patch.object(AIClient, "ask", side_effect=AIUnavailable("down")), \
         mock.patch.object(chat, "_handle_scrutinize", return_value={"answer": "legacy"}) as legacy:
        out = chat.handle_chat_message("tok", "page", "q")
    legacy.assert_called_once()
    assert out["answer"] == "legacy"


@override_settings(AI_BACKEND="scrutinize")
def test_default_backend_is_untouched_legacy_path():
    with mock.patch.object(chat, "_handle_scrutinize", return_value={"answer": "legacy"}) as legacy, \
         mock.patch.object(AIClient, "ask") as ask:
        chat.handle_chat_message("tok", "page", "q")
    legacy.assert_called_once()
    ask.assert_not_called()


@override_settings(AI_BACKEND="shadow")
def test_shadow_serves_legacy_and_logs_comparison():
    done = []
    legacy = {"answer": "legacy answer", "citations": [{"post_id": 3}, {"post_id": None}]}
    with mock.patch.object(chat, "_handle_scrutinize", return_value=legacy), \
         mock.patch.object(AIClient, "ask", return_value=AI_RESULT) as ask, \
         mock.patch.object(AIClient, "shadow", side_effect=lambda *a: done.append(a)):
        out = chat.handle_chat_message("tok", "page", "q")
        for _ in range(50):  # background thread
            if done:
                break
            import time
            time.sleep(0.02)
    assert out is legacy
    assert ask.call_args.kwargs["session_id"].startswith("shadow:")
    assert done and done[0][0] == "q" and done[0][2] == [3]


@pytest.mark.django_db
class TestViewsAndSignals:
    @override_settings(AI_BACKEND="antix")
    def test_chat_api_end_to_end(self):
        with mock.patch.object(AIClient, "ask", return_value=AI_RESULT), \
             mock.patch.object(AIClient, "conversation", return_value=[
                 {"role": "user", "content": "q", "citations": [], "trace_id": "t-1"},
                 {"role": "assistant", "content": "A [S2].", "citations": AI_RESULT["citations"], "trace_id": "t-1"}]):
            r = Client().post("/api/chat", json.dumps({"message": "q", "session_token": "tok"}),
                              content_type="application/json")
        assert r.status_code == 200
        body = r.json()
        assert body["messages"][1]["content"] == "A [#2]." and body["messages"][1]["citations"][0]["index"] == 2

    @override_settings(AI_BACKEND="antix")
    def test_stream_proxies_sse(self):
        sse = iter([b"event: token\ndata: {}\n\n", b"event: final\ndata: {}\n\n"])
        with mock.patch.object(AIClient, "ask_stream", return_value=sse):
            r = Client().post("/api/chat/stream", json.dumps({"message": "q", "session_token": "tok"}),
                              content_type="application/json")
            body = b"".join(r.streaming_content)
        assert r["Content-Type"].startswith("text/event-stream") and b"event: final" in body

    @override_settings(AI_BACKEND="scrutinize")
    def test_stream_refused_when_not_antix(self):
        r = Client().post("/api/chat/stream", json.dumps({"message": "q"}), content_type="application/json")
        assert r.status_code == 409

    def test_feedback_validation(self):
        c = Client()
        bad = c.post("/api/chat/feedback", json.dumps({"trace_id": "t", "rating": 5}), content_type="application/json")
        assert bad.status_code == 400
        with mock.patch.object(AIClient, "feedback") as fb:
            ok = c.post("/api/chat/feedback", json.dumps({"trace_id": "t", "rating": -1}),
                        content_type="application/json")
        assert ok.status_code == 200 and fb.call_args.args[:2] == ("t", -1)

    @override_settings(AI_BACKEND="antix")
    def test_saving_and_deleting_posts_enqueues_ingest(self, django_capture_on_commit_callbacks):
        with mock.patch("apps.ai.tasks.enqueue_ingest.delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                p = Post.objects.create(title="T", status="approved", original_url="https://x/1")
            assert delay.call_args.args == (p.pk,)
            delay.reset_mock()
            pk = p.pk
            with django_capture_on_commit_callbacks(execute=True):
                p.delete()
            assert delay.call_args.args == (pk,)

    @override_settings(AI_BACKEND="scrutinize")
    def test_no_enqueue_for_legacy_backend(self, django_capture_on_commit_callbacks):
        with mock.patch("apps.ai.tasks.enqueue_ingest.delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                Post.objects.create(title="T2", status="approved", original_url="https://x/2")
        delay.assert_not_called()

    @override_settings(AI_BACKEND="antix")
    def test_broker_outage_does_not_break_saving(self, django_capture_on_commit_callbacks):
        with mock.patch("apps.ai.tasks.enqueue_ingest.delay", side_effect=RuntimeError("broker down")):
            with django_capture_on_commit_callbacks(execute=True):
                p = Post.objects.create(title="T3", status="approved", original_url="https://x/3")
        assert Post.objects.filter(pk=p.pk).exists()
