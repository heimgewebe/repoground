import hmac

from fastapi import HTTPException, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

from ..adapters.security import get_security_config

security_scheme = HTTPBearer(auto_error=False)


def _token_matches(candidate: Optional[str], expected: str) -> bool:
    # Constant-time comparison to avoid leaking the token via timing.
    if not candidate:
        return False
    return hmac.compare_digest(candidate, expected)


def verify_token(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    token: Optional[str] = Query(None)
):
    config = get_security_config()
    if not config.token:
        return

    # Bearer header is the preferred channel. The query parameter is retained
    # only for browser-native clients that cannot set headers (EventSource /
    # direct downloads).  Uvicorn's raw URL logger remains disabled and the
    # service's bounded access logger never reads the query string.
    if _token_matches(creds.credentials if creds else None, config.token):
        return

    if _token_matches(token, config.token):
        return

    raise HTTPException(status_code=401, detail="Missing or invalid authentication token")
