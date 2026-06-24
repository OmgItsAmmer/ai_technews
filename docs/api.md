# API Reference

This document provides details for the API endpoints available in the AI News application.

---

## 1. Trigger Source Fetching

### Purpose
An authenticated endpoint to trigger an asynchronous Celery task that fetches and processes news from all active sources.
It is designed to be called by external cron orchestrators (e.g., GitHub Actions, UptimeRobot) and returns immediately.

### Request Format
* **Method:** `POST`
* **URL:** `/internal/trigger-fetch/`
* **Headers:**
  * `X-Cron-Secret`: `<string>` (Required: Secret token matching the configured `CRON_SECRET`)
* **Body:** None (Empty body)

### Response Format

#### 202 Accepted (Success)
Returned when the fetch action is successfully authenticated and dispatched to the Celery worker queue.
```json
{
  "status": "dispatched",
  "task_id": "8a3d90e2-36fb-4f24-9b2f-3d607421cb8b"
}
```

#### 403 Forbidden
Returned when the `X-Cron-Secret` header is missing, incorrect, or empty.
```json
{
  "status": "error",
  "detail": "Forbidden."
}
```

#### 503 Service Unavailable
Returned when the application's `CRON_SECRET` environment variable is not configured, disabling the trigger functionality.
```json
{
  "status": "error",
  "detail": "Cron trigger is not configured."
}
```
