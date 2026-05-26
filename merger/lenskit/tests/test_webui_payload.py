from __future__ import annotations

import pytest
import json
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page, Route

pytestmark = pytest.mark.browser

UI_DIR = os.path.abspath("merger/lenskit/frontends/webui")

@pytest.fixture
def page_with_static(page: Page):
    import os
    # Log console
    if os.environ.get("DEBUG_PLAYWRIGHT_REQUESTS") == "1":
        page.on("console", lambda msg: print(f"PAGE LOG: {msg.text}"))
        page.on("pageerror", lambda exc: print(f"PAGE ERROR: {exc}"))

    with open(os.path.join(UI_DIR, "index.html"), "r") as f:
        content = f.read()

    content = content.replace("__RLENS_ASSET_BASE__", "./")
    content = content.replace("__RLENS_BUILD__", "test-v1")

    page.route("http://localhost:8000/", lambda route: route.fulfill(
        status=200,
        body=content,
        content_type="text/html"
    ))

    def handle_static(route: Route):
        path = route.request.url.split("/")[-1].split("?")[0]
        file_path = os.path.join(UI_DIR, path)
        if os.path.exists(file_path):
            content_type = "text/plain"
            if path.endswith(".js"):
                content_type = "application/javascript"
            elif path.endswith(".css"):
                content_type = "text/css"
            elif path.endswith(".html"):
                content_type = "text/html"

            with open(file_path, "rb") as f:
                route.fulfill(body=f.read(), content_type=content_type)
        else:
            route.continue_()

    page.route("**/app.js*", handle_static)
    page.route("**/materialize.js*", handle_static)
    page.route("**/style.css*", handle_static)

    page.route("**/api/version", lambda route: route.fulfill(json={"version": "test", "build_id": "test-1"}))
    page.route("**/api/health", lambda route: route.fulfill(json={"status": "ok", "hub": "/mock/hub", "merges_dir": "/mock/merges"}))
    page.route("**/api/artifacts", lambda route: route.fulfill(json=[]))
    repo_fetch_count = {"count": 0}

    def handle_repos(route: Route):
        repo_fetch_count["count"] += 1
        route.fulfill(json=["repoA", "repoB", "../dirtyRepo"])

    page.route("**/api/repos*", handle_repos)
    setattr(page, "_repo_fetch_count", repo_fetch_count)

    return page

def test_run_merge_picks_up_pool_selections(page_with_static: Page):
    """
    Verifies that the 'Run Merge' button correctly picks up pool selections
    and uses Combined Job Mapping (strict_include_paths_by_repo) when partial selections exist.
    """
    pool_state = {
        "repoA": {"raw": None, "compressed": None}, # Full selection
        "repoB": {"raw": ["fileB.txt"], "compressed": ["fileB.txt"]} # Partial selection
    }

    page_with_static.add_init_script("window.__RLENS_TEST__ = true;")
    page_with_static.goto("http://localhost:8000/")

    page_with_static.evaluate(f"""
        const pool = {json.dumps(pool_state)};
        localStorage.setItem("lenskit.prescan.savedSelections.v1", JSON.stringify(pool));
    """)
    page_with_static.reload()
    page_with_static.wait_for_function("() => window.__rlens_pool_ready === true")
    page_with_static.wait_for_selector("#repoList input[name='repos']")

    # Select repoA and repoB
    page_with_static.evaluate("""
        const boxes = document.querySelectorAll('input[name="repos"]');
        boxes.forEach(b => {
            if (b.value === 'repoA' || b.value === 'repoB') b.checked = true;
        });
    """)

    payloads = []
    def handle_jobs(route: Route):
        if route.request.method == "POST":
            data = route.request.post_data_json or json.loads(route.request.post_data)
            payloads.append(data)
            route.fulfill(json={"id": "job-" + str(len(payloads)), "status": "queued"})
        else:
            route.continue_()

    page_with_static.route("**/api/jobs", handle_jobs)
    page_with_static.select_option("#mode", "gesamt")
    page_with_static.click("#jobForm button[type='submit']")

    def wait_for_payloads():
        start = time.time()
        while time.time() - start < 5:
            if len(payloads) == 1: return
            page_with_static.wait_for_timeout(50)
        raise TimeoutError(f"Payloads count {len(payloads)} != 1")

    wait_for_payloads()

    p = payloads[0]
    assert sorted(p["repos"]) == ["repoA", "repoB"]
    assert "include_paths_by_repo" in p
    ipbr = p["include_paths_by_repo"]
    assert ipbr["repoA"] is None # Full
    assert ipbr["repoB"] == ["fileB.txt"] # Partial
    assert p.get("strict_include_paths_by_repo") is True
    assert "include_paths" not in p or p["include_paths"] is None
    assert p.get("force_new") is True

    # Ensure global filters are cleared when pool is active (even partially)
    assert p.get("path_filter") is None
    assert p.get("extensions") is None


def test_run_merge_mixed_pool_and_non_pool(page_with_static: Page):
    """
    Verifies that if one repo is in the pool (partial) and another is NOT in the pool,
    the non-pool repo gets mapped to null (Full) in the combined job.
    """
    pool_state = {
        "repoA": {"raw": ["fileA.txt"], "compressed": ["fileA.txt"]}
        # repoB NOT in pool
    }

    page_with_static.add_init_script("window.__RLENS_TEST__ = true;")
    page_with_static.goto("http://localhost:8000/")

    page_with_static.evaluate(f"""
        const pool = {json.dumps(pool_state)};
        localStorage.setItem("lenskit.prescan.savedSelections.v1", JSON.stringify(pool));
    """)
    page_with_static.reload()
    page_with_static.wait_for_function("() => window.__rlens_pool_ready === true")
    page_with_static.wait_for_selector("#repoList input[name='repos']")

    page_with_static.evaluate("""
        const boxes = document.querySelectorAll('input[name="repos"]');
        boxes.forEach(b => {
            if (b.value === 'repoA' || b.value === 'repoB') b.checked = true;
        });
    """)

    payloads = []
    def handle_jobs(route: Route):
        if route.request.method == "POST":
            data = route.request.post_data_json or json.loads(route.request.post_data)
            payloads.append(data)
            route.fulfill(json={"id": "job-mixed", "status": "queued"})
        else:
            route.continue_()

    page_with_static.route("**/api/jobs", handle_jobs)
    page_with_static.select_option("#mode", "gesamt")
    page_with_static.click("#jobForm button[type='submit']")

    def wait_for_payloads():
        start = time.time()
        while time.time() - start < 5:
            if len(payloads) == 1: return
            page_with_static.wait_for_timeout(50)
        raise TimeoutError(f"Payloads count {len(payloads)} != 1")

    wait_for_payloads()

    p = payloads[0]
    assert sorted(p["repos"]) == ["repoA", "repoB"]
    assert p["include_paths_by_repo"]["repoA"] == ["fileA.txt"]
    assert p["include_paths_by_repo"]["repoB"] is None # Not in pool -> Full
    assert p.get("strict_include_paths_by_repo") is True
    assert p.get("force_new") is True


def test_run_merge_blocks_dirty_keys(page_with_static: Page):
    """
    Verifies that selecting a repo with a dirty name blocks submission.
    """
    page_with_static.add_init_script("window.__RLENS_TEST__ = true;")
    page_with_static.goto("http://localhost:8000/")
    page_with_static.wait_for_selector("#repoList input[name='repos']")

    # Select the dirty repo "../dirtyRepo"
    page_with_static.evaluate("""
        const boxes = document.querySelectorAll('input[name="repos"]');
        boxes.forEach(b => {
            if (b.value === '../dirtyRepo') b.checked = true;
        });
    """)

    payloads = []
    def handle_jobs(route: Route):
        if route.request.method == "POST":
            payloads.append(route.request.post_data)
            route.fulfill(json={})
        else:
            route.continue_()

    page_with_static.route("**/api/jobs", handle_jobs)

    # Handle alert
    dialog_message = []
    def handle_dialog(dialog):
        dialog_message.append(dialog.message)
        dialog.accept()
    page_with_static.on("dialog", handle_dialog)

    page_with_static.click("#jobForm button[type='submit']")

    # Wait a bit to ensure no network req happens
    page_with_static.wait_for_timeout(500)

    assert len(payloads) == 0
    assert len(dialog_message) > 0
    assert "Security: Invalid repository names detected" in dialog_message[0]

def test_run_merge_clears_global_filters_for_pool(page_with_static: Page):
    """
    Regression Test: If pool selection is active, global filters (path_filter, extensions)
    must be cleared to prevent silent dropping of explicitly selected files.
    """
    # 1. Setup Pool with explicit selection
    pool_state = {
        "repoA": {"raw": ["foo.txt"], "compressed": ["foo.txt"]}
    }
    page_with_static.add_init_script("window.__RLENS_TEST__ = true;")
    page_with_static.goto("http://localhost:8000/")

    page_with_static.evaluate(f"""
        const pool = {json.dumps(pool_state)};
        localStorage.setItem("lenskit.prescan.savedSelections.v1", JSON.stringify(pool));
    """)
    page_with_static.reload()
    page_with_static.wait_for_function("() => window.__rlens_pool_ready === true")

    # 2. Set global filters in UI (the trap)
    page_with_static.fill("#pathFilter", "src/")
    page_with_static.fill("#extFilter", ".js")

    # 3. Select Repo
    page_with_static.evaluate("""
        const boxes = document.querySelectorAll('input[name="repos"]');
        boxes.forEach(b => {
            if (b.value === 'repoA') b.checked = true;
        });
    """)

    # 4. Capture Payload
    payloads = []
    def handle_jobs(route: Route):
        if route.request.method == "POST":
            data = route.request.post_data_json or json.loads(route.request.post_data)
            payloads.append(data)
            route.fulfill(json={"id": "job-regr", "status": "queued"})
        else:
            route.continue_()

    page_with_static.route("**/api/jobs", handle_jobs)
    page_with_static.select_option("#mode", "gesamt")
    page_with_static.click("#jobForm button[type='submit']")

    # Wait for payload
    start = time.time()
    while len(payloads) == 0 and time.time() - start < 5:
        page_with_static.wait_for_timeout(50)

    assert len(payloads) == 1
    p = payloads[0]

    # 5. Assert Logic:
    # - Repo has include_paths_by_repo (pool active)
    # - path_filter and extensions MUST be null/None
    assert p["include_paths_by_repo"]["repoA"] == ["foo.txt"]
    assert p.get("path_filter") is None, "path_filter must be cleared when pool is active"
    assert p.get("extensions") is None, "extensions must be cleared when pool is active"
    assert p.get("force_new") is True


def test_run_merge_clears_global_filters_for_all_pool_selection(page_with_static: Page):
    """
    Verifies that global filters are cleared even if the pool selection is 'ALL' (null).
    """
    # 1. Setup Pool with explicit 'ALL' selection
    pool_state = {
        "repoA": {"raw": None, "compressed": None}
    }
    page_with_static.add_init_script("window.__RLENS_TEST__ = true;")
    page_with_static.goto("http://localhost:8000/")

    page_with_static.evaluate(f"""
        const pool = {json.dumps(pool_state)};
        localStorage.setItem("lenskit.prescan.savedSelections.v1", JSON.stringify(pool));
    """)
    page_with_static.reload()
    page_with_static.wait_for_function("() => window.__rlens_pool_ready === true")

    # 2. Set global filters in UI
    page_with_static.fill("#pathFilter", "src/")
    page_with_static.fill("#extFilter", ".js")

    # 3. Select Repo
    page_with_static.check("input[value='repoA']")

    # 4. Capture Payload
    payloads = []
    def handle_jobs(route: Route):
        payloads.append(route.request.post_data_json or json.loads(route.request.post_data))
        route.fulfill(json={"id": "job-regr-all", "status": "queued"})

    page_with_static.route("**/api/jobs", handle_jobs)
    page_with_static.click("#jobForm button[type='submit']")

    # Wait for payload
    start = time.time()
    while len(payloads) == 0 and time.time() - start < 5:
        page_with_static.wait_for_timeout(50)

    assert len(payloads) == 1
    p = payloads[0]

    # 5. Assert Logic:
    # Even with ALL (null), presence in the pool means an explicit override.
    assert "repoA" in p["include_paths_by_repo"]
    assert p["include_paths_by_repo"]["repoA"] is None  # ALL
    assert p.get("path_filter") is None, "path_filter must be cleared even for ALL pool selections"
    assert p.get("extensions") is None, "extensions must be cleared even for ALL pool selections"


def test_run_merge_plan_only_omits_force_new(page_with_static: Page):
    """
    Verifies that when 'Plan Only' is checked, the generated payload
    omits the 'force_new' parameter to allow caching.
    """
    page_with_static.add_init_script("window.__RLENS_TEST__ = true;")
    page_with_static.goto("http://localhost:8000/")
    page_with_static.wait_for_selector("#repoList input[name='repos']")

    # Select repoA
    page_with_static.evaluate("""
        const boxes = document.querySelectorAll('input[name="repos"]');
        boxes.forEach(b => {
            if (b.value === 'repoA') b.checked = true;
        });
    """)

    # Check Plan Only
    page_with_static.check("#planOnly")

    def handle_jobs(route: Route):
        if route.request.method == "POST":
            route.fulfill(json={"id": "job-plan-only", "status": "queued"})
        else:
            route.continue_()

    page_with_static.route("**/api/jobs", handle_jobs)
    page_with_static.select_option("#mode", "gesamt")

    with page_with_static.expect_request("**/api/jobs") as req_info:
        page_with_static.click("#jobForm button[type='submit']")

    req = req_info.value
    p = req.post_data_json or json.loads(req.post_data)

    assert p["plan_only"] is True
    assert "force_new" not in p, "force_new should be omitted for plan_only jobs"


def test_run_merge_resets_form_to_factory_defaults_when_none_saved(page_with_static: Page):
    """
    Test A: Verify that after successful submit, form resets to factory defaults
    when no saved defaults exist in rlens_config.
    """
    pool_state = {
        "repoA": {"raw": ["src/a.py"], "compressed": ["src/a.py"]},
        "repoB": {"raw": None, "compressed": None},
    }

    page_with_static.add_init_script("window.__RLENS_TEST__ = true;")
    page_with_static.goto("http://localhost:8000/")

    page_with_static.evaluate(f"""
        localStorage.setItem("lenskit.prescan.savedSelections.v1", JSON.stringify({json.dumps(pool_state)}));
    """)
    page_with_static.reload()
    page_with_static.wait_for_function("() => window.__rlens_pool_ready === true")
    page_with_static.wait_for_selector("#repoList input[name='repos']")

    page_with_static.evaluate("""
        document.querySelectorAll('input[name="repos"]').forEach(b => {
            if (b.value === 'repoA' || b.value === 'repoB') b.checked = true;
        });
    """)

    # Set non-default values temporarily
    page_with_static.select_option("#profile", "overview")
    page_with_static.select_option("#mode", "gesamt")
    page_with_static.fill("#splitSize", "10MB")
    page_with_static.fill("#maxBytes", "2048")
    page_with_static.select_option("#metaDensity", "full")
    page_with_static.fill("#pathFilter", "src/")
    page_with_static.fill("#extFilter", ".py,.md")
    page_with_static.check("#planOnly")
    page_with_static.check("#codeOnly")

    payloads = []

    def handle_jobs(route: Route):
        if route.request.method == "POST":
            data = route.request.post_data_json or json.loads(route.request.post_data)
            payloads.append(data)
            route.fulfill(json={"id": "job-reset", "status": "queued"})
        else:
            route.continue_()

    page_with_static.route("**/api/jobs", handle_jobs)
    repo_fetch_count_before_submit = getattr(page_with_static, "_repo_fetch_count", {"count": 0})["count"]
    page_with_static.click("#jobForm button[type='submit']")

    start = time.time()
    while len(payloads) == 0 and time.time() - start < 5:
        page_with_static.wait_for_timeout(50)

    assert len(payloads) == 1
    sent = payloads[0]
    assert sent["level"] == "overview"
    assert sent["split_size"] == "10MB"
    assert sent["max_bytes"] == "2048"
    assert sent["path_filter"] is None
    assert sent["extensions"] is None
    assert sent["include_paths_by_repo"]["repoA"] == ["src/a.py"]
    assert sent["include_paths_by_repo"]["repoB"] is None
    assert sent["plan_only"] is True
    assert sent["code_only"] is True

    # After submit, form should reset to factory defaults
    page_with_static.wait_for_function("""
      () => Array.from(document.querySelectorAll('input[name="repos"]')).length > 0
        && Array.from(document.querySelectorAll('input[name="repos"]')).every(b => b.checked === false)
        && document.querySelector('#profile')?.value === 'max'
        && document.querySelector('#mode')?.value === 'gesamt'
        && document.querySelector('#splitSize')?.value === '25MB'
        && document.querySelector('#maxBytes')?.value === '0'
        && document.querySelector('#metaDensity')?.value === 'auto'
        && document.querySelector('#pathFilter')?.value === ''
        && document.querySelector('#extFilter')?.value === ''
        && document.getElementById('planOnly')?.checked === false
        && document.getElementById('codeOnly')?.checked === false
    """)

    repo_fetch_count_after_submit = getattr(page_with_static, "_repo_fetch_count", {"count": 0})["count"]
    assert repo_fetch_count_after_submit >= 2
    assert repo_fetch_count_after_submit > repo_fetch_count_before_submit

    pool_after = page_with_static.evaluate("""
        () => JSON.parse(localStorage.getItem('lenskit.prescan.savedSelections.v1') || '{}')
    """)
    assert pool_after == {}

    page_with_static.wait_for_function("""
        () => !document.querySelector('#repoList')?.innerText.includes('POOL')
    """)


def test_run_merge_respects_saved_defaults_after_success(page_with_static: Page):
    """
    Test B: Verify that after successful submit, form resets to SAVED defaults
    (not factory defaults) when rlens_config contains user-saved defaults.
    This ensures user preferences from 'Save Defaults' are preserved across submits.
    """
    pool_state = {
        "repoA": {"raw": ["src/a.py"], "compressed": ["src/a.py"]},
        "repoB": {"raw": None, "compressed": None},
    }

    # Saved defaults (what user set via "Save Defaults" button)
    saved_config = {
        "profile": "dev",
        "mode": "pro-repo",
        "splitSize": "8MB",
        "maxBytes": "1024",
        "metaDensity": "min",
        "pathFilter": "src/util/",
        "extFilter": ".ts,.js",
        "planOnly": False,
        "codeOnly": False,
        "extras": ["json_sidecar"],
        "hubPath": "/env/hub",
        "mergesPath": "/env/merges"
    }

    page_with_static.add_init_script("window.__RLENS_TEST__ = true;")
    page_with_static.goto("http://localhost:8000/")

    page_with_static.evaluate(f"""
        localStorage.setItem("lenskit.prescan.savedSelections.v1", JSON.stringify({json.dumps(pool_state)}));
        localStorage.setItem("rlens_config", JSON.stringify({json.dumps(saved_config)}));
    """)
    page_with_static.reload()
    page_with_static.wait_for_function("() => window.__rlens_pool_ready === true")
    page_with_static.wait_for_selector("#repoList input[name='repos']")

    # Verify saved defaults were loaded into form
    assert page_with_static.input_value("#profile") == "dev"
    assert page_with_static.locator("#mode").evaluate("(el) => el.value") == "pro-repo"
    assert page_with_static.input_value("#splitSize") == "8MB"
    assert page_with_static.input_value("#maxBytes") == "1024"

    page_with_static.evaluate("""
        document.querySelectorAll('input[name="repos"]').forEach(b => {
            if (b.value === 'repoA' || b.value === 'repoB') b.checked = true;
        });
    """)

    # Override with different values for this run
    page_with_static.select_option("#profile", "overview")
    page_with_static.select_option("#mode", "gesamt")
    page_with_static.fill("#splitSize", "10MB")
    page_with_static.fill("#maxBytes", "2048")
    page_with_static.select_option("#metaDensity", "full")
    page_with_static.fill("#pathFilter", "src/")
    page_with_static.fill("#extFilter", ".py,.md")
    page_with_static.check("#planOnly")
    page_with_static.check("#codeOnly")

    payloads = []

    def handle_jobs(route: Route):
        if route.request.method == "POST":
            data = route.request.post_data_json or json.loads(route.request.post_data)
            payloads.append(data)
            route.fulfill(json={"id": "job-reset-saved", "status": "queued"})
        else:
            route.continue_()

    page_with_static.route("**/api/jobs", handle_jobs)
    page_with_static.click("#jobForm button[type='submit']")

    start = time.time()
    while len(payloads) == 0 and time.time() - start < 5:
        page_with_static.wait_for_timeout(50)

    assert len(payloads) == 1
    sent = payloads[0]
    # Should contain the override values for this specific run
    assert sent["level"] == "overview"
    assert sent["split_size"] == "10MB"
    assert sent["max_bytes"] == "2048"
    assert sent["plan_only"] is True
    assert sent["code_only"] is True


    # Wait for full reset: repos unchecked AND form restored to saved defaults
    page_with_static.wait_for_function("""
      () => Array.from(document.querySelectorAll('input[name="repos"]')).every(b => b.checked === false)
        && document.querySelector('#profile')?.value === 'dev'
        && document.querySelector('#mode')?.value === 'pro-repo'
        && document.querySelector('#splitSize')?.value === '8MB'
    """, timeout=5000)

    # Check pool was cleared
    pool_after = page_with_static.evaluate("""
        () => JSON.parse(localStorage.getItem('lenskit.prescan.savedSelections.v1') || '{}')
    """)
    assert pool_after == {}

    # Check all visible fields reset to saved defaults (not factory defaults)
    assert page_with_static.input_value("#profile") == "dev"
    assert page_with_static.locator("#mode").evaluate("(el) => el.value") == "pro-repo"
    assert page_with_static.input_value("#splitSize") == "8MB"
    assert page_with_static.input_value("#maxBytes") == "1024"
    assert page_with_static.locator("#metaDensity").evaluate("(el) => el.value") == "min"
    assert page_with_static.input_value("#pathFilter") == "src/util/"
    assert page_with_static.input_value("#extFilter") == ".ts,.js"

    # Check extras: json_sidecar should be checked; augment_sidecar should not
    assert page_with_static.evaluate(
        "() => document.querySelector('input[name=\"extras\"][value=\"json_sidecar\"]')?.checked"
    ) is True
    assert page_with_static.evaluate(
        "() => document.querySelector('input[name=\"extras\"][value=\"augment_sidecar\"]')?.checked"
    ) is False

    # Crucially: rlens_config must NOT be overwritten — saved defaults remain unchanged
    stored_config = page_with_static.evaluate("""
        () => JSON.parse(localStorage.getItem('rlens_config') || '{}')
    """)
    assert stored_config.get("profile") == "dev"
    assert stored_config.get("mode") == "pro-repo"
    assert stored_config.get("splitSize") == "8MB"
    assert stored_config.get("maxBytes") == "1024"
    assert stored_config.get("metaDensity") == "min"
    assert stored_config.get("pathFilter") == "src/util/"
    assert stored_config.get("extFilter") == ".ts,.js"
    assert stored_config.get("hubPath") == "/env/hub"
    assert stored_config.get("mergesPath") == "/env/merges"




def test_query_tab_submits_payload(page_with_static: Page):
    from playwright.sync_api import expect

    import os
    if os.environ.get("DEBUG_PLAYWRIGHT_REQUESTS") == "1":
        page_with_static.on("request", lambda r: print(f"REQ: {r.method} {r.url}"))
    page_with_static.add_init_script("window.__RLENS_TEST__ = true; localStorage.setItem('rlens_state_version', 'test-v1');")

    def handle_query(route: Route):
        if route.request.method == "POST":
            route.fulfill(status=200, json={
                "context_bundle": {
                    "hits": [
                        {
                            "file": "src/login.py",
                            "range": "1-10",
                            "score": 0.95,
                            "provenance_type": "explicit",
                            "explain": {"top_k_scoring": []},
                            "surrounding_context": "def login():\n    pass",
                            "graph_context": {"graph_used": True, "distance": 1}
                        }
                    ]
                },
                "query_trace": {"timings": {}}
            })
        else:
            route.continue_()

    page_with_static.route("**/api/query*", handle_query)

    page_with_static.goto("http://localhost:8000/")

    page_with_static.wait_for_selector("#tab-query")

    # Wait for JS to attach event listeners
    page_with_static.wait_for_function("typeof window.switchTab === 'function' && typeof window.executeQuery === 'function'")

    # Switch to the query tab explicitly via application state to avoid headless click flakiness on hidden layout elements
    page_with_static.evaluate("window.switchTab('query')")
    page_with_static.wait_for_selector("#layout-query", state="visible")
    page_with_static.wait_for_selector("#queryForm", state="attached")

    # Fill out the form normally now that the layout is cleanly visible.
    # Use force=True to bypass Chromium's flaky headless clickability checks on dynamic tabs.
    page_with_static.locator("#queryIndexId").fill("job-1234", force=True)
    page_with_static.locator("#queryText").fill("find login", force=True)
    page_with_static.locator("#queryK").fill("5", force=True)
    page_with_static.locator("#queryContextMode").select_option("window", force=True)
    page_with_static.locator("#queryWindowLines").fill("3", force=True)
    page_with_static.locator("#queryTrace").check(force=True)

    with page_with_static.expect_request("**/api/query*", timeout=5000) as req_info:
        page_with_static.locator("#queryForm button[type='submit']").click(force=True)

    req = req_info.value
    p = req.post_data_json or json.loads(req.post_data)

    assert p["index_id"] == "job-1234"
    assert p["q"] == "find login"
    assert p["k"] == 5
    assert p["context_mode"] == "window"
    assert p["context_window_lines"] == 3
    assert p["explain"] is True
    assert p["trace"] is True
    assert p["output_profile"] == "ui_navigation"

    # Verify that the mocked payload is correctly rendered in the UI
    expect(page_with_static.locator("#queryResults")).to_be_visible()

    # Check for the file path being rendered
    expect(page_with_static.locator("#queryResults").locator("text=src/login.py")).to_be_visible()

    # Check for score rendering
    expect(page_with_static.locator("#queryResults").locator("text=Score: 0.950")).to_be_visible()

    # Check for explain block
    expect(page_with_static.locator("#queryResults").get_by_text("Explain", exact=True)).to_be_visible()
