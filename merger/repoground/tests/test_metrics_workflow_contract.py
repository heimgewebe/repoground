from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import yaml


WORKFLOW_PATH = Path(".github/workflows/metrics.yml")
KEYWORDS_PATH = Path("scripts/ci/ajv_metrics_keywords.cjs")
EXPECTED_SCHEMA_COMMIT = "cba66e2b08d908aeff201e4e43aa902b96762b47"
EXPECTED_SCHEMA_SHA256 = "1b1de44ea326ce8de36da6fc6d8f2da0abe279df8c47ab10e58ddc2cf604b914"
EXPECTED_SCHEMA_URL = (
    "https://raw.githubusercontent.com/heimgewebe/metarepo/"
    f"{EXPECTED_SCHEMA_COMMIT}/contracts/metrics.snapshot.schema.json"
)


def _workflow() -> dict[str, object]:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_metrics_schema_is_bound_to_immutable_metarepo_content() -> None:
    workflow = _workflow()
    env = workflow["env"]

    assert env["METRICS_SCHEMA_URL"] == EXPECTED_SCHEMA_URL
    assert env["METRICS_SCHEMA_SHA256"] == EXPECTED_SCHEMA_SHA256
    assert re.fullmatch(r"[0-9a-f]{40}", EXPECTED_SCHEMA_COMMIT)
    assert re.fullmatch(r"[0-9a-f]{64}", env["METRICS_SCHEMA_SHA256"])
    assert "contracts-v1" not in env["METRICS_SCHEMA_URL"]


def test_metrics_workflow_verifies_download_before_ajv_validation() -> None:
    workflow = _workflow()
    steps = workflow["jobs"]["snapshot"]["steps"]
    fetch_index = next(i for i, step in enumerate(steps) if step.get("name") == "Fetch pinned AJV schema")
    validate_index = next(i for i, step in enumerate(steps) if step.get("name") == "Validate metrics contract")
    fetch_script = steps[fetch_index]["run"]
    validate_script = steps[validate_index]["run"]

    assert fetch_index < validate_index
    assert '"$METRICS_SCHEMA_URL"' in fetch_script
    assert '"$METRICS_SCHEMA_SHA256"' in fetch_script
    assert "sha256sum --check --strict" in fetch_script
    assert "--connect-timeout 5" in fetch_script
    assert "--max-time 30" in fetch_script
    assert "npx --yes ajv-cli@5.0.0 validate" in validate_script
    assert "--spec=draft2020" in validate_script
    assert "-c ./scripts/ci/ajv_metrics_keywords.cjs" in validate_script
    assert "--strict=false" not in validate_script
    assert workflow["jobs"]["snapshot"]["timeout-minutes"] == 10


def test_optional_hauski_post_remains_non_blocking() -> None:
    workflow = _workflow()
    steps = workflow["jobs"]["snapshot"]["steps"]
    post = next(step for step in steps if step.get("name") == "Optional POST to hausKI")

    assert post["continue-on-error"] is True
    assert "HAUSKI_POST_URL" in str(post["if"])
    assert "--connect-timeout 5" in post["run"]
    assert "--max-time 30" in post["run"]


def test_metrics_ajv_extension_registers_only_declared_metadata_keywords() -> None:
    program = f"""
const addKeywords = require({json.dumps(str(KEYWORDS_PATH.resolve()))});
const rows = [];
addKeywords({{ addKeyword: (value) => rows.push(value) }});
process.stdout.write(JSON.stringify(rows));
"""
    completed = subprocess.run(
        ["node", "-e", program],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == [
        {"keyword": "x-producers", "schemaType": "array", "valid": True},
        {"keyword": "x-consumers", "schemaType": "array", "valid": True},
    ]
