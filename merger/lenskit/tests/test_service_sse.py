

from merger.lenskit.service.models import Job, JobRequest

def test_sse_contract(service_client, monkeypatch):
    ctx = service_client

    # 1. Create a job manually in store
    # Use proper Pydantic construction
    job_id = "test-job-sse"
    req = JobRequest(repos=["repo-test"])

    # Manually construct Job to control state perfectly
    # Note: Job.create() sets status='queued'. We want 'succeeded' for deterministic end.
    job = Job(
        id=job_id,
        status="succeeded", # Important: ensures stream ends immediately after logs
        created_at="2024-01-01T00:00:00+00:00",
        request=req,
        hub_resolved=str(ctx.hub_path),
        logs=["line1", "line2", "line3"]
    )

    # Mock store retrieval.
    # We use monkeypatch to avoid global side effects.
    # Must mock 'get_job' and inject MockLogProvider.

    def fake_get_job(jid):
        if jid == job_id:
            return job
        return None

    monkeypatch.setattr(ctx.store, "get_job", fake_get_job)

    # Inject MockLogProvider
    from merger.lenskit.service.logging_provider import MockLogProvider
    mock_provider = MockLogProvider({job_id: job.logs})
    from merger.lenskit.service.app import state

    old_provider = state.log_provider
    state.log_provider = mock_provider

    try:
        url = f"/api/jobs/{job_id}/logs"

        # CASE 1: No last-id, start from 0
        with ctx.client.stream("GET", url, headers=ctx.headers) as response:
            lines = list(response.iter_lines())
            decoded = [l for l in lines if l]

            # Verify IDs and Data
            assert "id: 1" in decoded
            assert "data: line1" in decoded
            assert "id: 2" in decoded
            assert "data: line2" in decoded
            assert "id: 3" in decoded
            assert "data: line3" in decoded

            # Verify end event
            assert "event: end" in decoded
            assert "data: end" in decoded

        # CASE 2: Resume with Last-Event-ID header
        headers_resume = ctx.headers.copy()
        headers_resume["Last-Event-ID"] = "2"

        with ctx.client.stream("GET", url, headers=headers_resume) as response:
            lines = list(response.iter_lines())
            decoded = [l for l in lines if l]

            # Should start after ID 2
            assert "id: 1" not in decoded
            assert "id: 2" not in decoded

            assert "id: 3" in decoded
            assert "data: line3" in decoded
            assert "event: end" in decoded

        # CASE 3: Resume with query param
        with ctx.client.stream("GET", f"{url}?last_id=1", headers=ctx.headers) as response:
            lines = list(response.iter_lines())
            decoded = [l for l in lines if l]

            assert "id: 2" in decoded
            assert "id: 3" in decoded

        # CASE 4: Header overrides Query
        headers_resume["Last-Event-ID"] = "2"
        with ctx.client.stream("GET", f"{url}?last_id=0", headers=headers_resume) as response:
            lines = list(response.iter_lines())
            decoded = [l for l in lines if l]

            assert "id: 1" not in decoded
            assert "id: 2" not in decoded
            assert "id: 3" in decoded

    finally:
        # Restore provider
        state.log_provider = old_provider

def test_sse_edge_cases(service_client, monkeypatch):
    """
    Validates explicit edge-case handling for SSE.
    """
    ctx = service_client
    job_id = "test-job-sse-edge"
    req = JobRequest(repos=["repo-test"])

    # 3 lines of logs
    job = Job(
        id=job_id,
        status="succeeded",
        created_at="2024-01-01T00:00:00+00:00",
        request=req,
        hub_resolved=str(ctx.hub_path),
        logs=["line1", "line2", "line3"]
    )

    def fake_get_job(jid):
        if jid == job_id:
            return job
        return None

    monkeypatch.setattr(ctx.store, "get_job", fake_get_job)

    # Inject MockLogProvider
    from merger.lenskit.service.logging_provider import MockLogProvider
    mock_provider = MockLogProvider({job_id: job.logs})
    from merger.lenskit.service.app import state
    old_provider = state.log_provider
    state.log_provider = mock_provider

    try:
        url = f"/api/jobs/{job_id}/logs"

        # EDGE CASE 1: Last-Event-ID = garbage -> HTTP 400
        bad_headers = ctx.headers.copy()
        bad_headers["Last-Event-ID"] = "garbage-value"

        # Note: Using stream=True but checking status_code before iterating
        response = ctx.client.get(url, headers=bad_headers)
        assert response.status_code == 400
        assert "Invalid Last-Event-ID" in response.text

        # EDGE CASE 1.5: Last-Event-ID = negative -> Clamped to 0 (Success)
        neg_headers = ctx.headers.copy()
        neg_headers["Last-Event-ID"] = "-1"

        with ctx.client.stream("GET", url, headers=neg_headers) as response:
            lines = list(response.iter_lines())
            # Robust decode: iter_lines() might yield bytes or str depending on client/version
            decoded = [
                (l.decode("utf-8") if isinstance(l, (bytes, bytearray)) else l)
                for l in lines if l
            ]

            # Should start from beginning (clamped to 0)
            assert any(l.startswith("id: 1") for l in decoded)
            assert any(l.startswith("data: line1") for l in decoded)

        # EDGE CASE 2: Last-Event-ID > len(logs) -> event: end (no logs)
        headers_future = ctx.headers.copy()
        headers_future["Last-Event-ID"] = "100"

        with ctx.client.stream("GET", url, headers=headers_future) as response:
            lines = list(response.iter_lines())
            decoded = [l for l in lines if l]

            # No log data should be emitted
            assert not any("data: line" in l for l in decoded)
            # Should finish gracefully
            assert "event: end" in decoded

        # EDGE CASE 3: Reconnect after end -> event: end (no logs)
        # If we have 3 logs, requesting ID 3 means "I have 3, give me next".
        # Since there is no next and job is done, it should send end.
        headers_done = ctx.headers.copy()
        headers_done["Last-Event-ID"] = "3"

        with ctx.client.stream("GET", url, headers=headers_done) as response:
            lines = list(response.iter_lines())
            decoded = [l for l in lines if l]

            # Should not resend line 3
            assert not any("data: line" in l for l in decoded)
            assert "event: end" in decoded

        # EDGE CASE 4: last_id query param = negative -> Clamped to 0
        with ctx.client.stream("GET", f"{url}?last_id=-1", headers=ctx.headers) as response:
            lines = list(response.iter_lines())
            # Robust decode
            decoded = [
                (l.decode("utf-8") if isinstance(l, (bytes, bytearray)) else l)
                for l in lines if l
            ]

            # Should start from beginning
            assert any(l.startswith("id: 1") for l in decoded)
            assert any(l.startswith("data: line1") for l in decoded)

    finally:
        # Restore provider
        state.log_provider = old_provider
