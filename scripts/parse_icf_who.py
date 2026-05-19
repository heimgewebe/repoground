#!/usr/bin/env python3
"""Merge WHO ICF descriptions into local JSON datasets.

The script expects an `ifc-who.txt` source file containing WHO descriptions
and updates the JSON datasets we keep in `data/`.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple, Union

Code = str
Description = str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parse ifc-who.txt and backfill WHO descriptions into ICF JSON data."
        )
    )
    parser.add_argument(
        "--who-file",
        default=Path("data/ifc-who.txt"),
        type=Path,
        help="Path to the WHO source text file (default: data/ifc-who.txt).",
    )
    parser.add_argument(
        "--full-json",
        default=Path("data/icf-complete-full.json"),
        type=Path,
        help="Path to the primary ICF JSON database (default: data/icf-complete-full.json).",
    )
    parser.add_argument(
        "--codes-json",
        default=Path("data/icf_codes_complete.json"),
        type=Path,
        help="Path to the secondary codes JSON (default: data/icf_codes_complete.json).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Also replace existing WHO descriptions instead of filling missing ones only.",
    )
    return parser.parse_args()


def parse_who_text(lines: Iterable[str]) -> Dict[Code, Description]:
    """Parse WHO descriptions from a text stream.

    The parser is designed for lines formatted as:
    ``
    <CODE> <Description ...>
        <optional continuation>
    ``
    Continuation lines (starting with whitespace) are appended to the
    previous description.
    """

    descriptions: Dict[Code, str] = {}
    current_code: Code | None = None
    buffer: List[str] = []

    def flush() -> None:
        nonlocal buffer
        if current_code is None or not buffer:
            return
        text = " ".join(part.strip() for part in buffer if part.strip())
        if text:
            descriptions[current_code] = text
        buffer = []

    code_line = re.compile(r"^(?P<code>[A-Za-z]\w+)\s+(?P<desc>.+)$")

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        match = code_line.match(line)
        if match:
            # New entry begins, flush previous buffer.
            flush()
            current_code = match.group("code").strip()
            buffer = [match.group("desc").strip()]
            continue

        if current_code is None:
            # Skip lines that do not belong to any code.
            continue

        if line[0].isspace():
            buffer.append(line.strip())
        else:
            # Unexpected format: treat as new description without a code.
            flush()
            current_code = None

    flush()
    return descriptions


Dataset = Union[Dict[Code, dict], List[dict]]


def load_dataset(path: Path) -> Tuple[Dataset, Dict[Code, dict]]:
    if not path.exists():
        return {}, {}

    with path.open("r", encoding="utf-8") as handle:
        data: Dataset = json.load(handle)

    if isinstance(data, list):
        index = {entry.get("code"): entry for entry in data if "code" in entry}
    elif isinstance(data, dict):
        index = data
    else:
        raise TypeError(f"Unsupported JSON structure in {path}: {type(data).__name__}")
    return data, index


def update_descriptions(
    index: Dict[Code, dict],
    who_descriptions: Dict[Code, Description],
    overwrite: bool = False,
) -> int:
    updated = 0
    for code, description in who_descriptions.items():
        entry = index.get(code)
        if entry is None:
            continue
        existing = entry.get("who_description") or ""
        if existing and not overwrite:
            continue
        entry["who_description"] = description
        updated += 1
    return updated


def persist_dataset(path: Path, data: Dataset) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> None:
    args = parse_args()
    who_path: Path = args.who_file

    if not who_path.exists():
        raise FileNotFoundError(
            f"WHO source file not found: {who_path}. Please place ifc-who.txt under data/."
        )

    who_descriptions = parse_who_text(who_path.read_text(encoding="utf-8").splitlines())
    if not who_descriptions:
        raise ValueError("No WHO descriptions found in the provided source file.")

    updated_total = 0
    for json_path in (args.full_json, args.codes_json):
        data, index = load_dataset(json_path)
        if not index:
            # Nothing to update yet; leave a stub file so future runs can succeed.
            data = {}
            index = data
        updated = update_descriptions(index, who_descriptions, overwrite=args.overwrite)
        persist_dataset(json_path, data)
        print(f"Updated {updated} entries in {json_path}.")
        updated_total += updated

    print(f"Finished. Total entries updated: {updated_total}.")


if __name__ == "__main__":
    main()
