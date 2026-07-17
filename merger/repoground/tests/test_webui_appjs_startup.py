"""Static regressions for RepoGround WebUI startup ordering.

Form submissions must be intercepted before the asynchronous startup path waits
for service health. Otherwise the browser can perform native form navigation
and discard the current UI state.
"""
from pathlib import Path


APP_JS = Path(__file__).resolve().parents[1] / "frontends" / "webui" / "app.js"
BROWSER_TEST = Path(__file__).resolve().parent / "test_webui_payload.py"


def _load_appjs() -> str:
    return APP_JS.read_text(encoding="utf-8")


def test_form_listeners_are_bound_before_first_health_await() -> None:
    source = _load_appjs()

    readiness = "window.__repoground_form_listeners_ready = Boolean("
    first_network_await = "const hub = await fetchHealth();"
    assert readiness in source
    assert first_network_await in source
    assert source.index(readiness) < source.index(first_network_await)


def test_each_startup_form_has_one_submit_listener() -> None:
    source = _load_appjs()

    for binding in (
        "jobForm.addEventListener('submit', startJob)",
        "atlasForm.addEventListener('submit', startAtlasJob)",
        "queryForm.addEventListener('submit', executeQuery)",
    ):
        assert source.count(binding) == 1


def test_listener_readiness_requires_all_three_forms() -> None:
    source = " ".join(_load_appjs().split())

    assert "window.__repoground_form_listeners_ready = false" in source
    assert (
        "window.__repoground_form_listeners_ready = Boolean( "
        "jobForm && atlasForm && queryForm )"
    ) in source

def test_browser_fixture_replaces_canonical_repoground_tokens() -> None:
    source = BROWSER_TEST.read_text(encoding="utf-8")

    for replacement in (
        'content.replace("__REPOGROUND_ASSET_BASE__", "./")',
        'content.replace("__REPOGROUND_BUILD__", "test-v1")',
    ):
        assert replacement in source
    assert 'window.__REPOGROUND_UI_VERSION__") == "test-v1"' in source
