import asyncio

import httpx
import pytest
from httpx import ASGITransport

from merger.lenskit.service.app import app, init_service, state
from merger.lenskit.service.models import Job, JobRequest


@pytest.fixture
def lifecycle_env(tmp_path):
    init_service(hub_path=tmp_path)
    return tmp_path


async def _wait_for_subscription(job_id: str, *, present: bool = True) -> None:
    async def observed() -> None:
        while (state.job_store.log_subscriber_count(job_id) > 0) is not present:
            await asyncio.sleep(0)

    await asyncio.wait_for(observed(), timeout=2.0)


def _job(job_id: str) -> Job:
    job = Job.create(request=JobRequest(repos=[]))
    job.id = job_id
    state.job_store.add_job(job)
    return job


async def _stream(job_id: str, lines_received: list[str]) -> None:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        async with client.stream("GET", f"/api/jobs/{job_id}/logs") as response:
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "end":
                    break
                lines_received.append(data)


def _observe_log_reads(
    monkeypatch, expected_lines: set[str]
) -> dict[str, asyncio.Event]:
    events = {line: asyncio.Event() for line in expected_lines}
    original = state.job_store.read_log_chunk

    def observed(job_id: str, last_line_id: int):
        rows = original(job_id, last_line_id)
        for line, _line_id in rows:
            event = events.get(line)
            if event is not None:
                event.set()
        return rows

    monkeypatch.setattr(state.job_store, "read_log_chunk", observed)
    return events


@pytest.mark.asyncio
async def test_stream_wakes_on_appended_logs(lifecycle_env, monkeypatch):
    job_id = "test-wake"
    job = _job(job_id)
    lines_received: list[str] = []
    line_events = _observe_log_reads(monkeypatch, {"hello world 1", "hello world 2"})
    stream_task = asyncio.create_task(_stream(job_id, lines_received))

    await _wait_for_subscription(job_id)
    state.job_store.append_log_line(job_id, "hello world 1")
    await asyncio.wait_for(line_events["hello world 1"].wait(), timeout=2.0)
    state.job_store.append_log_line(job_id, "hello world 2")
    await asyncio.wait_for(line_events["hello world 2"].wait(), timeout=2.0)
    job.status = "succeeded"
    state.job_store.update_job(job)

    await asyncio.wait_for(stream_task, timeout=2.0)
    assert lines_received == ["hello world 1", "hello world 2"]


@pytest.mark.asyncio
async def test_stream_ends_on_terminal_status(lifecycle_env):
    job_id = "test-term"
    job = _job(job_id)
    state.job_store.append_log_line(job_id, "start")
    lines_received: list[str] = []
    stream_task = asyncio.create_task(_stream(job_id, lines_received))

    await _wait_for_subscription(job_id)
    job.status = "failed"
    state.job_store.update_job(job)

    await asyncio.wait_for(stream_task, timeout=2.0)
    assert lines_received == ["start"]
    await _wait_for_subscription(job_id, present=False)


@pytest.mark.asyncio
async def test_stream_exits_on_job_removal(lifecycle_env):
    job_id = "test-remove"
    _job(job_id)
    lines_received: list[str] = []
    stream_task = asyncio.create_task(_stream(job_id, lines_received))

    await _wait_for_subscription(job_id)
    state.job_store.remove_job(job_id)

    await asyncio.wait_for(stream_task, timeout=2.0)
    assert lines_received == []
    assert state.job_store.log_subscriber_count(job_id) == 0


@pytest.mark.asyncio
async def test_stream_idle_timeout_path(lifecycle_env, monkeypatch):
    import merger.lenskit.service.app

    job_id = "test-idle"
    job = _job(job_id)
    monkeypatch.setattr(merger.lenskit.service.app, "SSE_IDLE_RECHECK_SEC", 0.01)
    lines_received: list[str] = []
    line_events = _observe_log_reads(monkeypatch, {"survived idle"})
    stream_task = asyncio.create_task(_stream(job_id, lines_received))

    await _wait_for_subscription(job_id)
    await asyncio.sleep(0.03)
    state.job_store.append_log_line(job_id, "survived idle")
    await asyncio.wait_for(line_events["survived idle"].wait(), timeout=2.0)
    job.status = "succeeded"
    state.job_store.update_job(job)

    await asyncio.wait_for(stream_task, timeout=2.0)
    assert lines_received == ["survived idle"]
