import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class ScrutinizeClient:
    """Service wrapper for interacting with the Scrutinize API (ingestion, library management, and v2 search)."""

    def __init__(self):
        self.base_url = getattr(settings, "SCRUTINIZE_API_BASE_URL", "http://localhost:8000").rstrip("/")
        self.admin_key = getattr(
            settings,
            "SCRUTINIZE_ADMIN_API_KEY",
            "scrutinize_sk_d5e6feae8ca4ff07557f29e8536f20f89b60f73f40270b9e",
        )
        self.client_key = getattr(
            settings,
            "SCRUTINIZE_PUBLIC_CLIENT_KEY",
            "scrutinize_pk_bad456b4ad1c215b093a78e12e33629074ee10f95e7e291b",
        )

    def _admin_headers(self) -> dict:
        return {"X-Project-Key": self.admin_key}

    def _client_headers(self) -> dict:
        return {
            "X-Project-Key": self.client_key,
            "X-Client-Key": self.client_key,
            "Content-Type": "application/json",
        }

    def upload_post(self, post) -> dict | None:
        """Format a Django Post record into text and upload to Scrutinize via POST /upload."""
        filename = f"post_{post.id}.txt"
        tags_str = ", ".join(post.tags) if isinstance(post.tags, list) else str(post.tags or "")
        source_name = post.source.name if post.source else "Antix News"
        date_str = str(post.published_at or post.fetched_at or "")

        content = (
            f"Title: {post.title}\n"
            f"Source: {source_name}\n"
            f"Author: {post.author or 'Editorial Team'}\n"
            f"Published Date: {date_str}\n"
            f"Original URL: {post.original_url or ''}\n"
            f"Tags: {tags_str}\n\n"
            f"Summary:\n{post.summary or 'No summary provided.'}\n\n"
            f"Full Article Content:\n{post.raw_content or post.summary or post.title}"
        )

        url = f"{self.base_url}/upload"
        import time
        for attempt in range(3):
            try:
                files = {"file": (filename, content.encode("utf-8"), "text/plain")}
                resp = requests.post(url, headers=self._admin_headers(), files=files, timeout=30)
                if resp.status_code == 429:
                    retry_after = 5
                    try:
                        err_data = resp.json()
                        retry_after = int(err_data.get("retry_after_seconds", 5))
                    except Exception:
                        pass
                    logger.warning("Rate limited (429) uploading post %s. Waiting %ds (attempt %d/3)...", post.id, retry_after, attempt + 1)
                    time.sleep(retry_after)
                    continue
                resp.raise_for_status()
                data = resp.json()
                logger.info("Successfully uploaded post %s to Scrutinize (file_id=%s)", post.id, data.get("file_id"))
                return data
            except requests.RequestException as e:
                logger.error("Failed to upload post %s to Scrutinize: %s", post.id, e)
                if hasattr(e, "response") and e.response is not None:
                    logger.error("Response content: %s", e.response.text)
                return None
        return None

    def delete_file(self, file_id: str) -> bool:
        """Delete a file from Scrutinize vector storage via DELETE /library/{file_id}."""
        url = f"{self.base_url}/library/{file_id}"
        try:
            resp = requests.delete(url, headers=self._admin_headers(), timeout=15)
            resp.raise_for_status()
            logger.info("Deleted file %s from Scrutinize library.", file_id)
            return True
        except requests.RequestException as e:
            logger.error("Failed to delete file %s from Scrutinize: %s", file_id, e)
            return False

    def list_library(self, limit: int = 500, offset: int = 0) -> list[dict]:
        """Retrieve indexed files from Scrutinize library."""
        url = f"{self.base_url}/library"
        params = {"limit": limit, "offset": offset}
        try:
            resp = requests.get(url, headers=self._admin_headers(), params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                return data.get("files", [])
            elif isinstance(data, list):
                return data
            return []
        except requests.RequestException as e:
            logger.error("Failed to list Scrutinize library: %s", e)
            return []

    def get_job_status(self, job_id: str) -> dict | None:
        """Poll Scrutinize ingestion job status via GET /status/{job_id}."""
        url = f"{self.base_url}/status/{job_id}"
        try:
            resp = requests.get(url, headers=self._admin_headers(), timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("Failed to get Scrutinize job status %s: %s", job_id, e)
            return None

    def search(self, query: str, conversation: dict = None) -> dict | None:
        """Search Scrutinize vector DB and generate LLM answer via POST /v2/search."""
        url = f"{self.base_url}/v2/search"
        payload = {"query": query}
        if conversation:
            payload["conversation"] = conversation

        try:
            resp = requests.post(url, headers=self._client_headers(), json=payload, timeout=120)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("Scrutinize search failed for query '%s': %s", query, e)
            if hasattr(e, "response") and e.response is not None:
                logger.error("Response details: %s", e.response.text)
            return None
