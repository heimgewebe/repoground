"""
Manual benchmark / smoke test script for SSE stream performance.
Not intended as a deterministic performance test for CI.
"""
import asyncio
import time
import httpx
from merger.repoground.service.app import app, state, init_service
from merger.repoground.service.models import JobRequest, Job
import pathlib
from httpx import ASGITransport

async def test_sse_stream_overhead():
    # Setup test env
    hub_path = pathlib.Path("./benchmark_hub").resolve()
    hub_path.mkdir(exist_ok=True)
    init_service(hub_path=hub_path)

    job_id = "bench-job-1"
    req = JobRequest(repos=["repo-test"])

    job = Job.create(request=req)
    job.id = job_id
    state.job_store.add_job(job)

    async def simulate_job_activity():
        # Keep job running for a few seconds while we measure stream CPU usage
        for i in range(50):
            await asyncio.sleep(0.01)
            state.job_store.append_log_line(job_id, f"Line {i}")

        job.status = "succeeded"
        state.job_store.update_job(job)

    async def stream_logs():
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            t0 = time.perf_counter()
            line_count = 0
            async with client.stream("GET", f"/api/jobs/{job_id}/logs") as response:
                async for line in response.aiter_lines():
                    if line:
                        line_count += 1

            t1 = time.perf_counter()
            return t1 - t0, line_count

    print("Running stream benchmark...")
    t0 = time.perf_counter()

    t_job = asyncio.create_task(simulate_job_activity())
    duration, line_count = await stream_logs()
    await t_job

    t1 = time.perf_counter()
    print(f"Total time taken: {t1 - t0:.3f} seconds for {line_count} lines")

if __name__ == "__main__":
    asyncio.run(test_sse_stream_overhead())
