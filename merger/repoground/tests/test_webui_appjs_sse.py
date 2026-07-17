"""Static regression tests for the rLens webui app.js SSE end-event fix.

These checks verify that the correct EventSource API is used to handle
the named SSE 'end' event emitted by the backend. No browser/JS runtime needed.
"""
import os
import re

APP_JS = os.path.join(
    os.path.dirname(__file__),
    "..", "frontends", "webui", "app.js"
)


def _load_appjs() -> str:
    with open(APP_JS, encoding="utf-8") as f:
        return f.read()


def test_appjs_has_named_end_listener():
    """app.js must handle the named SSE 'end' event via addEventListener."""
    src = _load_appjs()
    assert 'addEventListener("end"' in src or "addEventListener('end'" in src, (
        "streamLogs() must use es.addEventListener('end', ...) to handle the named SSE end event. "
        "onmessage does not fire for named events."
    )


def test_appjs_onmessage_has_no_data_end_guard():
    """onmessage must no longer check event.data === 'end' as the sole end-path."""
    src = _load_appjs()
    # The old pattern was the only termination path inside onmessage
    assert "event.data === 'end'" not in src and 'event.data === "end"' not in src, (
        "onmessage must not check event.data === 'end'. "
        "The 'end' event is a named SSE event and is not delivered to onmessage."
    )


def test_appjs_stream_closed_guard_present():
    """A re-entrance guard (streamClosed) must prevent duplicate end/error messages."""
    src = _load_appjs()
    assert "streamClosed" in src, (
        "streamLogs() must declare a streamClosed flag (or equivalent closeStream helper) "
        "to prevent onerror from appending '[Connection Lost]' after an intentional close."
    )


def test_appjs_load_artifacts_called_on_end():
    """loadArtifacts() must be called after the stream ends."""
    src = _load_appjs()
    # Find the addEventListener("end") block
    match = re.search(
        r'addEventListener\(["\']end["\'].*?loadArtifacts\(\)',
        src,
        re.DOTALL,
    )
    assert match, (
        "loadArtifacts() must be called inside the 'end' event listener of streamLogs()."
    )
