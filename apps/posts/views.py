import json
import logging
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required
from apps.posts.models import Post
from apps.extraction.service import extract_metadata

logger = logging.getLogger(__name__)


staff_required = staff_member_required(login_url="/admin/login/")


@staff_required
@require_POST
def extract_preview(request):
    """
    POST /admin/extract-preview/
    Accepts JSON body: {"mode": "url" | "text", "content": "..."}
    Runs extraction pipeline and returns metadata result.
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON format"}, status=400)

    mode = data.get("mode")
    content = data.get("content")

    if not mode or mode not in ["url", "text"]:
        return JsonResponse({"detail": "Invalid or missing mode"}, status=400)

    if not content or not content.strip():
        return JsonResponse({"detail": "content is required"}, status=400)

    try:
        result = extract_metadata(mode, content)
        return JsonResponse(result, status=200)
    except Exception as e:
        logger.error(f"Error in extract_preview view: {e}")
        return JsonResponse({"detail": f"Server error: {str(e)}"}, status=500)


@staff_required
@require_POST
def publish_post(request):
    """
    POST /admin/publish/
    Accepts JSON body for the final post fields.
    Validates tags, checks for duplicate URL, and saves as approved.
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "detail": "Invalid JSON format"}, status=400)

    title = data.get("title")
    author = data.get("author")
    published_at = data.get("published_at")
    summary = data.get("summary")
    tags = data.get("tags", [])
    original_url = data.get("original_url")
    raw_input = data.get("raw_input")

    # 1. Reject if tags is empty
    if not tags:
        return JsonResponse({
            "status": "error",
            "detail": "At least one tag is required."
        }, status=400)

    # 2. Check for duplicate URL if original_url is present
    if original_url:
        existing_post = Post.objects.filter(original_url=original_url).first()
        if existing_post:
            return JsonResponse({
                "status": "error",
                "detail": "A post with this URL already exists.",
                "post_id": existing_post.id
            }, status=409)

    # 3. Create approved Post
    # Note: main backend uses raw_content field; raw_input from admin intake maps to it.
    try:
        post = Post.objects.create(
            title=title or "Untitled",
            author=author or "",
            published_at=published_at if published_at else None,
            summary=summary or "",
            tags=tags,
            original_url=original_url if original_url else None,
            raw_content=raw_input or "",
            status="approved"
        )
        return JsonResponse({
            "status": "ok",
            "post_id": post.id
        }, status=201)
    except Exception as e:
        logger.error(f"Error creating Post in publish_post view: {e}")
        return JsonResponse({
            "status": "error",
            "detail": f"Failed to save post: {str(e)}"
        }, status=500)
