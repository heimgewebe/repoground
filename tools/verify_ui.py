#!/usr/bin/env python3
"""
tools/verify_ui.py

Verifies frontend feature parity and UI state using Playwright.
Designed to be robust in CI environments where Playwright might not be installed.

Usage:
    python3 tools/verify_ui.py [--strict] [--headful] [--timeout-ms MS]

Exit Codes:
    0 - Success OR Skipped (if dependencies missing and not strict)
    1 - Verification Failed OR Strict mode check failed (missing dependencies)
"""
import sys
import os
import json
import argparse

# Determine the project root and UI directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(PROJECT_ROOT, "merger/repoground/frontends/webui")

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

def verify_ui(args) -> int:
    """
    Verifies that the redundant 'Run Merge from Pool' button is gone
    and the main 'Start Job' button is present.
    Returns: 0 for success/skip, 1 for failure.
    """
    print(f"Starting UI verification against {UI_DIR}...")

    # Pre-check: Ensure UI assets exist
    if not os.path.exists(UI_DIR) or not os.path.exists(os.path.join(UI_DIR, "index.html")):
        if args.strict:
            print(f"FAILURE: UI directory or index.html not found at {UI_DIR}")
            return 1
        else:
            print(f"SKIP: UI directory or index.html not found at {UI_DIR}")
            return 0

    with sync_playwright() as p:
        try:
            # args.headful means NOT headless. Default is headless=True (if headful is False).
            browser = p.chromium.launch(headless=not args.headful)
        except Exception as e:
            if args.strict:
                print(f"FAILURE: Could not launch browser (Strict Mode): {e}")
                return 1
            else:
                print(f"SKIP: Could not launch browser: {e}")
                print("Tip: Run 'playwright install --with-deps chromium'")
                return 0

        try:
            page = browser.new_page()

            # Robust Request Handler (Strict Mode)
            def handle_request(route):
                url = route.request.url
                path = url.split("/")[-1].split("?")[0]

                # Root / Index
                # Matches http://verify.local/ or index.html
                if url == "http://verify.local/" or path == "index.html" or path == "":
                    try:
                        with open(os.path.join(UI_DIR, "index.html"), "r") as f:
                            content = f.read()
                        content = content.replace("__RLENS_ASSET_BASE__", "./")
                        content = content.replace("__RLENS_BUILD__", "verify-tool-v1")
                        route.fulfill(body=content, content_type="text/html")
                    except Exception as e:
                        print(f"Error serving index: {e}")
                        route.fulfill(status=500, body=str(e))
                    return

                # Static Files
                file_path = os.path.join(UI_DIR, path)
                if os.path.exists(file_path) and os.path.isfile(file_path):
                    content_type = "text/plain"
                    if path.endswith(".js"): content_type = "application/javascript"
                    elif path.endswith(".css"): content_type = "text/css"
                    elif path.endswith(".html"): content_type = "text/html"

                    with open(file_path, "rb") as f:
                        route.fulfill(body=f.read(), content_type=content_type)
                else:
                    # STRICT 404 for everything else.
                    # No fallback to network.
                    route.fulfill(status=404, body="Not Found")

            # 0. Global Route Interception (Prevent DNS/Network for fake domain)
            def master_handler(route):
                url = route.request.url

                # API Routing
                if "/api/version" in url:
                    route.fulfill(json={"version": "verify-tool", "build_id": "v1"})
                    return
                if "/api/health" in url:
                    route.fulfill(json={"status": "ok", "hub": "/mock/hub", "merges_dir": "/mock/merges"})
                    return
                if "/api/artifacts" in url:
                    route.fulfill(json=[])
                    return
                if "/api/repos" in url:
                    route.fulfill(json=["repoA", "repoB"])
                    return
                if "/api/jobs" in url:
                    route.fulfill(json={"id": "job-tool-1", "status": "queued"})
                    return

                # Static/Index Routing
                handle_request(route)

            page.route("**/*", master_handler)

            # Inject pool state
            pool_state = {
                "repoA": {"raw": None, "compressed": None},
                "repoB": {"raw": ["fileB.txt"], "compressed": ["fileB.txt"]}
            }

            try:
                # Use add_init_script to inject storage BEFORE the page loads.
                # This ensures app.js sees the state immediately on initial load.
                page.add_init_script(f"""
                    localStorage.setItem("lenskit.prescan.savedSelections.v1", JSON.stringify({json.dumps(pool_state)}));
                """)

                # Single robust navigation with full interception via master_handler (which covers **/*)
                page.goto("http://verify.local/")

                # Wait for UI
                page.wait_for_selector("#repoList input[name='repos']", timeout=args.timeout_ms)
                page.wait_for_timeout(500)

                # Verification Logic
                failed = False

                # 1. Check for redundant button
                pool_btn = page.query_selector("button:has-text('Run Merge from Pool')")
                if pool_btn:
                    print("FAILURE: 'Run Merge from Pool' button found!")
                    failed = True
                else:
                    print("SUCCESS: 'Run Merge from Pool' button NOT found.")

                # 2. Check for main button
                start_btn = page.query_selector("#jobForm button[type='submit']")
                if start_btn:
                    print("SUCCESS: 'Start Job' button found.")
                else:
                    print("FAILURE: 'Start Job' button NOT found.")
                    failed = True

                if failed:
                    return 1

                print("Verification passed.")
                return 0

            except Exception as e:
                print(f"Verification logic crashed: {e}")
                return 1

        except Exception as e:
             print(f"Browser/Page crashed: {e}")
             return 1
        finally:
            browser.close()

def main():
    parser = argparse.ArgumentParser(description="Verify UI parity and robustness.")
    parser.add_argument("--headful", action="store_true", help="Run browser in headful mode (default: headless)")
    parser.add_argument("--timeout-ms", type=int, default=5000, help="Timeout in milliseconds")
    parser.add_argument("--strict", action="store_true", help="Fail if dependencies are missing")
    args = parser.parse_args()

    if not PLAYWRIGHT_AVAILABLE:
        if args.strict:
            print("FAILURE: Playwright not installed and --strict mode is on.")
            sys.exit(1)
        else:
            print("SKIP: Playwright not installed.")
            sys.exit(0)

    # Run verification and exit with returned code
    sys.exit(verify_ui(args))

if __name__ == "__main__":
    main()
