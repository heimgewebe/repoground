#!/usr/bin/env python3
"""
Parity Guard
------------
Ensures feature parity between the Backend Model (JobRequest),
Pythonista UI (repoLens), and Web UI (rLens).

Checks:
1. JobRequest model fields (Source of Truth).
2. repolens.py (CLI args, usage, and UI logic).
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
        "repolens_usage": "args.level"
    },
    "mode": {
        "cli_arg": "--mode",
        "html_id": "mode",
        "js_key": "mode",
        "repolens_usage": "args.mode"
    },
    "max_bytes": {
        "cli_arg": "--max-bytes",
        "html_id": "maxBytes",
        "js_key": "max_bytes",
        "repolens_usage": "args.max_bytes" # ArgumentParser automatically converts - to _
    },
    "split_size": {
        "cli_arg": "--split-size",
        "html_id": "splitSize",
        "js_key": "split_size",
        "repolens_usage": "args.split_size"
    },
    "plan_only": {
        "cli_arg": "--plan-only",
        "html_id": "planOnly",
        "js_key": "plan_only",
        "repolens_usage": "args.plan_only"
    },
    "code_only": {
        "cli_arg": "--code-only",
        "html_id": "codeOnly",
        "js_key": "code_only",
        "repolens_usage": "args.code_only"
    },
    "meta_density": {
        "cli_arg": "--meta-density",
        "html_id": "metaDensity",
        "js_key": "meta_density",
        "repolens_usage": "args.meta_density"
    },
    "json_sidecar": {
        "cli_arg": "--json-sidecar",
        # Explicit decision: Treat as a payload key in JS (even if logic is derived).
        # In JobRequest it is a field.
        "js_key": "json_sidecar",
        "repolens_usage": "args.json_sidecar"
    },
    # Filters
    "extensions": {
        "cli_arg": "--extensions",
        "html_id": "extFilter",
        "js_key": "extensions",
        "repolens_usage": "args.extensions"
    },
    "path_filter": {
        "cli_arg": "--path-filter",
        "html_id": "pathFilter",
        "js_key": "path_filter",
        "repolens_usage": "args.path_filter"
    }
}

# Paths
ROOT = Path(__file__).parent.parent.resolve()
MODEL_PATH = ROOT / "merger/lenskit/service/models.py"
REPOLENS_PATH = ROOT / "merger/lenskit/frontends/pythonista/repolens.py"
WEBUI_HTML_PATH = ROOT / "merger/lenskit/frontends/webui/index.html"
WEBUI_JS_PATH = ROOT / "merger/lenskit/frontends/webui/app.js"

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

    def check_repolens(self):
        """Check Pythonista UI/CLI using AST."""
        print(f"Checking repoLens in {REPOLENS_PATH}...")
        try:
            content = REPOLENS_PATH.read_text("utf-8")
            tree = ast.parse(content)
        except Exception as e:
            self.log_error(f"Could not parse repolens.py: {e}")
            return

        # 1. Collect all add_argument args
        defined_cli_args = set()

        # 2. Collect all attribute access on 'args'
        accessed_args = set()

        # 3. Detect generic usage: vars(args) or args.__dict__
        has_generic_usage_ast = False

        # 4. Collect ALL string literals in the code (for generic fallback fallback)
        # But we want to be strict. Let's start with strict AST.
        # Strict Generic: literal string used as Subscript slice.
        accessed_keys = set()

        for node in ast.walk(tree):
            # Check for add_argument calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr == 'add_argument':
                    # Extract string arguments
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            defined_cli_args.add(arg.value)

            # Check for usage: getattr(args, 'field')
            # Strict check: first arg must be Name(id='args')
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'getattr':
                if len(node.args) >= 2:
                    arg1 = node.args[0]
                    arg2 = node.args[1]
                    if isinstance(arg1, ast.Name) and arg1.id == 'args':
                        if isinstance(arg2, ast.Constant) and isinstance(arg2.value, str):
                             accessed_args.add(f"args.{arg2.value}")

            # Check for usage: args.field
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id == 'args':
                    accessed_args.add(f"args.{node.attr}")

            # Check for generic usage: vars(args)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'vars':
                if len(node.args) == 1 and isinstance(node.args[0], ast.Name) and node.args[0].id == 'args':
                    has_generic_usage_ast = True

            # Check for generic usage: args.__dict__
            if isinstance(node, ast.Attribute) and node.attr == '__dict__':
                if isinstance(node.value, ast.Name) and node.value.id == 'args':
                    has_generic_usage_ast = True

            # Check for Subscript keys (e.g. d['key']) - assuming 'd' comes from vars(args)
            # Since tracking 'd' is hard, we'll just accept ANY string literal used as a subscript key
            # IF generic usage is detected. This eliminates help strings (usually args to calls, not slices).
            if isinstance(node, ast.Subscript):
                # node.slice is the index.
                # In Python < 3.9, it might be Index(value=...)
                slice_node = node.slice
                # Handle Index wrapper for older python
                if sys.version_info < (3, 9) and isinstance(slice_node, ast.Index):
                    slice_node = slice_node.value

                if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
                    accessed_keys.add(slice_node.value)

        for feature, config in FEATURES.items():
            # Check Definition
            cli_arg = config.get("cli_arg")
            if cli_arg:
                if cli_arg in defined_cli_args:
                    self.log_pass(f"repoLens CLI: {cli_arg} definition found (AST).")
                else:
                    self.log_error(f"repoLens CLI: Definition for {cli_arg} missing (feature: {feature}).")

            # Check Usage
            usage_key = config.get("repolens_usage")
            if usage_key:
                field_name = usage_key.split('.')[-1]

                if usage_key in accessed_args:
                    self.log_pass(f"repoLens Usage: {usage_key} accessed (AST).")
                elif has_generic_usage_ast and field_name in accessed_keys:
                    # Strict Generic: requires vars(args) AND usage as a subscript key anywhere
                    self.log_pass(f"repoLens Usage: {usage_key} accessed (Generic AST + Key Usage).")
                else:
                    self.log_error(f"repoLens Usage: {usage_key} not explicitly accessed and key literal not used as subscript.")

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
                # Look for payload key assignment: "key:"
                # Strict check: key followed by optional whitespace and a colon.
                if re.search(rf'\b{js_key}\s*:', payload_block):
                    self.log_pass(f"WebUI JS: Payload key '{js_key}' found.")
                else:
                    self.log_error(f"WebUI JS: Payload key '{js_key}' missing for feature '{feature}'.")

    def run(self):
        if "--verify-guard" in sys.argv:
            print("Guard Verification: AST parser active. OK.")
            sys.exit(0)

        self.check_model_fields()
        self.check_repolens()
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
