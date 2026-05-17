"""Tests for the read-only rLens CLI client (cmd_rlens_client.py).

No real rLens server is used. urllib.request.urlopen is monkeypatched.
"""
import json
import pathlib
import urllib.error
import urllib.request

import pytest

import merger.lenskit.cli.cmd_rlens_client as _mod
from merger.lenskit.cli.main import main


class _FakeResponse:
    """Minimal HTTP response context manager for monkeypatching urlopen."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        pass


def _make_opener(response_body: object):
    """Return (captured, urlopen_fn). captured['req'] is the Request object."""
    captured: dict = {}
    body = json.dumps(response_body).encode()
    fake = _FakeResponse(body)

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> _FakeResponse:
        captured["req"] = req
        return fake

    return captured, _urlopen


def _make_bad_json_opener():
    fake = _FakeResponse(b"not valid json!!!")

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> _FakeResponse:
        return fake

    return _urlopen


# ---------------------------------------------------------------------------
# Test 14 — no requests dependency (run first so it's a build-time gate)
# ---------------------------------------------------------------------------


def test_rlens_client_no_requests_dependency() -> None:
    src = pathlib.Path(_mod.__file__).read_text(encoding="utf-8")
    assert "import requests" not in src
    assert "requests." not in src


# ---------------------------------------------------------------------------
# Test 1 — health --json
# ---------------------------------------------------------------------------


def test_rlens_client_health_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    fake_data = {"status": "ok", "version": "1.2.3"}
    captured, opener = _make_opener(fake_data)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["rlens-client", "health", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 0
    parsed = json.loads(out)
    assert parsed["status"] == "ok"
    assert captured["req"].full_url.endswith("/api/health")


# ---------------------------------------------------------------------------
# Test 2 — health text output
# ---------------------------------------------------------------------------


def test_rlens_client_health_text(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    fake_data = {
        "status": "ok",
        "version": "1.0.0",
        "server_version": "srv-2",
        "running_jobs": 3,
        "auth_enabled": True,
    }
    _, opener = _make_opener(fake_data)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["rlens-client", "health"])
    out, _ = capsys.readouterr()

    assert rc == 0
    assert "status" in out
    assert "version" in out
    assert "running_jobs" in out
    assert "auth_enabled" in out


# ---------------------------------------------------------------------------
# Test 3 — base_url from env
# ---------------------------------------------------------------------------


def test_rlens_client_base_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RLENS_BASE_URL", "http://heimserver:8787")
    captured, opener = _make_opener({"status": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["rlens-client", "health", "--json"])

    assert rc == 0
    assert captured["req"].full_url.startswith("http://heimserver:8787")


# ---------------------------------------------------------------------------
# Test 4 — --base-url flag overrides env
# ---------------------------------------------------------------------------


def test_rlens_client_base_url_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RLENS_BASE_URL", "http://wrong:8787")
    captured, opener = _make_opener({"status": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["rlens-client", "health", "--base-url", "http://heim-pc:8787", "--json"])

    assert rc == 0
    assert captured["req"].full_url.startswith("http://heim-pc:8787")
    assert "wrong" not in captured["req"].full_url


# ---------------------------------------------------------------------------
# Test 5 — token from env sent as Bearer header
# ---------------------------------------------------------------------------


def test_rlens_client_token_header_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RLENS_TOKEN", "secret-token")
    captured, opener = _make_opener([])
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["rlens-client", "artifacts", "--json"])

    assert rc == 0
    auth = captured["req"].get_header("Authorization")
    assert auth == "Bearer secret-token"


# ---------------------------------------------------------------------------
# Test 6 — --token flag overrides env
# ---------------------------------------------------------------------------


def test_rlens_client_token_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RLENS_TOKEN", "env-token")
    captured, opener = _make_opener([])
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["rlens-client", "artifacts", "--token", "flag-token", "--json"])

    assert rc == 0
    auth = captured["req"].get_header("Authorization")
    assert auth == "Bearer flag-token"


# ---------------------------------------------------------------------------
# Test 7 — token not leaked on HTTP error
# ---------------------------------------------------------------------------


def test_rlens_client_token_not_leaked_on_http_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("RLENS_TOKEN", "my-secret-token")

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise urllib.error.HTTPError(
            url=None, code=401, msg="Unauthorized", hdrs=None, fp=None
        )

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["rlens-client", "health", "--json"])
    out, err = capsys.readouterr()

    assert rc == 1
    assert "my-secret-token" not in out
    assert "my-secret-token" not in err


# ---------------------------------------------------------------------------
# Test 8 — token not leaked on URL error
# ---------------------------------------------------------------------------


def test_rlens_client_token_not_leaked_on_url_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("RLENS_TOKEN", "my-secret-token")

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["rlens-client", "health", "--json"])
    out, err = capsys.readouterr()

    assert rc == 1
    assert "my-secret-token" not in out
    assert "my-secret-token" not in err


# ---------------------------------------------------------------------------
# Test 9 — artifacts --repo URL-encodes the query param
# ---------------------------------------------------------------------------


def test_rlens_client_artifacts_with_repo_query(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    captured, opener = _make_opener([])
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["rlens-client", "artifacts", "--repo", "lens kit", "--json"])
    capsys.readouterr()

    assert rc == 0
    url = captured["req"].full_url
    assert "/api/artifacts" in url
    # urllib.parse.urlencode encodes space as '+'
    assert "lens+kit" in url or "lens%20kit" in url


# ---------------------------------------------------------------------------
# Test 10 — latest without --repo is a CLI error (no network call)
# ---------------------------------------------------------------------------


def test_rlens_client_latest_requires_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    network_called: dict = {}

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        network_called["hit"] = True
        raise AssertionError("Network must not be called when --repo is missing")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    with pytest.raises(SystemExit) as exc_info:
        main(["rlens-client", "latest", "--json"])

    assert exc_info.value.code != 0
    assert "hit" not in network_called


# ---------------------------------------------------------------------------
# Test 11 — latest with --repo --level --mode builds correct URL
# ---------------------------------------------------------------------------


def test_rlens_client_latest_with_repo_level_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    fake_data = {"id": "art-abc", "repos": "lenskit", "created_at": "2026-01-01"}
    captured, opener = _make_opener(fake_data)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(
        [
            "rlens-client",
            "latest",
            "--repo",
            "lenskit",
            "--level",
            "max",
            "--mode",
            "gesamt",
            "--json",
        ]
    )
    capsys.readouterr()

    assert rc == 0
    url = captured["req"].full_url
    assert "/api/artifacts/latest" in url
    assert "repo=lenskit" in url
    assert "level=max" in url
    assert "mode=gesamt" in url


# ---------------------------------------------------------------------------
# Test 12 — HTTP error → exit 1, JSON error envelope
# ---------------------------------------------------------------------------


def test_rlens_client_http_error_exit_1_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise urllib.error.HTTPError(
            url=None, code=500, msg="Internal Server Error", hdrs=None, fp=None
        )

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["rlens-client", "health", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 1
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert parsed["error_kind"] == "remote_error"


# ---------------------------------------------------------------------------
# Test 13 — non-JSON response → exit 1, parse_error
# ---------------------------------------------------------------------------


def test_rlens_client_invalid_json_response_exit_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _make_bad_json_opener())

    rc = main(["rlens-client", "health", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 1
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert parsed["error_kind"] == "parse_error"
