import os
from pathlib import Path, PurePosixPath


def _validated_relative_parts(relpath: str) -> tuple[str, ...]:
    """Return normalized POSIX path parts for one root-bounded relative path."""
    if not isinstance(relpath, str):
        raise ValueError("relpath must be a string")
    if not relpath or relpath != relpath.strip():
        raise ValueError("relpath must be non-empty and unpadded")
    if "\x00" in relpath or "\\" in relpath or ":" in relpath:
        raise ValueError(
            "Relative paths must not contain NUL bytes, backslashes, or colons"
        )
    if os.path.isabs(relpath):
        raise ValueError("Absolute paths are forbidden")

    parts = relpath.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Empty, dot, and parent path segments are forbidden")

    normalized = PurePosixPath(relpath)
    if normalized.is_absolute() or normalized.as_posix() != relpath:
        raise ValueError("Relative path must already be normalized POSIX syntax")
    return normalized.parts


def resolve_secure_path(root: Path, relpath: str) -> Path:
    """Resolve a normalized relative path beneath an existing trusted directory root."""
    raw_root = str(root)
    if not raw_root.strip() or "\x00" in raw_root:
        raise ValueError("Invalid root path")

    parts = _validated_relative_parts(relpath)
    try:
        # `root` is chosen by the application/operator, and `relpath` has passed the
        # strict component allowlist above. The comments document the custom barrier
        # for CodeQL, which cannot infer the component-level validation.
        root_abs = Path(root).resolve(strict=True)  # lgtm[py/path-injection]
        if not root_abs.is_dir():
            raise ValueError("Root must be an existing directory")
        candidate = root_abs.joinpath(*parts)
        resolved = candidate.resolve(strict=False)  # lgtm[py/path-injection]
        resolved.relative_to(root_abs)
        return resolved
    except (ValueError, RuntimeError, OSError) as exc:
        raise ValueError("Path resolution failed") from exc
