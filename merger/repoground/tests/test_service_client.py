"""Tests for the RepoGround service client (cmd_service_client.py).

No real service is used. urllib.request.urlopen is monkeypatched.
"""
import json
import pathlib
import ast
import urllib.error
import urllib.parse
import urllib.request

import pytest

import merger.repoground.cli.cmd_service_client as _mod
from merger.repoground.cli.main import main as _main


def main(args: list[str]) -> int:
    """Run service-client coverage through the canonical command surface."""
    return _main(args)


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


def _assert_request_url(
    req: urllib.request.Request,
    *,
    scheme: str,
    netloc: str,
    path: str,
) -> None:
    parsed = urllib.parse.urlparse(req.full_url)
    assert parsed.scheme == scheme
    assert parsed.netloc == netloc
    assert parsed.path == path


# ---------------------------------------------------------------------------
# Test 14 — no requests dependency (run first so it's a build-time gate)
# ---------------------------------------------------------------------------


def test_service_client_no_requests_dependency() -> None:
    src = pathlib.Path(_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name != "requests" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module != "requests"


# ---------------------------------------------------------------------------
# Test 1 — health --json
# ---------------------------------------------------------------------------


def test_service_client_health_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    fake_data = {"status": "ok", "version": "1.2.3"}
    captured, opener = _make_opener(fake_data)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "health", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 0
    parsed = json.loads(out)
    assert parsed["status"] == "ok"
    assert captured["req"].full_url.endswith("/api/health")


# ---------------------------------------------------------------------------
# Test 2 — health text output
# ---------------------------------------------------------------------------


def test_service_client_health_text(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    fake_data = {
        "status": "ok",
        "version": "1.0.0",
        "server_version": "srv-2",
        "running_jobs": 3,
        "auth_enabled": True,
    }
    _, opener = _make_opener(fake_data)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "health"])
    out, _ = capsys.readouterr()

    assert rc == 0
    assert "status" in out
    assert "version" in out
    assert "running_jobs" in out
    assert "auth_enabled" in out


# ---------------------------------------------------------------------------
# Test 3 — base_url from env
# ---------------------------------------------------------------------------


def test_service_client_base_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOGROUND_BASE_URL", "http://heimserver:8787")
    captured, opener = _make_opener({"status": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "health", "--json"])

    assert rc == 0
    _assert_request_url(captured["req"], scheme="http", netloc="heimserver:8787", path="/api/health")


# ---------------------------------------------------------------------------
# Test 4 — --base-url flag overrides env
# ---------------------------------------------------------------------------


def test_service_client_base_url_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOGROUND_BASE_URL", "http://wrong:8787")
    captured, opener = _make_opener({"status": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "health", "--base-url", "http://heim-pc:8787", "--json"])

    assert rc == 0
    _assert_request_url(captured["req"], scheme="http", netloc="heim-pc:8787", path="/api/health")
    assert "wrong" not in captured["req"].full_url


# ---------------------------------------------------------------------------
# Test 5 — token from env sent as Bearer header
# ---------------------------------------------------------------------------


def test_service_client_token_header_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOGROUND_TOKEN", "secret-token")
    captured, opener = _make_opener([])
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "artifacts", "--json"])

    assert rc == 0
    auth = captured["req"].get_header("Authorization")
    assert auth == "Bearer secret-token"
    assert "secret-token" not in captured["req"].full_url


# ---------------------------------------------------------------------------
# Test 6 — --token flag overrides env
# ---------------------------------------------------------------------------


def test_service_client_token_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOGROUND_TOKEN", "env-token")
    captured, opener = _make_opener([])
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "artifacts", "--token", "flag-token", "--json"])

    assert rc == 0
    auth = captured["req"].get_header("Authorization")
    assert auth == "Bearer flag-token"
    assert "flag-token" not in captured["req"].full_url


def test_service_client_token_before_subcommand_is_safe(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    captured, opener = _make_opener({"status": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "--token", "secret-token", "health", "--json"])
    out, err = capsys.readouterr()

    assert rc == 0
    parsed = json.loads(out)
    assert parsed["status"] == "ok"
    assert captured["req"].get_header("Authorization") == "Bearer secret-token"
    assert "secret-token" not in err


def test_service_client_leaf_token_overrides_parent_token(monkeypatch: pytest.MonkeyPatch) -> None:
    captured, opener = _make_opener([])
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(
        [
            "service-client",
            "--token",
            "parent-token",
            "artifacts",
            "--token",
            "leaf-token",
            "--json",
        ]
    )

    assert rc == 0
    assert captured["req"].get_header("Authorization") == "Bearer leaf-token"


def test_service_client_leaf_base_url_overrides_parent_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured, opener = _make_opener({"status": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(
        [
            "service-client",
            "--base-url",
            "http://parent:8787",
            "health",
            "--base-url",
            "http://leaf:8787",
            "--json",
        ]
    )

    assert rc == 0
    _assert_request_url(captured["req"], scheme="http", netloc="leaf:8787", path="/api/health")


# ---------------------------------------------------------------------------
# Test 7 — token not leaked on HTTP error
# ---------------------------------------------------------------------------


def test_service_client_token_not_leaked_on_http_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("REPOGROUND_TOKEN", "my-secret-token")

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise urllib.error.HTTPError(
            url=None, code=401, msg="Unauthorized", hdrs=None, fp=None
        )

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "health", "--json"])
    out, err = capsys.readouterr()

    assert rc == 1
    assert "my-secret-token" not in out
    assert "my-secret-token" not in err


# ---------------------------------------------------------------------------
# Test 8 — token not leaked on URL error
# ---------------------------------------------------------------------------


def test_service_client_token_not_leaked_on_url_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("REPOGROUND_TOKEN", "my-secret-token")

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "health", "--json"])
    out, err = capsys.readouterr()

    assert rc == 1
    assert "my-secret-token" not in out
    assert "my-secret-token" not in err


# ---------------------------------------------------------------------------
# Test 9 — artifacts --repo URL-encodes the query param
# ---------------------------------------------------------------------------


def test_service_client_artifacts_with_repo_query(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    captured, opener = _make_opener([])
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "artifacts", "--repo", "lens kit", "--json"])
    capsys.readouterr()

    assert rc == 0
    url = captured["req"].full_url
    assert "/api/artifacts" in url
    # urllib.parse.urlencode encodes space as '+'
    assert "lens+kit" in url or "lens%20kit" in url


# ---------------------------------------------------------------------------
# Test 10 — latest without --repo is a CLI error (no network call)
# ---------------------------------------------------------------------------


def test_service_client_latest_requires_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    network_called: dict = {}

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        network_called["hit"] = True
        raise AssertionError("Network must not be called when --repo is missing")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    with pytest.raises(SystemExit) as exc_info:
        main(["service-client", "latest", "--json"])

    assert exc_info.value.code == 2
    assert "hit" not in network_called


# ---------------------------------------------------------------------------
# Test 11 — latest with --repo --level --mode builds correct URL
# ---------------------------------------------------------------------------


def test_service_client_latest_with_repo_level_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    fake_data = {"id": "art-abc", "repos": "repoground", "created_at": "2026-01-01"}
    captured, opener = _make_opener(fake_data)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(
        [
            "service-client",
            "latest",
            "--repo",
            "repoground",
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
    assert "repo=repoground" in url
    assert "level=max" in url
    assert "mode=gesamt" in url


# ---------------------------------------------------------------------------
# Test 12 — HTTP error → exit 1, JSON error envelope
# ---------------------------------------------------------------------------


def test_service_client_http_error_exit_1_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise urllib.error.HTTPError(
            url=None, code=500, msg="Internal Server Error", hdrs=None, fp=None
        )

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "health", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 1
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert parsed["error_kind"] == "remote_error"


# ---------------------------------------------------------------------------
# Test 13 — non-JSON response → exit 1, parse_error
# ---------------------------------------------------------------------------


def test_service_client_invalid_json_response_exit_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _make_bad_json_opener())

    rc = main(["service-client", "health", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 1
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert parsed["error_kind"] == "parse_error"


# ---------------------------------------------------------------------------
# Test 15 — request ValueError -> exit 1 remote_error + no token leak
# ---------------------------------------------------------------------------


def test_service_client_value_error_exit_1_no_token_leak(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("REPOGROUND_TOKEN", "my-secret-token")

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise ValueError("bad url my-secret-token")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "health", "--json"])
    out, err = capsys.readouterr()

    assert rc == 1
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert parsed["error_kind"] == "remote_error"
    assert "my-secret-token" not in out
    assert "my-secret-token" not in err


def test_service_client_invalid_base_url_scheme_rejected(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    network_called: dict = {}

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        network_called["hit"] = True
        raise AssertionError("Network must not be called for invalid base URL")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "health", "--base-url", "file:///etc/passwd", "--json"])
    out, err = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert parsed["error_kind"] == "config_error"
    assert "http://" in parsed["message"]
    assert "https://" in parsed["message"]
    assert "hit" not in network_called
    assert "file:///etc/passwd" not in out
    assert "file:///etc/passwd" not in err


def test_service_client_invalid_base_url_env_is_config_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    network_called: dict = {}
    monkeypatch.setenv("REPOGROUND_BASE_URL", "ftp://example.org")

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        network_called["hit"] = True
        raise AssertionError("Network must not be called for invalid env base URL")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "health", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert parsed["error_kind"] == "config_error"
    assert "hit" not in network_called


def test_redact_masks_bearer_token_even_without_explicit_token() -> None:
    msg = "Authorization failed: Bearer abc123.xyz"
    redacted = _mod._redact(msg, None)
    assert "abc123.xyz" not in redacted
    assert "Bearer [REDACTED]" in redacted


# ---------------------------------------------------------------------------
# jobs / job / logs (PR C scope)
# ---------------------------------------------------------------------------


class _FakeSSEResponse:
    """Iterable response stub for SSE streaming tests."""

    def __init__(self, lines: list) -> None:
        # Each entry should be a complete line ending in "\n" (bytes or str).
        self._lines = list(lines)
        self.closed = False

    def __iter__(self):
        return iter(self._lines)

    def close(self) -> None:
        self.closed = True


def _make_sse_opener(lines: list):
    captured: dict = {}

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> _FakeSSEResponse:
        captured["req"] = req
        captured["timeout"] = timeout
        resp = _FakeSSEResponse(lines)
        captured["resp"] = resp
        return resp

    return captured, _urlopen


def test_service_client_jobs_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    fake_data = [
        {"id": "j1", "status": "running", "created_at": "2026-01-01T00:00:00Z"},
        {"id": "j2", "status": "succeeded", "created_at": "2026-01-02T00:00:00Z"},
    ]
    captured, opener = _make_opener(fake_data)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "jobs", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 0
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert parsed[0]["id"] == "j1"
    assert captured["req"].full_url.endswith("/api/jobs")


def test_service_client_jobs_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    fake_data = [
        {"id": "job-abc", "status": "running", "created_at": "2026-01-01"},
    ]
    _, opener = _make_opener(fake_data)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "jobs"])
    out, _ = capsys.readouterr()

    assert rc == 0
    assert "job-abc" in out
    assert "running" in out


def test_service_client_jobs_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _, opener = _make_opener([])
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "jobs"])
    out, _ = capsys.readouterr()

    assert rc == 0
    assert "No jobs" in out


def test_service_client_jobs_status_and_limit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    captured, opener = _make_opener([])
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "jobs", "--status", "running", "--limit", "3", "--json"])
    capsys.readouterr()

    assert rc == 0
    url = captured["req"].full_url
    assert "/api/jobs" in url
    assert "status=running" in url
    assert "limit=3" in url


def test_service_client_job_by_id_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    fake_data = {
        "id": "job-xyz",
        "status": "succeeded",
        "created_at": "2026-01-01",
        "artifact_ids": ["art-1", "art-2"],
    }
    captured, opener = _make_opener(fake_data)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "job", "job-xyz", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 0
    parsed = json.loads(out)
    assert parsed["id"] == "job-xyz"
    assert captured["req"].full_url.endswith("/api/jobs/job-xyz")


def test_service_client_job_by_id_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    fake_data = {
        "id": "job-xyz",
        "status": "failed",
        "created_at": "2026-01-01",
        "started_at": "2026-01-01T00:01:00Z",
        "finished_at": "2026-01-01T00:02:00Z",
        "hub_resolved": "/some/hub",
        "artifact_ids": ["art-1"],
        "error": "boom",
        "warnings": ["w1", "w2"],
    }
    _, opener = _make_opener(fake_data)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "job", "job-xyz"])
    out, _ = capsys.readouterr()

    assert rc == 0
    assert "job-xyz" in out
    assert "failed" in out
    assert "art-1" in out
    assert "boom" in out
    assert "w1" in out
    assert "w2" in out


def test_service_client_job_id_is_url_encoded(monkeypatch: pytest.MonkeyPatch) -> None:
    captured, opener = _make_opener({"id": "x"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "job", "job id/with weird", "--json"])

    assert rc == 0
    # Path segment must not contain raw spaces or slashes.
    url = captured["req"].full_url
    assert " " not in url.split("?")[0]
    assert "/api/jobs/" in url
    assert url.split("/api/jobs/", 1)[1].rstrip("?&").count("/") == 0


def test_service_client_job_missing_id_is_cli_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called when job_id is missing")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    with pytest.raises(SystemExit) as exc_info:
        main(["service-client", "job"])
    assert exc_info.value.code == 2


def test_service_client_job_http_404_no_token_leak(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("REPOGROUND_TOKEN", "shhh-secret")

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise urllib.error.HTTPError(
            url=None, code=404, msg="Not Found", hdrs=None, fp=None
        )

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "job", "missing-id", "--json"])
    out, err = capsys.readouterr()

    assert rc == 1
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert "shhh-secret" not in out
    assert "shhh-secret" not in err


# ---------------------------------------------------------------------------
# run / cancel (PR E scope)
# ---------------------------------------------------------------------------


def _decode_request_json(req: urllib.request.Request) -> dict:
    raw = req.data or b"{}"
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return json.loads(raw.decode("utf-8"))


def test_service_client_run_posts_job_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    fake_data = {
        "id": "job-run-1",
        "status": "queued",
        "repos": ["repoground"],
        "hub_resolved": "/hub",
    }
    captured, opener = _make_opener(fake_data)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(
        [
            "service-client",
            "run",
            "--repo",
            "repoground",
            "--level",
            "max",
            "--mode",
            "gesamt",
            "--json",
        ]
    )
    out, _ = capsys.readouterr()

    assert rc == 0
    parsed = json.loads(out)
    assert parsed["id"] == "job-run-1"
    req = captured["req"]
    assert req.get_method() == "POST"
    assert req.get_header("Content-type") == "application/json"
    _assert_request_url(req, scheme="http", netloc="127.0.0.1:8787", path="/api/jobs")
    payload = _decode_request_json(req)
    # pre_pull defaults to True and is always sent explicitly.
    assert payload == {"repos": ["repoground"], "level": "max", "mode": "gesamt", "pre_pull": True}


def test_service_client_run_defaults_pre_pull_true(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    captured, opener = _make_opener({"id": "job-pp", "status": "queued"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "run", "--repo", "repoground", "--json"])
    capsys.readouterr()

    assert rc == 0
    payload = _decode_request_json(captured["req"])
    assert payload["pre_pull"] is True


def test_service_client_run_no_pre_pull_sends_false(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    captured, opener = _make_opener({"id": "job-pp2", "status": "queued"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "run", "--repo", "repoground", "--no-pre-pull", "--json"])
    capsys.readouterr()

    assert rc == 0
    payload = _decode_request_json(captured["req"])
    assert payload["pre_pull"] is False
    # Other options remain untouched.
    assert payload["repos"] == ["repoground"]
    assert "force_new" not in payload


def test_service_client_run_plan_only_sends_pre_pull_false(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    captured, opener = _make_opener({"id": "job-po", "status": "queued"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "run", "--repo", "repoground", "--plan-only", "--json"])
    capsys.readouterr()

    assert rc == 0
    payload = _decode_request_json(captured["req"])
    # plan_only never mutates local repos, so effective pre_pull is false.
    assert payload["plan_only"] is True
    assert payload["pre_pull"] is False


def test_service_client_run_plan_only_with_pre_pull_is_rejected(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called for --plan-only --pre-pull")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "run", "--repo", "repoground", "--plan-only", "--pre-pull", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert parsed["error_kind"] == "config_error"
    assert "mutually exclusive" in parsed["message"]


def test_service_client_run_pre_pull_and_no_pre_pull_are_mutually_exclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called on argparse error")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    with pytest.raises(SystemExit) as exc_info:
        main(["service-client", "run", "--repo", "repoground", "--pre-pull", "--no-pre-pull"])
    assert exc_info.value.code == 2


def test_service_client_run_repeated_repo_force_new_and_plan_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    captured, opener = _make_opener({"id": "job-run-2", "status": "queued"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(
        [
            "service-client",
            "run",
            "--repo",
            "repoground",
            "--repo",
            "metarepo",
            "--hub",
            "/tmp/hub",
            "--merges-dir",
            "/tmp/merges",
            "--force-new",
            "--plan-only",
            "--json",
        ]
    )
    capsys.readouterr()

    assert rc == 0
    payload = _decode_request_json(captured["req"])
    assert payload["repos"] == ["repoground", "metarepo"]
    assert payload["hub"] == "/tmp/hub"
    assert payload["merges_dir"] == "/tmp/merges"
    assert payload["force_new"] is True
    assert payload["plan_only"] is True
    assert payload["level"] == "dev"
    assert payload["mode"] == "gesamt"


# ---------------------------------------------------------------------------
# run --source-mode (RepoGround service source acquisition)
# ---------------------------------------------------------------------------


def test_service_client_run_remote_snapshot_payload(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    captured, opener = _make_opener({"id": "job-rs", "status": "queued"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "run", "--repo", "weltgewebe", "--source-mode", "remote-snapshot", "--json"])
    capsys.readouterr()

    assert rc == 0
    payload = _decode_request_json(captured["req"])
    assert payload["repo_source_mode"] == "remote_snapshot"
    assert payload["remote_ref_policy"] == "upstream"
    assert payload["pre_pull"] is False
    assert "remote_ref" not in payload


def test_service_client_run_remote_snapshot_default_branch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    captured, opener = _make_opener({"id": "job-db", "status": "queued"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main([
        "service-client", "run", "--repo", "weltgewebe",
        "--source-mode", "remote-snapshot", "--remote-ref-policy", "default-branch", "--json",
    ])
    capsys.readouterr()

    assert rc == 0
    payload = _decode_request_json(captured["req"])
    assert payload["repo_source_mode"] == "remote_snapshot"
    assert payload["remote_ref_policy"] == "default_branch"


def test_service_client_run_remote_snapshot_explicit_ref(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    captured, opener = _make_opener({"id": "job-er", "status": "queued"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main([
        "service-client", "run", "--repo", "weltgewebe",
        "--source-mode", "remote-snapshot", "--remote-ref", "origin/main", "--json",
    ])
    capsys.readouterr()

    assert rc == 0
    payload = _decode_request_json(captured["req"])
    assert payload["remote_ref"] == "origin/main"


def test_service_client_run_local_current_payload(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    captured, opener = _make_opener({"id": "job-lc", "status": "queued"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "run", "--repo", "repoground", "--source-mode", "local-current", "--json"])
    capsys.readouterr()

    assert rc == 0
    payload = _decode_request_json(captured["req"])
    assert payload["repo_source_mode"] == "local_current"
    assert payload["pre_pull"] is False
    assert "remote_ref_policy" not in payload


def test_service_client_run_plan_only_remote_snapshot_allowed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    captured, opener = _make_opener({"id": "job-po-rs", "status": "queued"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main([
        "service-client", "run", "--repo", "weltgewebe",
        "--source-mode", "remote-snapshot", "--plan-only", "--json",
    ])
    capsys.readouterr()

    assert rc == 0
    payload = _decode_request_json(captured["req"])
    assert payload["plan_only"] is True
    assert payload["repo_source_mode"] == "remote_snapshot"
    assert payload["pre_pull"] is False


def test_service_client_run_source_mode_pre_pull_conflicts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called on a source-mode conflict")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    for argv in (
        ["service-client", "run", "--repo", "r", "--source-mode", "local-current", "--pre-pull", "--json"],
        ["service-client", "run", "--repo", "r", "--source-mode", "local-ff", "--no-pre-pull", "--json"],
        ["service-client", "run", "--repo", "r", "--source-mode", "remote-snapshot", "--pre-pull", "--json"],
    ):
        rc = main(argv)
        out, _ = capsys.readouterr()
        assert rc == 2, argv
        parsed = json.loads(out)
        assert parsed["error_kind"] == "config_error"


@pytest.mark.parametrize(
    "argv",
    [
        # local-ff + plan-only: local-ff would mutate, plan-only forbids mutation.
        ["service-client", "run", "--repo", "r", "--source-mode", "local-ff", "--plan-only", "--json"],
        # remote-ref without remote-snapshot.
        ["service-client", "run", "--repo", "r", "--remote-ref", "origin/main", "--json"],
        ["service-client", "run", "--repo", "r", "--source-mode", "local-current", "--remote-ref", "origin/main", "--json"],
        ["service-client", "run", "--repo", "r", "--source-mode", "local-ff", "--remote-ref", "origin/main", "--json"],
        # explicit non-default policy without remote-snapshot.
        ["service-client", "run", "--repo", "r", "--remote-ref-policy", "default-branch", "--json"],
        ["service-client", "run", "--repo", "r", "--source-mode", "local-current", "--remote-ref-policy", "default-branch", "--json"],
    ],
)
def test_service_client_run_source_mode_conflicts_exit_2_no_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, argv
) -> None:
    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called on a source-mode conflict")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(argv)
    out, _ = capsys.readouterr()
    assert rc == 2, argv
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert parsed["error_kind"] == "config_error"


def test_service_client_run_remote_snapshot_explicit_policy_allowed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # The same non-default policy is fine *with* remote-snapshot.
    captured, opener = _make_opener({"id": "job-ok", "status": "queued"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main([
        "service-client", "run", "--repo", "r",
        "--source-mode", "remote-snapshot", "--remote-ref-policy", "default-branch", "--json",
    ])
    capsys.readouterr()
    assert rc == 0
    payload = _decode_request_json(captured["req"])
    assert payload["remote_ref_policy"] == "default_branch"


def test_service_client_run_text_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _, opener = _make_opener(
        {
            "id": "job-run-text",
            "status": "queued",
            "repos": ["repoground", "metarepo"],
            "hub_resolved": "/hub",
        }
    )
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "run", "--repo", "repoground"])
    out, _ = capsys.readouterr()

    assert rc == 0
    assert "job-run-text" in out
    assert "queued" in out
    assert "repoground" in out
    assert "/hub" in out


def test_service_client_run_sets_bearer_header_and_no_query_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPOGROUND_TOKEN", "run-secret")
    captured, opener = _make_opener({"id": "job-run-token", "status": "queued"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "run", "--repo", "repoground", "--json"])

    assert rc == 0
    assert captured["req"].get_header("Authorization") == "Bearer run-secret"
    assert "run-secret" not in captured["req"].full_url


def test_service_client_run_http_error_exit_1_no_token_leak(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("REPOGROUND_TOKEN", "run-secret")

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise urllib.error.HTTPError(
            url=None, code=500, msg="Internal Server Error", hdrs=None, fp=None
        )

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "run", "--repo", "repoground", "--json"])
    out, err = capsys.readouterr()

    assert rc == 1
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert parsed["error_kind"] == "remote_error"
    assert "run-secret" not in out
    assert "run-secret" not in err


def test_service_client_cancel_posts_to_url_encoded_job_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    captured, opener = _make_opener({"status": "canceling"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "cancel", "job id/with weird", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 0
    parsed = json.loads(out)
    assert parsed["status"] == "canceling"
    req = captured["req"]
    assert req.get_method() == "POST"
    assert " " not in req.full_url.split("?")[0]
    assert "/api/jobs/" in req.full_url
    suffix = req.full_url.split("/api/jobs/", 1)[1]
    assert suffix.endswith("/cancel")
    assert suffix[: -len("/cancel")].count("/") == 0


def test_service_client_cancel_text_finished_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _, opener = _make_opener({"status": "succeeded", "message": "Job already finished"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "cancel", "job-done"])
    out, _ = capsys.readouterr()

    assert rc == 0
    assert "succeeded" in out
    assert "Job already finished" in out


def test_service_client_cancel_sets_bearer_header_and_no_query_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPOGROUND_TOKEN", "cancel-secret")
    captured, opener = _make_opener({"status": "canceling"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "cancel", "job-1", "--json"])

    assert rc == 0
    assert captured["req"].get_header("Authorization") == "Bearer cancel-secret"
    assert "cancel-secret" not in captured["req"].full_url


def test_service_client_cancel_http_404_no_token_leak(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("REPOGROUND_TOKEN", "cancel-secret")

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise urllib.error.HTTPError(
            url=None, code=404, msg="Not Found", hdrs=None, fp=None
        )

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "cancel", "missing-id", "--json"])
    out, err = capsys.readouterr()

    assert rc == 1
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert parsed["error_kind"] == "remote_error"
    assert "cancel-secret" not in out
    assert "cancel-secret" not in err


def test_service_client_logs_text_streams_data_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    lines = [
        b"id: 1\n",
        b"data: hello\n",
        b"\n",
        b"id: 2\n",
        b"data: world\n",
        b"\n",
        b"event: end\n",
        b"data: end\n",
        b"\n",
    ]
    captured, opener = _make_sse_opener(lines)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "logs", "job-1"])
    out, _ = capsys.readouterr()

    assert rc == 0
    assert "hello" in out
    assert "world" in out
    # "end" SSE marker must not leak into text output.
    assert "event: end" not in out
    assert captured["req"].get_header("Accept") == "text/event-stream"
    assert captured["resp"].closed is True


def test_service_client_logs_json_emits_one_object_per_event(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    lines = [
        b"id: 1\n",
        b"data: line-a\n",
        b"\n",
        b"id: 2\n",
        b"data: line-b\n",
        b"\n",
        b"event: end\n",
        b"data: end\n",
        b"\n",
    ]
    _, opener = _make_sse_opener(lines)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "logs", "job-1", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 0
    objs = [json.loads(line) for line in out.strip().splitlines() if line.strip()]
    assert len(objs) == 2
    assert objs[0]["data"] == "line-a"
    assert objs[0]["id"] == "1"
    assert objs[1]["data"] == "line-b"


def test_service_client_logs_stops_on_event_end(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # Anything after event: end must not appear in output.
    lines = [
        b"id: 1\n",
        b"data: keep\n",
        b"\n",
        b"event: end\n",
        b"data: end\n",
        b"\n",
        b"id: 2\n",
        b"data: should-not-appear\n",
        b"\n",
    ]
    _, opener = _make_sse_opener(lines)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "logs", "job-1"])
    out, _ = capsys.readouterr()

    assert rc == 0
    assert "keep" in out
    assert "should-not-appear" not in out


def test_service_client_logs_passes_last_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    lines = [b"event: end\n", b"data: end\n", b"\n"]
    captured, opener = _make_sse_opener(lines)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "logs", "job-1", "--last-id", "7"])
    capsys.readouterr()

    assert rc == 0
    url = captured["req"].full_url
    assert "last_id=7" in url


def test_service_client_logs_multiline_data(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # Per SSE spec, multiple data: lines in a single event concatenate with newline.
    lines = [
        b"id: 1\n",
        b"data: first\n",
        b"data: second\n",
        b"\n",
        b"event: end\n",
        b"data: end\n",
        b"\n",
    ]
    _, opener = _make_sse_opener(lines)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "logs", "job-1"])
    out, _ = capsys.readouterr()

    assert rc == 0
    assert "first\nsecond" in out


def test_service_client_logs_ignores_comment_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    lines = [
        b":heartbeat\n",
        b"id: 1\n",
        b"data: alive\n",
        b"\n",
        b"event: end\n",
        b"data: end\n",
        b"\n",
    ]
    _, opener = _make_sse_opener(lines)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "logs", "job-1"])
    out, _ = capsys.readouterr()

    assert rc == 0
    assert "heartbeat" not in out
    assert "alive" in out


def test_service_client_logs_handles_http_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("REPOGROUND_TOKEN", "stream-secret")

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise urllib.error.HTTPError(
            url=None, code=400, msg="Bad Request", hdrs=None, fp=None
        )

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "logs", "job-1", "--json"])
    out, err = capsys.readouterr()

    assert rc == 1
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert parsed["error_kind"] == "remote_error"
    assert "stream-secret" not in out
    assert "stream-secret" not in err


def test_service_client_logs_token_redacted_in_data(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("REPOGROUND_TOKEN", "log-secret")
    lines = [
        b"id: 1\n",
        b"data: echoing log-secret in line\n",
        b"\n",
        b"event: end\n",
        b"data: end\n",
        b"\n",
    ]
    _, opener = _make_sse_opener(lines)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "logs", "job-1"])
    out, _ = capsys.readouterr()

    assert rc == 0
    assert "log-secret" not in out
    assert "[REDACTED]" in out


def test_service_client_logs_sets_bearer_header_and_no_query_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPOGROUND_TOKEN", "bearer-token")
    lines = [b"event: end\n", b"data: end\n", b"\n"]
    captured, opener = _make_sse_opener(lines)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "logs", "job-1"])

    assert rc == 0
    assert captured["req"].get_header("Authorization") == "Bearer bearer-token"
    assert "bearer-token" not in captured["req"].full_url


def test_service_client_logs_stream_without_end_event_still_succeeds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # Server may close the stream without an explicit event: end.
    # MVP: that's not an error.
    lines = [
        b"id: 1\n",
        b"data: only\n",
        b"\n",
    ]
    _, opener = _make_sse_opener(lines)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "logs", "job-1"])
    out, _ = capsys.readouterr()

    assert rc == 0
    assert "only" in out


def test_service_client_logs_json_redacts_token_in_data(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("REPOGROUND_TOKEN", "json-secret")
    lines = [
        b"id: 1\n",
        b"data: json-secret appears\n",
        b"\n",
        b"event: end\n",
        b"data: end\n",
        b"\n",
    ]
    _, opener = _make_sse_opener(lines)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "logs", "job-1", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 0
    assert "json-secret" not in out
    objs = [json.loads(line) for line in out.strip().splitlines() if line.strip()]
    assert len(objs) == 1
    assert "[REDACTED]" in objs[0]["data"]


def test_service_client_jobs_negative_limit_is_config_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called for invalid limit")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "jobs", "--limit", "-1", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert parsed["error_kind"] == "config_error"


@pytest.mark.parametrize("timeout_value", ["0", "-1"])
def test_service_client_logs_timeout_non_positive_is_config_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    timeout_value: str,
) -> None:
    monkeypatch.setenv("REPOGROUND_TOKEN", "timeout-secret")

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called for invalid --timeout")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(
        ["service-client", "logs", "job-1", "--timeout", timeout_value, "--json"]
    )
    out, err = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert parsed["error_kind"] == "config_error"
    assert "timeout-secret" not in out
    assert "timeout-secret" not in err


def test_service_client_logs_last_id_negative_is_passed_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # --last-id negative values are intentionally forwarded; server clamps to 0.
    lines = [b"event: end\n", b"data: end\n", b"\n"]
    captured, opener = _make_sse_opener(lines)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "logs", "job-1", "--last-id", "-5"])

    assert rc == 0
    assert "last_id=-5" in captured["req"].full_url


# ---------------------------------------------------------------------------
# Host profiles (PR D scope)
# ---------------------------------------------------------------------------


def _write_profiles(tmp_path: pathlib.Path, payload: object) -> pathlib.Path:
    config = tmp_path / "repoground-profiles.json"
    config.write_text(json.dumps(payload), encoding="utf-8")
    return config


def _isolate_profile_env(monkeypatch: pytest.MonkeyPatch, config: pathlib.Path) -> None:
    monkeypatch.setenv("REPOGROUND_PROFILES", str(config))
    monkeypatch.delenv("REPOGROUND_BASE_URL", raising=False)
    monkeypatch.delenv("REPOGROUND_TOKEN", raising=False)
    monkeypatch.delenv("REPOGROUND_PROFILE", raising=False)


def test_service_client_profile_provides_base_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {
            "heim-pc": {"base_url": "http://heim-pc:8787"},
        },
    })
    _isolate_profile_env(monkeypatch, config)

    captured, opener = _make_opener({"status": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "health", "--profile", "heim-pc", "--json"])

    assert rc == 0
    _assert_request_url(captured["req"], scheme="http", netloc="heim-pc:8787", path="/api/health")


def test_service_client_profile_via_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {
            "lab": {"base_url": "http://lab.example:8787"},
        },
    })
    _isolate_profile_env(monkeypatch, config)
    monkeypatch.setenv("REPOGROUND_PROFILE", "lab")

    captured, opener = _make_opener({"status": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "health", "--json"])

    assert rc == 0
    _assert_request_url(captured["req"], scheme="http", netloc="lab.example:8787", path="/api/health")


def test_service_client_default_profile_used_when_no_selection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    config = _write_profiles(tmp_path, {
        "default_profile": "heimserver",
        "profiles": {
            "heimserver": {"base_url": "http://heimserver:8787"},
            "other": {"base_url": "http://other:8787"},
        },
    })
    _isolate_profile_env(monkeypatch, config)

    captured, opener = _make_opener({"status": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "health", "--json"])

    assert rc == 0
    _assert_request_url(captured["req"], scheme="http", netloc="heimserver:8787", path="/api/health")


def test_service_client_base_url_flag_beats_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {"heim-pc": {"base_url": "http://heim-pc:8787"}},
    })
    _isolate_profile_env(monkeypatch, config)

    captured, opener = _make_opener({"status": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main([
        "service-client", "health",
        "--profile", "heim-pc",
        "--base-url", "http://override:8787",
        "--json",
    ])

    assert rc == 0
    _assert_request_url(captured["req"], scheme="http", netloc="override:8787", path="/api/health")


def test_service_client_env_base_url_beats_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {"heim-pc": {"base_url": "http://heim-pc:8787"}},
    })
    _isolate_profile_env(monkeypatch, config)
    monkeypatch.setenv("REPOGROUND_BASE_URL", "http://env-wins:8787")

    captured, opener = _make_opener({"status": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "health", "--profile", "heim-pc", "--json"])

    assert rc == 0
    _assert_request_url(captured["req"], scheme="http", netloc="env-wins:8787", path="/api/health")


def test_service_client_profile_token_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {
            "heim-pc": {
                "base_url": "http://heim-pc:8787",
                "token_env": "REPOGROUND_TOKEN_HEIM_PC",
            },
        },
    })
    _isolate_profile_env(monkeypatch, config)
    monkeypatch.setenv("REPOGROUND_TOKEN_HEIM_PC", "profile-token-value")

    captured, opener = _make_opener({"status": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "health", "--profile", "heim-pc", "--json"])

    assert rc == 0
    auth = captured["req"].get_header("Authorization")
    assert auth == "Bearer profile-token-value"
    assert "profile-token-value" not in captured["req"].full_url


def test_service_client_token_flag_beats_profile_token_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {
            "heim-pc": {
                "base_url": "http://heim-pc:8787",
                "token_env": "REPOGROUND_TOKEN_HEIM_PC",
            },
        },
    })
    _isolate_profile_env(monkeypatch, config)
    monkeypatch.setenv("REPOGROUND_TOKEN_HEIM_PC", "profile-token-value")

    captured, opener = _make_opener({"status": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main([
        "service-client", "health",
        "--profile", "heim-pc",
        "--token", "cli-token",
        "--json",
    ])

    assert rc == 0
    assert captured["req"].get_header("Authorization") == "Bearer cli-token"


def test_service_client_unknown_profile_is_config_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {"local": {"base_url": "http://127.0.0.1:8787"}},
    })
    _isolate_profile_env(monkeypatch, config)

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called for unknown profile")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "health", "--profile", "nope", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["error_kind"] == "config_error"
    assert "nope" in parsed["message"]


def test_service_client_profile_unknown_even_with_base_url_override_is_config_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {"local": {"base_url": "http://127.0.0.1:8787"}},
    })
    _isolate_profile_env(monkeypatch, config)

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called for unknown profile")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main([
        "service-client", "health",
        "--base-url", "http://override:8787",
        "--profile", "nope",
        "--json",
    ])
    out, _ = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["error_kind"] == "config_error"
    assert "nope" in parsed["message"]


def test_service_client_profile_requested_but_no_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    missing = tmp_path / "missing-profiles.json"
    _isolate_profile_env(monkeypatch, missing)

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called when explicit profile is missing")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "health", "--profile", "heim-pc", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["error_kind"] == "config_error"


def test_service_client_profile_default_profile_non_string_is_config_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config = _write_profiles(tmp_path, {
        "default_profile": 42,
        "profiles": {"x": {"base_url": "http://x:8787"}},
    })
    _isolate_profile_env(monkeypatch, config)

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called for invalid config")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "health", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["error_kind"] == "config_error"
    assert "default_profile" in parsed["message"]


def test_service_client_no_config_no_profile_uses_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    # If no profile is requested and no config exists, fall back to default URL.
    missing = tmp_path / "missing-profiles.json"
    _isolate_profile_env(monkeypatch, missing)

    captured, opener = _make_opener({"status": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "health", "--json"])

    assert rc == 0
    _assert_request_url(captured["req"], scheme="http", netloc="127.0.0.1:8787", path="/api/health")


def test_service_client_invalid_profile_config_without_profile_is_config_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {"naughty": {"base_url": "http://x:8787", "garbage": "x"}},
    })
    _isolate_profile_env(monkeypatch, config)

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called for invalid config")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "health", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["error_kind"] == "config_error"
    assert "garbage" in parsed["message"]


def test_service_client_invalid_profile_config_with_token_override_is_config_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {"bad": {"base_url": "http://x:8787", "token": "super-secret"}},
    })
    _isolate_profile_env(monkeypatch, config)

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called for invalid profile config")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "health", "--token", "cli-token", "--json"])
    out, err = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["error_kind"] == "config_error"
    assert "super-secret" not in out
    assert "super-secret" not in err


def test_service_client_invalid_profile_config_with_env_token_is_config_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {"bad": {"base_url": "http://x:8787", "garbage": "x"}},
    })
    _isolate_profile_env(monkeypatch, config)
    monkeypatch.setenv("REPOGROUND_TOKEN", "env-token")

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called for invalid profile config")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "health", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["error_kind"] == "config_error"
    assert "garbage" in parsed["message"]


def test_service_client_invalid_profile_config_with_base_url_override_is_config_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {"bad": {"base_url": "http://x:8787", "garbage": "x"}},
    })
    _isolate_profile_env(monkeypatch, config)

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called for invalid profile config")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "health", "--base-url", "http://override:8787", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["error_kind"] == "config_error"
    assert "garbage" in parsed["message"]


def test_service_client_profile_with_token_field_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    # Hard security invariant: profile files must NEVER contain raw secrets.
    config = _write_profiles(tmp_path, {
        "profiles": {
            "bad": {
                "base_url": "http://x:8787",
                "token": "secret-in-config",
            },
        },
    })
    _isolate_profile_env(monkeypatch, config)

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called when profile is invalid")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "health", "--profile", "bad", "--json"])
    out, err = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["error_kind"] == "config_error"
    assert "secret-in-config" not in out
    assert "secret-in-config" not in err


def test_service_client_profile_forbidden_key_even_with_base_url_override_is_config_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {
            "bad": {
                "base_url": "http://x:8787",
                "token": "secret-in-config",
            },
        },
    })
    _isolate_profile_env(monkeypatch, config)

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called when profile is invalid")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main([
        "service-client", "health",
        "--profile", "bad",
        "--base-url", "http://override:8787",
        "--json",
    ])
    out, err = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["error_kind"] == "config_error"
    assert "secret-in-config" not in out
    assert "secret-in-config" not in err


def test_service_client_profile_unknown_key_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {"x": {"base_url": "http://x:8787", "garbage": "yes"}},
    })
    _isolate_profile_env(monkeypatch, config)

    rc = main(["service-client", "health", "--profile", "x", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["error_kind"] == "config_error"
    assert "garbage" in parsed["message"]


def test_service_client_profile_invalid_base_url_is_config_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {"bad": {"base_url": "ftp://nope"}},
    })
    _isolate_profile_env(monkeypatch, config)

    def _urlopen(req: urllib.request.Request, timeout: object = None) -> None:
        raise AssertionError("Network must not be called for invalid base url")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    rc = main(["service-client", "health", "--profile", "bad", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["error_kind"] == "config_error"


def test_service_client_profile_malformed_json_is_config_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config = tmp_path / "repoground-profiles.json"
    config.write_text("this is not json {", encoding="utf-8")
    _isolate_profile_env(monkeypatch, config)

    rc = main(["service-client", "health", "--profile", "x", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["error_kind"] == "config_error"


def test_service_client_profiles_subcommand_lists_profiles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    config = _write_profiles(tmp_path, {
        "default_profile": "local",
        "profiles": {
            "local": {"base_url": "http://127.0.0.1:8787"},
            "heim-pc": {
                "base_url": "http://heim-pc:8787",
                "token_env": "REPOGROUND_TOKEN_HEIM_PC",
            },
        },
    })
    _isolate_profile_env(monkeypatch, config)

    rc = main(["service-client", "profiles", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 0
    parsed = json.loads(out)
    assert parsed["exists"] is True
    assert parsed["default_profile"] == "local"
    assert parsed["profiles"]["heim-pc"]["base_url"] == "http://heim-pc:8787"
    assert parsed["profiles"]["heim-pc"]["token_env"] == "REPOGROUND_TOKEN_HEIM_PC"


def test_service_client_profiles_subcommand_no_secret_leak(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {
            "naughty": {
                "base_url": "http://x:8787",
                "token_env": "REPOGROUND_TOKEN_X",
            }
        }
    })
    _isolate_profile_env(monkeypatch, config)

    rc = main(["service-client", "profiles", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 0
    assert "REPOGROUND_TOKEN_X" in out
    assert "secret" not in out


def test_service_client_profiles_subcommand_unknown_key_is_config_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {"naughty": {"base_url": "http://x:8787", "garbage": "x"}},
    })
    _isolate_profile_env(monkeypatch, config)

    rc = main(["service-client", "profiles", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["error_kind"] == "config_error"
    assert "garbage" in parsed["message"]


def test_service_client_profiles_subcommand_forbidden_key_is_config_error_no_secret_leak(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {"naughty": {"base_url": "http://x:8787", "token": "super-secret"}},
    })
    _isolate_profile_env(monkeypatch, config)

    rc = main(["service-client", "profiles", "--json"])
    out, err = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["error_kind"] == "config_error"
    assert "super-secret" not in out
    assert "super-secret" not in err


def test_service_client_profile_base_url_invalid_scheme_rejected_by_profiles_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config = _write_profiles(tmp_path, {
        "profiles": {"naughty": {"base_url": "ftp://nope"}},
    })
    _isolate_profile_env(monkeypatch, config)

    rc = main(["service-client", "profiles", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["error_kind"] == "config_error"


def test_service_client_profiles_subcommand_no_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    missing = tmp_path / "missing.json"
    _isolate_profile_env(monkeypatch, missing)

    rc = main(["service-client", "profiles", "--json"])
    out, _ = capsys.readouterr()

    assert rc == 0
    parsed = json.loads(out)
    assert parsed["exists"] is False
    assert parsed["profiles"] == {}


def test_service_client_profile_xdg_config_home_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    # When REPOGROUND_PROFILES is not set, XDG_CONFIG_HOME is honored.
    monkeypatch.delenv("REPOGROUND_PROFILES", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("REPOGROUND_BASE_URL", raising=False)
    monkeypatch.delenv("REPOGROUND_TOKEN", raising=False)
    monkeypatch.delenv("REPOGROUND_PROFILE", raising=False)

    profile_dir = tmp_path / "repoground"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profiles.json").write_text(
        json.dumps({"profiles": {"x": {"base_url": "http://x:8787"}}}),
        encoding="utf-8",
    )

    captured, opener = _make_opener({"status": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    rc = main(["service-client", "health", "--profile", "x", "--json"])

    assert rc == 0
    _assert_request_url(captured["req"], scheme="http", netloc="x:8787", path="/api/health")


def test_service_client_profile_config_path_expands_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOGROUND_PROFILES", "~/repoground-profiles.json")
    path = _mod._profile_config_path()
    assert str(path).startswith(str(pathlib.Path.home()))
