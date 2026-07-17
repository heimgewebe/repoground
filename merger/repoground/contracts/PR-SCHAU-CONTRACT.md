# PR-Schau Contract (v1.0)

**Thesis:** PR-Schau must never silently truncate content. It must split or explicitly mark truncation in a machine-readable way.

## 0. Compatibility & Rollout Rule (Normative)

This schema is intentionally strict (`additionalProperties:false`). Therefore:

1.  **Paired Change Rule:** Any change that introduces or tightens required fields in
    `pr-schau.v1.schema.json` **MUST** be merged together with an updated producer implementation
    (e.g. `generate_review_bundle`) and tests that validate real output against the schema.
2.  **No-Legacy Acceptance:** Consumers and validators **MUST NOT** accept legacy flat bundle formats
    (e.g. top-level `repo`, `created_at`, numeric `version`, `hub_rel`, etc.). Such acceptance would
    reintroduce epistemic errors via silent drift.
3.  **CI as Gate:** The repository CI **MUST** fail if the current producer output does not validate
    against this schema (see regression guard tests).

Rationale: A strict contract without a strict producer gate creates a false sense of safety.

PR-Schau is a two-layer artifact:
1.  **Index Layer (Portable Manifest / Index Entry Point):** A JSON sidecar (`bundle.json` conforming to `pr-schau.v1.schema.json`) that acts as the machine-readable map of the bundle. It is **NOT** the canonical content, but the guide to it.
2.  **Content Layer (Canonical Content):** One or more Markdown files (`review.md`, `review_part2.md`, etc.) that contain the actual review content. These files are the authoritative source of human-readable information.

## 1. Completeness Policy ("No-Truncate")

To prevent epistemic errors ("hallucination on partial data"), the generator must adhere to the following rules:

*   **No Silent Truncation:** If the content exceeds a single-file limit (e.g., 40KB or 200KB), the generator **MUST NOT** simply cut it off with a text note.
*   **Splitting:** The preferred strategy is to split the content into multiple parts (`review.md`, `review_part2.md`, ...).
*   **Machine-Readable Truth:** The `completeness` block in the JSON Index determines the reliability of the content.

### JSON Completeness Block
```json
"completeness": {
  "is_complete": true,
  "policy": "split",
  "parts": ["review.md", "review_part2.md"],
  "primary_part": "review.md",
  "expected_bytes": 150000,
  "emitted_bytes": 150512
}
```

If `is_complete` is `false`, the consumer must treat the review as a **Preview** or **Index**, not as the canonical source of truth.

## 2. Artifacts & Linking

The JSON Index acts as the portable manifest. It links to artifacts using relative `basename` references, allowing the bundle to be moved (e.g., zipped, attached to tickets) without breaking links.

```json
"artifacts": [
  {
    "role": "index_json",
    "basename": "bundle.json",
    "mime": "application/json"
  },
  {
    "role": "canonical_md",
    "basename": "review.md",
    "sha256": "...",
    "mime": "text/markdown"
  },
  {
    "role": "part_md",
    "basename": "review_part2.md",
    "sha256": "...",
    "mime": "text/markdown"
  }
]
```

## 3. Semantic Zones (Markdown)

To facilitate robust parsing of the human-readable Markdown by AI agents, the content should be wrapped in Semantic Zone Markers. These markers are HTML comments that do not affect rendering but provide clear boundaries.

**Syntax:** `<!-- zone:begin type=<type> [attrs...] -->` ... `<!-- zone:end -->`

**Standard Zones:**

*   `summary`: High-level stats (added, removed, changed). **MUST** exist.
*   `files_manifest`: The list/table of changed files. **MUST** exist.
*   `diff`: The actual file content diffs or full content.
*   `hotspots`: (Optional) List of critical files.

## 4. Guards & Enforcement

Ethical guidelines are insufficient; physical constraints are required.

1.  **"No-Truncate" Guard:** CI/CD or consumption tools **MUST** fail validation if the text "Content truncated at" (or similar generator-specific strings) appears in the Markdown content, UNLESS `completeness.policy` is explicitly set to `"truncate"` and `completeness.is_complete` is `false`.
2.  **Integrity Guard:** Tools **MUST** verify that:
    *   All files listed in `completeness.parts` exist.
    *   `primary_part` is present in `parts`.
    *   Every entry in `parts` has a corresponding artifact in `artifacts` with a matching `basename`.
    *   All files match their declared SHA256 checksums (required for `canonical_md` and `part_md`).

## 5. Byte Semantics & Tolerances

To ensure rigorous completeness checks:

*   **`expected_bytes`**: The computed size of the logical content payload (un-splitted text) before any file splitting or header overhead is added.
*   **`emitted_bytes`**: The sum of the actual file sizes (in bytes) of all files listed in `parts`.
*   **Overhead Tolerance:** When `is_complete` is `true`, `emitted_bytes` must be effectively equal to `expected_bytes`.
    *   **Normative Rule:** `emitted_bytes` MUST NOT exceed `expected_bytes` by more than **64KB** (or 5% of `expected_bytes`, whichever is larger). This allowance covers repeated headers and markdown metadata in split files.

## 6. Verification Status

To combat the assumption that "existence implies correctness", bundles MAY include a `verification` block stamped by a checking tool (e.g., `pr-schau-verify`).

```json
"verification": {
  "checked_at": "2023-10-27T10:05:00Z",
  "checker": { "name": "pr-schau-verify", "version": "1.0.0" },
  "level": "full"
}
```

### Verification Levels (Normative)

*   **`none`** (or missing): No verification performed. Consumers **SHOULD** treat missing verification as `level='none'` (untrusted).
*   **`basic`**:
    *   JSON Schema validation passed.
    *   All files listed in `parts` physically exist on disk.
*   **`full`**:
    *   **Includes `basic`.**
    *   All file hashes (SHA256) match artifacts.
    *   `primary_part` is confirmed present in `parts`.
    *   Cross-reference check: Every part has a corresponding artifact entry.
    *   "No-Truncate" guard passed (no truncation text found in MD).
    *   Byte overhead tolerance check passed.

## 7. View Modes & Content Scope

*   `view_mode`: High-level intent (`delta` vs `full`).
*   `content_scope`: Precise content nature.
    *   `diff`: Only unified diffs (no full files).
    *   `fullfiles`: Full content of changed/added files.
    *   `mixed`: Combination (e.g., small files full, large files diffed).

## 8. Future Directions (v2)

*   **Decision Coverage:** A future evolution may introduce "Decision Coverage" – ensuring that while not *all* files are full, all *decision-critical* files (security, contracts, core logic) are present as `fullfiles`.

## 9. Two-Layer Artifact Pattern

PR-Schau follows the [Two-Layer Artifact Pattern](../../../docs/architecture/two-layer-artifact-pattern.md):

- JSON describes navigation, completeness, and integrity.
- Markdown contains the readable content.
- JSON must not be treated as complete content proof.

## 10. Versioning

This is **Version 1.0** of the PR-Schau Contract.
Schema URI: `https://heimgewebe.local/schema/pr-schau.v1.schema.json`
