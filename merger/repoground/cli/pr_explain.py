import argparse
import sys
import json
from pathlib import Path

def run_pr_explain(args: argparse.Namespace) -> int:
    delta_path = Path(args.delta)
    if not delta_path.exists():
        print(f"Error: PR delta file not found: {delta_path}", file=sys.stderr)
        return 1

    try:
        with open(delta_path, 'r', encoding='utf-8') as f:
            delta_data = json.load(f)

        print("PR Explain:")
        print(f"Repository: {delta_data.get('repo')}")

        summary = delta_data.get('summary', {})
        print(f"Summary: +{summary.get('added', 0)} ~{summary.get('changed', 0)} -{summary.get('removed', 0)}")

        print("\nChanged files:")
        for file in delta_data.get('files', []):
            print(f"  {file.get('status', '').ljust(8)} {file.get('path')}")

            suspicious = file.get('suspicious_patterns', [])
            if suspicious:
                print(f"    [!] Suspicious patterns: {', '.join(suspicious)}")

            chunk_ids = file.get('affected_chunk_ids', [])
            if chunk_ids:
                print(f"    Affected chunks: {', '.join(chunk_ids)}")

    except json.JSONDecodeError as e:
        print(f"Error decoding JSON in delta file: {e}", file=sys.stderr)
        return 1
    except IOError as e:
        print(f"I/O error reading delta file: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error processing delta file: {e}", file=sys.stderr)
        return 1

    return 0
