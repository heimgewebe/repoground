# rLens credential-safe HTTP access log v1 — proof

Date: 2026-07-10

## Decision

Uvicorn's raw access log remains disabled because it formats the concrete request target and can therefore expose query-string credentials used by browser-native EventSource and direct-download clients.

rLens restores bounded operational visibility with a service-owned ASGI middleware. The middleware emits one compact JSON record containing only:

- event name `http_access`;
- bounded HTTP method;
- static route template after routing, for example `/jobs/{job_id}`;
- response status;
- elapsed milliseconds.

## Data-minimization boundary

The middleware does not read or serialize:

- the concrete URL path;
- query strings;
- request or response headers;
- authorization values;
- cookies;
- client addresses;
- request or response bodies;
- exception messages or tracebacks.

Unmatched requests use the constant route label `<unmatched>`. Dynamic path values are never copied into the record. Non-HTTP ASGI scopes pass through without access records. Logging failures are swallowed after the request so an observability backend cannot break a completed response.

## Proof surface

```text
python3 -m pytest -q \
  merger/lenskit/tests/test_safe_access_log.py \
  merger/lenskit/tests/test_rlens_server_security.py \
  merger/lenskit/tests/test_service_auth_hardening.py \
  merger/lenskit/tests/test_service_security.py \
  merger/lenskit/tests/test_service_hardening.py
```

The tests inject the same secret into the query string, Bearer header, cookie, body and dynamic path value, then assert it is absent from every emitted record. They also cover unmatched routes, exceptions, non-HTTP scopes, production middleware registration and a failing logging backend.

## Non-claims

A passing test does not establish that every external proxy, process supervisor or future middleware is credential-safe. It does not prove authentication correctness, intrusion detection, audit completeness, request attribution, service availability, test sufficiency or regression absence. The proof is limited to the rLens-owned middleware and launcher configuration on the reviewed revision.
