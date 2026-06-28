import json
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts" / "architecture.source_roots.v1.schema.json"
EXAMPLE_PATH = ROOT / "contracts" / "examples" / "source_roots_minimal.json"


def _schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_source_roots_example_validates():
    jsonschema.Draft7Validator.check_schema(_schema())
    payload = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(payload, _schema())


@pytest.mark.parametrize(
    "root",
    [
        "",
        ".",
        "./src",
        "../src",
        "src/./pkg",
        "src/../pkg",
        "src/.",
        "/src",
        "src\\pkg",
        "src//pkg",
        "src/",
    ],
)
def test_source_roots_reject_noncanonical_paths(root):
    payload = {
        "kind": "lenskit.architecture.source_roots",
        "version": "1.0",
        "roots": [root],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())


def test_source_roots_reject_duplicates_and_unknown_fields():
    duplicate = {
        "kind": "lenskit.architecture.source_roots",
        "version": "1.0",
        "roots": ["src", "src"],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(duplicate, _schema())

    extra = {
        "kind": "lenskit.architecture.source_roots",
        "version": "1.0",
        "roots": ["src"],
        "autodiscover": True,
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(extra, _schema())
