from __future__ import annotations

import argparse
import re
from pathlib import Path

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SAFE_PATH_RE = re.compile(r"^/[A-Za-z0-9._/-]+$")


def _safe_absolute_path(value: str | Path, *, label: str) -> Path:
    text = str(value)
    path_segments = text.split("/")
    if (
        not SAFE_PATH_RE.fullmatch(text)
        or "//" in text
        or any(segment in {".", ".."} for segment in path_segments)
        or (text != "/" and text.endswith("/"))
    ):
        raise ValueError(f"{label} must be a canonical simple absolute path")
    return Path(text)


def render_service_unit(
    *,
    commit: str,
    runtime_dir: str | Path,
    python_path: str | Path,
    env_file: str | Path,
) -> str:
    if not COMMIT_RE.fullmatch(commit):
        raise ValueError("commit must be a full 40-character lowercase SHA-1")
    runtime = _safe_absolute_path(runtime_dir, label="runtime_dir")
    python = _safe_absolute_path(python_path, label="python_path")
    env = _safe_absolute_path(env_file, label="env_file")
    if runtime.name != commit:
        raise ValueError("runtime_dir basename must equal commit")
    expected_python = runtime / ".venv" / "bin" / "python"
    if python != expected_python:
        raise ValueError("python_path must be <runtime_dir>/.venv/bin/python")

    return f"""[Unit]
Description=RepoGround Web UI / Atlas Browser
After=network.target
StartLimitIntervalSec=60
StartLimitBurst=5
ConditionPathIsDirectory={runtime}

[Service]
Type=simple
Environment=REPOGROUND_HUB=%h/repos
Environment=REPOGROUND_MERGES=%h/repoground-out
Environment=REPOGROUND_HOST=127.0.0.1
Environment=REPOGROUND_PORT=8787
EnvironmentFile={env}
Environment=REPOGROUND_SERVICE_UNIT=repoground
Environment=REPOGROUND_VERSION={commit}
Environment=REPOGROUND_BUILD_ID={commit}
Environment=PYTHONPATH={runtime}
Environment=PYTHONDONTWRITEBYTECODE=1
WorkingDirectory={runtime}
ExecStartPre=/usr/bin/test -d {runtime}
ExecStartPre=/usr/bin/test -x {python}
ExecStartPre=/bin/sh -c 'test -n "$REPOGROUND_TOKEN" || {{ echo "REPOGROUND_TOKEN is required" >&2; exit 1; }}'
ExecStart={python} -m merger.repoground serve
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a commit-bound RepoGround production systemd unit"
    )
    parser.add_argument("--commit", required=True)
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        rendered = render_service_unit(
            commit=args.commit,
            runtime_dir=args.runtime_dir,
            python_path=args.python,
            env_file=args.env_file,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.output:
        output = Path(args.output)
        if output.exists() or output.is_symlink():
            parser.error("--output must not already exist")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
