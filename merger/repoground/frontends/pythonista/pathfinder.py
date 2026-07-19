#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import os
import sys

print("RUNNING FILE:", __file__)

try:
    import console  # type: ignore
except Exception:
    console = None  # type: ignore


def safe_script_path() -> Path:
    try:
        return Path(__file__).resolve()
    except Exception:
        # letzte Rettung: aktuelles Verzeichnis
        return Path.cwd().resolve() / "repoground-hub-pathfinder.py"


def _is_pythonista_runtime() -> bool:
    sp = str(sys.executable)
    return ("/private/var/mobile/" in sp) or ("Pythonista" in sp)


def _depth(root: Path, p: Path) -> int:
    try:
        rel = p.resolve().relative_to(root.resolve())
        return len(rel.parts)
    except Exception:
        return 10**9


def find_repoground_dirs_in_tree(root: Path, max_depth: int = 8) -> list[Path]:
    found: list[Path] = []
    try:
        root_res = root.resolve()
    except Exception as e:
        print(f"[pathfinder] Error resolving root {root}: {e}", file=sys.stderr)
        root_res = root

    try:
        for hit in root_res.rglob("build.py"):
            expected_tail = ("merger", "repoground", "frontends", "pythonista", "build.py")
            if tuple(hit.parts[-5:]) != expected_tail:
                continue
            if _depth(root_res, hit) > max_depth:
                continue
            d = hit.parent
            if d.is_dir():
                found.append(d)
    except Exception as e:
        print(f"[pathfinder] Error scanning tree {root_res}: {e}", file=sys.stderr)

    # uniq
    uniq: list[Path] = []
    for d in found:
        if d not in uniq:
            uniq.append(d)
    return uniq


def find_repoground_dirs(home: Path) -> list[Path]:
    """
    Heuristik: typische Install-Orte in Pythonista.
    Wir schreiben den Pfad in jedes gefundene kanonische RepoGround-Verzeichnis.
    """
    candidates = [
        # Canonical RepoGround path
        home / "merger" / "repoground" / "frontends" / "pythonista",

        home / "wc-merger",
        home / "merger" / "wc-merger",
    ]


    # Add standard iCloud path for Pythonista (diagnostic candidate only)
    icloud_docs = Path("/private/var/mobile/Library/Mobile Documents/iCloud~com~omz-software~Pythonista3/Documents")
    if icloud_docs.exists():
        candidates.extend([
            icloud_docs / "merger" / "repoground" / "frontends" / "pythonista",
            icloud_docs / "wc-merger",
            icloud_docs / "merger" / "wc-merger",
        ])

    found: list[Path] = []
    for d in candidates:
        try:
            if d.is_dir():
                # Canonical RepoGround installs are recognized by the Pythonista build entrypoint
                if (d / "build.py").exists():
                    found.append(d)
        except Exception as e:
            print(f"[pathfinder] Error checking candidate {d}: {e}", file=sys.stderr)

    # Duplikate entfernen, Reihenfolge behalten
    uniq: list[Path] = []
    for d in found:
        if d not in uniq:
            uniq.append(d)
    return uniq


def write_pathfile(target_dir: Path, hub_dir: Path) -> tuple[bool, str]:
    out_file = target_dir / ".repoground-hub-path.txt"
    try:
        out_file.write_text(str(hub_dir), encoding="utf-8")
        return True, str(out_file)
    except Exception as e:
        return False, f"{out_file} -> {e}"


def main() -> int:
    script_path = safe_script_path()
    hub_dir = script_path.parent.resolve()  # <- das ist der ganze Trick

    if not hub_dir.is_dir():
        msg = f"Not a directory (script parent): {hub_dir}"
        print(msg)
        if console:
            console.alert("RepoGround hub pathfinder", msg, "OK", hide_cancel_button=True)
        return 2

    home = Path(os.path.expanduser("~")).resolve()

    # 1) immer in den Hub selbst schreiben
    ok_hub, info_hub = write_pathfile(hub_dir, hub_dir)

    # 2) also update discovered canonical RepoGround installation directories
    repoground_dirs = find_repoground_dirs(home)

    # NEW BLOCK: Scan current hub tree if not on Pythonista
    if not _is_pythonista_runtime():
        repoground_dirs.extend(find_repoground_dirs_in_tree(hub_dir, max_depth=8))

    # final uniq
    uniq: list[Path] = []
    for d in repoground_dirs:
        if d not in uniq:
            uniq.append(d)
    repoground_dirs = uniq

    results = []
    for d in repoground_dirs:
        ok, info = write_pathfile(d, hub_dir)
        results.append((ok, info))

    lines = []
    lines.append(f"Hub detected as script folder:\n{hub_dir}\n")
    lines.append("Written files:")

    lines.append(f"- HUB: {'OK' if ok_hub else 'FAIL'}  {info_hub}")

    if repoground_dirs:
        for (d, (ok, info)) in zip(repoground_dirs, results):
            lines.append(f"- RepoGround build @ {d}: {'OK' if ok else 'FAIL'}  {info}")

        # Ambiguity check
        if len(repoground_dirs) > 1:
            warn_msg = f"WARNING: Found {len(repoground_dirs)} RepoGround build locations; clean up duplicate installations."
            lines.append("")
            lines.append(warn_msg)
            print(warn_msg, file=sys.stderr)
            if console:
                 console.hud_alert("Multiple RepoGround builds found", "error", 2.0)

    else:
        lines.append("- RepoGround build: (not found automatically)")

    msg = "\n".join(lines)
    print(msg)

    if console:
        console.alert("RepoGround hub pathfinder", msg, "OK", hide_cancel_button=True)

    # Wenn der Hub-Eintrag schon nicht geht, ist es wirklich kaputt.
    return 0 if ok_hub else 3


if __name__ == "__main__":
    raise SystemExit(main())
