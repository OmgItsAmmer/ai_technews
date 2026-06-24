import logging

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.fetcher.tasks import fetch_all_sources

logger = logging.getLogger(__name__)

CRON_SECRET_HEADER = "HTTP_X_CRON_SECRET"


@csrf_exempt
@require_POST
def trigger_fetch(request: HttpRequest) -> JsonResponse:
    """
    Wake-and-fetch endpoint for external cron (GitHub Actions, UptimeRobot, etc.).

    Validates X-Cron-Secret, dispatches fetch_all_sources to Celery, returns immediately.
    """
    if not settings.CRON_SECRET:
        logger.error("CRON_SECRET is not configured; refusing trigger request")
        return JsonResponse(
            {"status": "error", "detail": "Cron trigger is not configured."},
            status=503,
        )

    provided = request.META.get(CRON_SECRET_HEADER, "")
    if not provided or provided != settings.CRON_SECRET:
        logger.warning("Rejected fetch trigger: invalid or missing cron secret")
        return JsonResponse(
            {"status": "error", "detail": "Forbidden."},
            status=403,
        )

    result = fetch_all_sources.delay()
    logger.info("Fetch triggered by external cron; task_id=%s", result.id)

    return JsonResponse(
        {"status": "dispatched", "task_id": result.id},
        status=202,
    )
