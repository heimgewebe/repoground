# Frontend Feature Parity Guard

## Overview
To prevent feature divergence between the WebUI (`rLens`) and Pythonista UI (`repoLens`), we have implemented a mechanized guard. This script ensures that control fields defined in the backend `JobRequest` model are exposed in both frontends.

## The Guard Script
The script is located at `tools/parity_guard.py`.

It performs strict heuristic checks using Python AST and Regex:
1.  **Backend Model**: Ensures features exist in `JobRequest` (AST check).
2.  **Pythonista CLI (`repolens.py`)**:
    *   **Definition:** Verifies that `argparse` definitions exist for the feature. It walks the Python AST to find `add_argument` calls and their string literal arguments.
    *   **Usage:** Verifies that the argument is accessed in the script logic.
        *   Checks for explicit access: `args.my_feature`.
        *   Checks for dynamic access: `getattr(args, 'my_feature')`.
        *   Checks for generic serialization: `vars(args)` or `args.__dict__` combined with the presence of the key literal.
3.  **Web UI HTML (`index.html`)**: Checks for input elements with specific IDs matching the feature.
4.  **Web UI JS (`app.js`)**: Checks for payload construction logic. It specifically isolates the `commonPayload` or `JSON.stringify` object definitions (ignoring comments) to prevent false positives from unused keys.

## Code Conventions
To ensure the guard works correctly, please adhere to these conventions:
*   **CLI Flags:** Must be defined as string literals in `add_argument(...)` calls. Dynamic flag construction is not supported.
*   **Argument Access:** Must act on the `args` object (e.g., `args.field` or `getattr(args, ...)`). `getattr` on other objects will not count as usage.
*   **JS Payload:** Should be defined in a `const commonPayload = { ... }` block or directly inside `JSON.stringify({ ... })`.

## Feature Definitions
The guard uses a `FEATURES` dictionary to map backend fields to frontend implementation details.
*   **`cli_arg`**: The expected CLI flag (e.g., `--my-feature`).
*   **`repolens_usage`**: The expected variable access (e.g., `args.my_feature`).
*   **`html_id`**: The ID of the input element in HTML.
*   **`js_key`**: The key used in the JSON payload object in `app.js`.

### Special Case: `json_sidecar`
While `json_sidecar` is technically derived from the "extras" string in some contexts, the Parity Guard enforces that it is present as an explicit key in the `app.js` payload object to match the `JobRequest` boolean field. This ensures explicit control.

## Usage
Run the script from the repository root:

```bash
python3 tools/parity_guard.py
```

### Self-Verification
To verify the guard's own internal logic against tricky patterns (Red-Team test), run:

```bash
python3 tools/parity_guard.py --verify-guard
```

## Adding New Features
When adding a new feature (control) to `JobRequest`:
1.  Add the field to `JobRequest` in `merger/lenskit/service/models.py`.
2.  Add the feature to the `FEATURES` dictionary in `tools/parity_guard.py` with all required mappings.
3.  Run the script. It will fail.
4.  Implement the feature in `repolens.py` (CLI argument + Usage logic).
5.  Implement the feature in `index.html` (Input element) and `app.js` (Payload logic).
6.  Run the script again. It should pass.

## CI Integration
The parity guard is implemented, self-tested, and wired into CI via `.github/workflows/parity_check.yml`.
The workflow runs `pytest tests/test_parity_guard.py` and `python3 tools/parity_guard.py` on push and pull-request events targeting `main`/`master`, triggered by path filters on the relevant frontend and guard files.
This is dedicated path-scoped CI enforcement; it is not a statement that every repository workflow executes the guard unconditionally.

## Scope Boundary
`tools/parity_guard.py` is a frontend-surface guard (JobRequest field parity across backend model, Pythonista CLI and WebUI payload/ids).

Real dump parity evidence is a separate workflow based on bundle manifests and diagnostic artifacts:

- CLI: `lenskit parity compare LEFT_MANIFEST RIGHT_MANIFEST --json`
- Core state builder: `merger/lenskit/core/parity_state.py`
- Gate evaluator: `merger/lenskit/core/parity_gates.py`

This dump-compare path is parser/CLI foundation for evidence-based parity checks. It is not automatically a global CI blocker unless explicitly wired as such in CI policy/workflows.
