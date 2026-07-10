from __future__ import annotations

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from merger.lenskit.service.access_log import SafeAccessLogMiddleware


LOGGER_NAME = "uvicorn.error.rlens_access"


def _records(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [json.loads(record.message) for record in caplog.records if record.name == LOGGER_NAME]


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SafeAccessLogMiddleware)

    @app.post("/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("synthetic secret must not be logged")

    return app


def test_access_log_uses_route_template_without_credentials_or_dynamic_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "token-DO-NOT-LOG"
    app = _app()

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        response = TestClient(app).post(
            f"/items/private-item?token={secret}&next=confidential",
            headers={"Authorization": f"Bearer {secret}", "Cookie": f"session={secret}"},
            content=f"body={secret}",
        )

    assert response.status_code == 200
    records = _records(caplog)
    assert len(records) == 1
    assert records[0]["event"] == "http_access"
    assert records[0]["method"] == "POST"
    assert records[0]["route"] == "/items/{item_id}"
    assert records[0]["status"] == 200
    assert isinstance(records[0]["duration_ms"], float)

    rendered = "\n".join(record.message for record in caplog.records)
    assert secret not in rendered
    assert "private-item" not in rendered
    assert "confidential" not in rendered
    assert "Authorization" not in rendered
    assert "Cookie" not in rendered


def test_unmatched_request_does_not_log_concrete_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _app()

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        response = TestClient(app).get("/missing/private-file-name?token=secret")

    assert response.status_code == 404
    record = _records(caplog)[0]
    assert record["route"] == "<unmatched>"
    assert record["status"] == 404
    assert "private-file-name" not in caplog.text
    assert "secret" not in caplog.text


def test_exception_is_logged_as_500_without_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _app()

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        response = TestClient(app, raise_server_exceptions=False).get("/boom?token=secret")

    assert response.status_code == 500
    record = _records(caplog)[0]
    assert record["route"] == "/boom"
    assert record["status"] == 500
    assert "synthetic secret" not in caplog.text
    assert "token=secret" not in caplog.text


@pytest.mark.asyncio
async def test_non_http_scope_is_forwarded_without_access_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    called = []

    async def inner(scope, receive, send):
        called.append(scope["type"])

    middleware = SafeAccessLogMiddleware(inner)

    async def receive():
        return {"type": "websocket.disconnect"}

    async def send(_message):
        return None

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await middleware({"type": "websocket"}, receive, send)

    assert called == ["websocket"]
    assert _records(caplog) == []


def test_logging_handler_failure_does_not_break_response() -> None:
    class BrokenLogger:
        def info(self, _message: str) -> None:
            raise RuntimeError("logging backend unavailable")

    app = FastAPI()
    app.add_middleware(SafeAccessLogMiddleware, logger=BrokenLogger())

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    response = TestClient(app).get("/health?token=secret")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_production_app_registers_safe_access_log_middleware() -> None:
    from merger.lenskit.service.app import app

    assert any(middleware.cls is SafeAccessLogMiddleware for middleware in app.user_middleware)


@pytest.mark.asyncio
async def test_access_fields_are_ascii_single_line_and_bounded() -> None:
    messages: list[str] = []

    class CapturingLogger:
        def info(self, message: str) -> None:
            messages.append(message)

    class SyntheticRoute:
        path = "/safe\nroute/" + ("x" * 400)

    async def inner(scope, receive, send):
        scope["route"] = SyntheticRoute()
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = SafeAccessLogMiddleware(inner, logger=CapturingLogger())

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    await middleware(
        {"type": "http", "method": "GET\nINJECT" + ("A" * 100)},
        receive,
        send,
    )

    assert len(messages) == 1
    assert "\n" not in messages[0]
    record = json.loads(messages[0])
    assert record["method"] == "GET?INJECTAAAAAA"
    assert len(record["method"]) == 16
    assert record["route"].startswith("/safe?route/")
    assert len(record["route"]) == 256
    assert record["status"] == 204
