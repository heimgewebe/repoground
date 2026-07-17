#!/usr/bin/env python3
"""
Validiert den @meta-Block eines WC-Merger-Reports gegen die JSON-Schemas.

Nutzung:

    python3 validate_merge_meta.py path/to/report.md

Voraussetzungen:
    pip install pyyaml jsonschema
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


def safe_script_path() -> Path:
    """
    Versucht, den Pfad dieses Skripts robust zu bestimmen.

    Reihenfolge:
    1. __file__ (Standard-Python)
    2. sys.argv[0] (z. B. in Shortcuts / eingebetteten Umgebungen)
    3. aktuelle Arbeitsdirectory (Last Resort)
    """
    try:
        return Path(__file__).resolve()
    except NameError:
        # Pythonista / Shortcuts oder exotischer Kontext
        argv0 = None
        try:
            if getattr(sys, "argv", None):
                argv0 = sys.argv[0] or None
        except Exception:
            argv0 = None

        if argv0:
            try:
                return Path(argv0).resolve()
            except Exception:
                pass

        # Fallback: aktuelle Arbeitsdirectory
        return Path.cwd().resolve()


# Cache script path at module level for consistent behavior
SCRIPT_PATH = safe_script_path()
SCRIPT_DIR = SCRIPT_PATH.parent


def extract_meta_block(markdown: str) -> dict:
    """
    Sucht den ersten @meta-Block im Markdown und parst den YAML-Inhalt.
    """
    meta_pattern = re.compile(
        r"<!-- @meta:start -->\s*```yaml\s*(?P<yaml>.*?)```",
        re.DOTALL,
    )
    match = meta_pattern.search(markdown)
    if not match:
        raise ValueError("Kein @meta-Block mit ```yaml ... ``` gefunden.")
    return yaml.safe_load(match.group("yaml"))


def load_schema(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_report_meta(report_path: Path) -> None:
    # Schemas liegen neben dem Skript, nicht zwingend neben dem Report
    text = report_path.read_text(encoding="utf-8")
    meta = extract_meta_block(text)

    merge_meta = meta.get("merge")
    if not isinstance(merge_meta, dict):
        raise ValueError("Im @meta-Block fehlt der Schlüssel 'merge' oder er ist kein Objekt.")

    # Hauptschema laden
    report_schema_path = (SCRIPT_DIR / "contracts" / "repolens-report.schema.json").resolve()
    if not report_schema_path.exists():
        raise FileNotFoundError(f"Schema nicht gefunden: {report_schema_path}")

    report_schema = load_schema(report_schema_path)
    merge_schema = report_schema["properties"]["merge"]

    validator = Draft202012Validator(merge_schema)
    errors = sorted(validator.iter_errors(merge_meta), key=lambda e: e.path)
    if errors:
        print(f"❌ Merge-Meta-Block in {report_path} verletzt das Schema:")
        for err in errors:
            path = ".".join(str(p) for p in err.path)
            print(f"  - [{path}] {err.message}")
        raise SystemExit(1)

    print(f"✅ Merge-Meta-Block in {report_path} ist schema-konform.")

    # Optional: Delta-Contract validieren, falls vorhanden
    delta = merge_meta.get("delta")
    if isinstance(delta, dict) and delta.get("type") == "repolens-delta":
        delta_schema_path = (SCRIPT_DIR / "contracts" / "repolens-delta.schema.json").resolve()
        if not delta_schema_path.exists():
            print("⚠️  Delta-Schema nicht gefunden, überspringe Delta-Validierung.")
            return
        delta_schema = load_schema(delta_schema_path)
        delta_validator = Draft202012Validator(delta_schema)
        delta_errors = sorted(delta_validator.iter_errors(delta), key=lambda e: e.path)
        if delta_errors:
            print("❌ Delta-Metadaten verletzen das Delta-Schema:")
            for err in delta_errors:
                path = ".".join(str(p) for p in err.path)
                print(f"  - [{path}] {err.message}")
            raise SystemExit(1)
        print("✅ Delta-Metadaten sind schema-konform.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path, help="Pfad zur Merge-Report-Markdown-Datei")
    args = parser.parse_args()

    validate_report_meta(args.report)


if __name__ == "__main__":
    main()
