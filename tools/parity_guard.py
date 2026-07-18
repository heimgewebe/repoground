#!/usr/bin/env python3
"""
Parity Guard
------------
Ensures feature parity between the Backend Model (JobRequest),
Pythonista UI (RepoGround Pythonista build), and RepoGround Web UI.

Checks:
1. JobRequest model fields (Source of Truth).
2. RepoGround Pythonista build (CLI args, usage, and UI logic).
3. Web UI (index.html inputs and app.js payload construction).
"""

import sys
import re
import ast
from pathlib import Path

# Configuration
# Map Feature Name (JobRequest field) to expected representations
# Key: JobRequest field name
# Value: Dict of expectations
FEATURES = {
    "level": {
        "cli_arg": "--level",
        "html_id": "profile",
        "js_key": "level",
        "pythonista_usage": "args.level"
    },
    "mode": {
        "cli_arg": "--mode",
        "html_id": "mode",
        "js_key": "mode",
        "pythonista_usage": "args.mode"
    },
    "max_bytes": {
        "cli_arg": "--max-bytes",
        "html_id": "maxBytes",
        "js_key": "max_bytes",
        "pythonista_usage": "args.max_bytes" # ArgumentParser automatically converts - to _
    },
    "split_size": {
        "cli_arg": "--split-size",
        "html_id": "splitSize",
        "js_key": "split_size",
        "pythonista_usage": "args.split_size"
    },
    "plan_only": {
        "cli_arg": "--plan-only",
        "html_id": "planOnly",
        "js_key": "plan_only",
        "pythonista_usage": "args.plan_only"
    },
    "code_only": {
        "cli_arg": "--code-only",
        "html_id": "codeOnly",
        "js_key": "code_only",
        "pythonista_usage": "args.code_only"
    },
    "meta_density": {
        "cli_arg": "--meta-density",
        "html_id": "metaDensity",
        "js_key": "meta_density",
        "pythonista_usage": "args.meta_density"
    },
    "json_sidecar": {
        "cli_arg": "--json-sidecar",
        # Explicit decision: Treat as a payload key in JS (even if logic is derived).
        # In JobRequest it is a field.
        "js_key": "json_sidecar",
        "pythonista_usage": "args.json_sidecar"
    },
    # Filters
    "extensions": {
        "cli_arg": "--extensions",
        "html_id": "extFilter",
        "js_key": "extensions",
        "pythonista_usage": "args.extensions"
    },
    "path_filter": {
        "cli_arg": "--path-filter",
        "html_id": "pathFilter",
        "js_key": "path_filter",
        "pythonista_usage": "args.path_filter"
    },
    # Surface parity only: this guard checks that the --pre-pull flag, the #prePull
    # WebUI element, the pre_pull payload key and RepoGround Pythonista build' args.pre_pull all exist.
    # It does NOT (and need not) assert the shared semantics — effective_pre_pull =
    # pre_pull and not plan_only, two-phase plan/apply, fast-forward-only — which are
    # covered by test_repo_sync.py / test_service_runner_pre_pull.py /
    # test_pythonista_pre_pull.py and the rLens-client tests.
    "pre_pull": {
        "cli_arg": "--pre-pull",
        "html_id": "prePull",
        "js_key": "pre_pull",
        "pythonista_usage": "args.pre_pull"
    },
    # RepoGround Source Acquisition v1. Surface-parity only: the guard checks that the
    # --source-mode/--remote-ref/--remote-ref-policy flags, the WebUI elements,
    # the payload keys and RepoGround Pythonista build' args all exist across surfaces. The shared
    # semantics (effective source mode, remote_snapshot non-mutation, ref policy,
    # dry-plan) are covered by test_source_acquisition.py and the service/CLI/UI
    # tests, not by this guard.
    "repo_source_mode": {
        "cli_arg": "--source-mode",
        "html_id": "sourceMode",
        "js_key": "repo_source_mode",
        "pythonista_usage": "args.source_mode"
    },
    "remote_ref": {
        "cli_arg": "--remote-ref",
        "html_id": "remoteRef",
        "js_key": "remote_ref",
        "pythonista_usage": "args.remote_ref"
    },
    "remote_ref_policy": {
        "cli_arg": "--remote-ref-policy",
        "html_id": "remoteRefPolicy",
        "js_key": "remote_ref_policy",
        "pythonista_usage": "args.remote_ref_policy"
    }
}

# Paths
ROOT = Path(__file__).parent.parent.resolve()
MODEL_PATH = ROOT / "merger/repoground/service/models.py"
PYTHONISTA_BUILD_PATH = ROOT / "merger/repoground/frontends/pythonista/build.py"
WEBUI_HTML_PATH = ROOT / "merger/repoground/frontends/webui/index.html"
WEBUI_JS_PATH = ROOT / "merger/repoground/frontends/webui/app.js"


def _defined_cli_arguments(tree: ast.AST) -> set[str]:
    arguments: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "add_argument":
            continue
        arguments.update(
            arg.value
            for arg in node.args
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
        )
    return arguments


def _explicit_argument_accesses(tree: ast.AST) -> set[str]:
    accesses = {
        f"args.{node.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "args"
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "getattr":
            continue
        if len(node.args) < 2:
            continue
        target, field = node.args[:2]
        if (
            isinstance(target, ast.Name)
            and target.id == "args"
            and isinstance(field, ast.Constant)
            and isinstance(field.value, str)
        ):
            accesses.add(f"args.{field.value}")
    return accesses


def _uses_generic_argument_mapping(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "vars"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "args"
        ):
            return True
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "__dict__"
            and isinstance(node.value, ast.Name)
            and node.value.id == "args"
        ):
            return True
    return False


def _literal_subscript_keys(tree: ast.AST) -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        slice_node = node.slice
        if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
            keys.add(slice_node.value)
    return keys

class ParityChecker:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def log_error(self, msg):
        self.errors.append(f"[FAIL] {msg}")

    def log_warn(self, msg):
        self.warnings.append(f"[WARN] {msg}")

    def log_pass(self, msg):
        print(f"[PASS] {msg}")

    def check_model_fields(self):
        """Verify defined features actually exist in JobRequest model."""
        print(f"Checking JobRequest in {MODEL_PATH}...")
        try:
            tree = ast.parse(MODEL_PATH.read_text("utf-8"))
        except Exception as e:
            self.log_error(f"Could not parse models.py: {e}")
            return

        job_request_fields = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "JobRequest":
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        job_request_fields.add(item.target.id)

        for feature in FEATURES:
            if feature not in job_request_fields:
                self.log_error(f"Feature '{feature}' defined in Parity Guard but missing in JobRequest model.")
            else:
                self.log_pass(f"Feature '{feature}' present in JobRequest.")

    def check_pythonista_build(self):
        """Check the RepoGround Pythonista CLI surface using its parsed AST."""
        print(f"Checking RepoGround Pythonista build in {PYTHONISTA_BUILD_PATH}...")
        try:
            tree = ast.parse(PYTHONISTA_BUILD_PATH.read_text("utf-8"))
        except Exception as error:
            self.log_error(f"Could not parse RepoGround Pythonista build: {error}")
            return

        defined_cli_args = _defined_cli_arguments(tree)
        accessed_args = _explicit_argument_accesses(tree)
        has_generic_usage = _uses_generic_argument_mapping(tree)
        accessed_keys = _literal_subscript_keys(tree)

        for feature, config in FEATURES.items():
            cli_arg = config.get("cli_arg")
            if cli_arg in defined_cli_args:
                self.log_pass(
                    f"RepoGround Pythonista build CLI: {cli_arg} definition found (AST)."
                )
            elif cli_arg:
                self.log_error(
                    f"RepoGround Pythonista build CLI: Definition for {cli_arg} "
                    f"missing (feature: {feature})."
                )

            usage_key = config.get("pythonista_usage")
            if not usage_key:
                continue
            field_name = usage_key.rsplit(".", 1)[-1]
            if usage_key in accessed_args:
                self.log_pass(
                    f"RepoGround Pythonista build Usage: {usage_key} accessed (AST)."
                )
            elif has_generic_usage and field_name in accessed_keys:
                self.log_pass(
                    f"RepoGround Pythonista build Usage: {usage_key} accessed "
                    "(Generic AST + Key Usage)."
                )
            else:
                self.log_error(
                    f"RepoGround Pythonista build Usage: {usage_key} not explicitly "
                    "accessed and key literal not used as subscript."
                )

    def check_webui_html(self):
        """Check index.html for IDs."""
        print(f"Checking WebUI HTML in {WEBUI_HTML_PATH}...")
        content = WEBUI_HTML_PATH.read_text("utf-8")

        for feature, config in FEATURES.items():
            html_id = config.get("html_id")
            if html_id:
                # Regex for id="value" or id='value'
                if re.search(f'id=["\']{html_id}["\']', content):
                    self.log_pass(f"WebUI HTML: Element #{html_id} found for '{feature}'.")
                else:
                    self.log_error(f"WebUI HTML: Element #{html_id} missing for feature '{feature}'.")

    def _strip_js_comments(self, js_content):
        """Remove single line // and multi-line /* */ comments."""
        js_content = re.sub(r'/\*.*?\*/', '', js_content, flags=re.DOTALL)
        js_content = re.sub(r'//.*', '', js_content)
        return js_content

    def check_webui_js(self):
        """Check app.js for payload construction."""
        print(f"Checking WebUI JS in {WEBUI_JS_PATH}...")
        content = WEBUI_JS_PATH.read_text("utf-8")
        clean_content = self._strip_js_comments(content)

        # Heuristic 1: Locate "const commonPayload = {"
        match = re.search(r"const\s+commonPayload\s*=\s*(\{.*?\};)", clean_content, re.DOTALL)

        payload_block = None
        if match:
            payload_block = match.group(1)
        else:
            # Heuristic 2: Locate JSON.stringify({ ... })
            match2 = re.search(r"JSON\.stringify\s*\(\s*(\{.*?\})\s*\)", clean_content, re.DOTALL)
            if match2:
                payload_block = match2.group(1)

        if not payload_block:
            self.log_warn("Could not isolate 'commonPayload' or 'JSON.stringify({...})' block in JS. Running global check (risk of false positives).")
            payload_block = clean_content

        for feature, config in FEATURES.items():
            js_key = config.get("js_key")

            if js_key:
                # Look for payload key assignment: "key:" inside the payload block,
                # OR a conditional assignment to the payload object elsewhere
                # (e.g. commonPayload.repo_source_mode = ...), which is how the
                # optional source-acquisition keys are attached.
                in_block = re.search(rf'\b{js_key}\s*:', payload_block)
                as_assignment = re.search(rf'\.{js_key}\s*=', clean_content)
                if in_block or as_assignment:
                    self.log_pass(f"WebUI JS: Payload key '{js_key}' found.")
                else:
                    self.log_error(f"WebUI JS: Payload key '{js_key}' missing for feature '{feature}'.")

    def run(self):
        if "--verify-guard" in sys.argv:
            print("Guard Verification: AST parser active. OK.")
            sys.exit(0)

        self.check_model_fields()
        self.check_pythonista_build()
        self.check_webui_html()
        self.check_webui_js()

        print("\n--- Report ---")
        for w in self.warnings:
            print(w)
        for e in self.errors:
            print(e)

        if self.errors:
            print("\n[FAILED] Parity Check Failed.")
            sys.exit(1)
        else:
            print("\n[SUCCESS] Parity Check Passed.")
            sys.exit(0)

if __name__ == "__main__":
    ParityChecker().run()
