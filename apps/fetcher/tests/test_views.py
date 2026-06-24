from unittest.mock import MagicMock, patch

import pytest
from django.test import Client, override_settings

TRIGGER_URL = "/internal/trigger-fetch/"
CRON_SECRET = "test-cron-secret-value"


@pytest.fixture
def client():
    return Client()


@override_settings(CRON_SECRET=CRON_SECRET)
@patch("apps.fetcher.views.fetch_all_sources.delay")
def test_trigger_fetch_dispatches_with_valid_secret(mock_delay, client):
    mock_result = MagicMock()
    mock_result.id = "task-abc-123"
    mock_delay.return_value = mock_result

    response = client.post(
        TRIGGER_URL,
        HTTP_X_CRON_SECRET=CRON_SECRET,
    )

    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "dispatched"
    assert data["task_id"] == "task-abc-123"
    mock_delay.assert_called_once()


@override_settings(CRON_SECRET=CRON_SECRET)
def test_trigger_fetch_rejects_missing_secret(client):
    response = client.post(TRIGGER_URL)

    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden."


@override_settings(CRON_SECRET=CRON_SECRET)
def test_trigger_fetch_rejects_wrong_secret(client):
    response = client.post(
        TRIGGER_URL,
        HTTP_X_CRON_SECRET="wrong-secret",
    )

    assert response.status_code == 403


@override_settings(CRON_SECRET="")
def test_trigger_fetch_returns_503_when_not_configured(client):
    response = client.post(
        TRIGGER_URL,
        HTTP_X_CRON_SECRET="anything",
    )

    assert response.status_code == 503


@override_settings(CRON_SECRET=CRON_SECRET)
def test_trigger_fetch_rejects_get(client):
    response = client.get(
        TRIGGER_URL,
        HTTP_X_CRON_SECRET=CRON_SECRET,
    )

    assert response.status_code == 405
