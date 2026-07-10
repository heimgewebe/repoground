from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
import pytest

from merger.lenskit.adapters.security import get_security_config
from merger.lenskit.service import auth


@pytest.fixture(autouse=True)
def restore_security_token():
    config = get_security_config()
    previous = config.token
    yield
    config.set_token(previous)


def test_token_matches_uses_constant_time_comparison(monkeypatch):
    calls = []

    def fake_compare_digest(candidate, expected):
        calls.append((candidate, expected))
        return candidate == expected

    monkeypatch.setattr(auth.hmac, "compare_digest", fake_compare_digest)

    assert auth._token_matches("candidate", "expected") is False
    assert calls == [("candidate", "expected")]


def test_verify_token_accepts_bearer_header():
    get_security_config().set_token("expected")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="expected")

    assert auth.verify_token(creds=credentials, token=None) is None


def test_verify_token_accepts_query_token_for_browser_native_clients():
    get_security_config().set_token("expected")

    assert auth.verify_token(creds=None, token="expected") is None


def test_verify_token_rejects_invalid_credentials():
    get_security_config().set_token("expected")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong")

    with pytest.raises(HTTPException) as exc_info:
        auth.verify_token(creds=credentials, token="also-wrong")

    assert exc_info.value.status_code == 401
