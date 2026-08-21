import argparse
import sys
from pathlib import Path
from merger.repoground.retrieval import index_db


def _resolve_index_output_path(args: argparse.Namespace, chunk_path: Path) -> Path:
    if args.out:
        return Path(args.out)
    return chunk_path.with_suffix(".index.sqlite")


def _build_index_config_payload(
    args: argparse.Namespace, dump_path: Path
) -> dict[str, object]:
    config_payload: dict[str, object] = {"cli_args": str(args)}
    if dump_path.exists():
        import json

        try:
            dump_data = json.loads(dump_path.read_text(encoding="utf-8"))
            generator = dump_data.get("generator", {})
            config_payload["config_sha256"] = generator.get("config_sha256", "")
            config_payload["lenskit_version"] = generator.get("version", "unknown")
        except Exception:
            pass
    return config_payload


def run_index(args: argparse.Namespace) -> int:
    dump_path = Path(args.dump)
    chunk_path = Path(args.chunk_index)

    out_path = _resolve_index_output_path(args, chunk_path)

    if not dump_path.exists():
        print(f"Error: Dump file not found: {dump_path}", file=sys.stderr)
        return 1
    if not chunk_path.exists():
        print(f"Error: Chunk index file not found: {chunk_path}", file=sys.stderr)
        return 1

    if args.verify:
        print(f"Verifying index {out_path} against artifacts...")
        is_valid = index_db.verify_index(out_path, dump_path, chunk_path)
        if is_valid:
            print("✅ Index is valid and up-to-date.")
            return 0
        else:
            print("❌ Index is stale, missing, or invalid.")
            return 1

    if out_path.exists() and not args.rebuild:
        if index_db.verify_index(out_path, dump_path, chunk_path):
            print(f"Index {out_path} is already up-to-date. Use --rebuild to force.")
            return 0
        else:
            print(f"Index {out_path} is stale. Rebuilding...")

    print(f"Building index from {chunk_path.name}...")
    try:
        config_payload = _build_index_config_payload(args, dump_path)
        index_db.build_index(
            dump_path, chunk_path, out_path, config_payload=config_payload
        )
        print(f"✅ Index built successfully: {out_path}")
        return 0
    except Exception as e:
        print(f"❌ Error building index: {e}", file=sys.stderr)
        if out_path.exists():
            try:
                out_path.unlink()
            except OSError:
                pass
        return 1
