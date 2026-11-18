import logging

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def allowed_hosts(settings):
    settings.ALLOWED_HOSTS = ["testserver"]


def duration_header(response):
    value = response["X-Request-Duration-Ms"]
    duration = float(value)
    assert duration >= 0
    return duration


def test_success_response_has_duration_header(client):
    response = client.get("/api/openapi.json")

    assert response.status_code == 200
    duration_header(response)


def test_error_response_has_duration_header(client):
    response = client.get("/api/v1/instances/999999")

    assert response.status_code == 404
    duration_header(response)


def test_request_duration_is_logged(client, caplog):
    with caplog.at_level(logging.INFO, logger="config.middleware"):
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    assert any(
        "GET /api/openapi.json 200" in record.message for record in caplog.records
    )
