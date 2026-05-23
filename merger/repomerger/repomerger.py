#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
repomerger – Multi-Repo-Merge ohne Diff, mit Plan-Phase, Kategorien und 3 Detailstufen.

Funktionen:
- Erzeugt EIN Markdown-File mit Überblick über ein oder mehrere Repos.
- Inhalte:
  - Plan-Abschnitt (Metaüberblick mit Kategorien- und Endungsstatistik).
  - Baumstruktur über alle Quellen.
  - Manifest aller gefundenen Dateien.
  - Je nach Detailstufe: Inhalte von Textdateien (mit Größenlimit pro Datei).

Detailstufen:
- overview: Struktur + Manifest, keine Inhalte.
- summary:  Struktur + Manifest + Inhalte aller Textdateien <= max_file_bytes.
- full:     Struktur + Manifest + Inhalte aller Textdateien,
            größere Textdateien werden bis max_file_bytes gekürzt.

Besonderheiten:
- Keine Diffs zu früheren Läufen: jeder Merge ist ein eigenständiger Schnappschuss.
- Mehrere Repos pro Lauf möglich.
- .env / .env.* werden ignoriert, außer .env.example / .env.template / .env.sample.
- Merge-Dateien werden IMMER in den Ordner "merges" geschrieben (neben dem Script).
- Quellordner werden nach dem Merge gelöscht, WENN sie im gleichen Ordner wie das Script liegen
  (und nicht der merges-Ordner sind). Abschaltbar mit --no-delete.
"""

import argparse
import datetime
import hashlib
import os
import shutil
from pathlib import Path

# --- Konfiguration / Heuristiken --------------------------------------------

MERGES_DIR_NAME = "merges"

# Verzeichnisse, die standardmäßig ignoriert werden (rekursiv)
SKIP_DIRS = {
    ".git",
    ".idea",
    # bewusst NICHT: ".vscode" (tasks.json etc. sind interessant)
    "node_modules",
    ".svelte-kit",
    ".next",
    "dist",
    "build",
    "target",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".DS_Store",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    "coverage",
}

# Top-Level-Verzeichnisse, die bei Auto-Discovery nicht als Repos genommen werden sollen
SKIP_ROOTS = {
    MERGES_DIR_NAME,
    "merge",
    "output",
    "out",
}

# Einzelne Dateien, die ignoriert werden
SKIP_FILES = {
    ".DS_Store",
}

# Erweiterungen, die sehr wahrscheinlich Text sind
TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    ".rst",
    ".py",
    ".rs",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".jsonl",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".dockerfile",
    "dockerfile",
    ".svelte",
    ".css",
    ".scss",
    ".html",
    ".htm",
    ".xml",
    ".csv",
    ".log",
    ".lock",   # z.B. Cargo.lock, pnpm-lock.yaml
}

# Dateien, die typischerweise Konfiguration sind
CONFIG_FILENAMES = {
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "Cargo.toml",
    "Cargo.lock",
    "requirements.txt",
    "Pipfile",
    "Pipfile.lock",
    "poetry.lock",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Justfile",
    "Makefile",
    "toolchain.versions.yml",
    ".editorconfig",
    ".markdownlint.jsonc",
    ".markdownlint.yaml",
    ".yamllint",
    ".yamllint.yml",
    ".lychee.toml",
    ".vale.ini",
}

DOC_EXTENSIONS = {".md", ".rst", ".txt"}

LANG_MAP = {
    "py": "python", "js": "javascript", "ts": "typescript", "html": "html", "css": "css",
    "scss": "scss", "sass": "sass", "json": "json", "xml": "xml", "yaml": "yaml", "yml": "yaml",
    "md": "markdown", "sh": "bash", "bat": "batch", "sql": "sql", "php": "php", "cpp": "cpp",
    "c": "c", "java": "java", "cs": "csharp", "go": "go", "rs": "rust", "rb": "ruby",
    "swift": "swift", "kt": "kotlin", "svelte": "svelte",
}

SOURCE_EXTENSIONS = {
    ".py",
    ".rs",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".svelte",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".go",
    ".java",
    ".cs",
}


class FileInfo(object):
    """Einfache Container-Klasse für Dateimetadaten."""

    def __init__(self, root_label, abs_path, rel_path, size, is_text, md5, category, ext):
        self.root_label = root_label
        self.abs_path = abs_path
        self.rel_path = rel_path
        self.size = size
        self.is_text = is_text
        self.md5 = md5
        self.category = category
        self.ext = ext


# --- Hilfsfunktionen ---------------------------------------------------------

def human_size(n):
    """Formatierte Dateigröße, z.B. '1.23 MB'."""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            return "{0:.2f} {1}".format(size, unit)
        size /= 1024.0
    return "{0:.2f} GB".format(size)


def is_probably_text(path, size):
    """
    Heuristik: Ist dies eher eine Textdatei?

    - bekannte Text-Endungen -> True
    - große unbekannte Dateien -> eher False
    - ansonsten: 4 KiB lesen, auf NUL-Bytes prüfen.
    """
    name = path.name.lower()
    base, ext = os.path.splitext(name)
    if ext in TEXT_EXTENSIONS or name in TEXT_EXTENSIONS:
        return True

    # Sehr große unbekannte Dateien eher als binär behandeln
    if size > 20 * 1024 * 1024:  # 20 MiB
        return False

    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
    except OSError:
        return False

    if not chunk:
        return True
    if b"\x00" in chunk:
        return False

    return True


def compute_md5(path, limit_bytes=None):
    """
    MD5-Hash einer Datei.

    - Wenn limit_bytes gesetzt ist, lesen wir höchstens so viele Bytes.
    - Bei Fehlern: 'ERROR'.
    """
    # MD5 is used for file integrity checking, not cryptographic security
    try:
        h = hashlib.md5(usedforsecurity=False)
    except TypeError:
        # Fallback for Python < 3.9
        h = hashlib.md5()  # nosec B303
    try:
        with path.open("rb") as f:
            remaining = limit_bytes
            while True:
                if remaining is None:
                    chunk = f.read(65536)
                else:
                    chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                h.update(chunk)
                if remaining is not None:
                    remaining -= len(chunk)
                    if remaining <= 0:
                        break
        return h.hexdigest()
    except OSError:
        return "ERROR"


def lang_for(ext):
    """Ermittelt die Sprache für Markdown-Blöcke anhand der Endung."""
    return LANG_MAP.get(ext.lower().lstrip("."), "")


def classify_category(rel_path, ext):
    """
    Grobe Einteilung in doc / config / source / other.
    """
    name = rel_path.name
    if name in CONFIG_FILENAMES:
        return "config"
    if ext in DOC_EXTENSIONS:
        return "doc"
    if ext in SOURCE_EXTENSIONS:
        return "source"
    parts = [p.lower() for p in rel_path.parts]
    for p in parts:
        if p in ("config", "configs", "settings", "etc", ".github"):
            return "config"
    if "docs" in parts or "doc" in parts:
        return "doc"
    return "other"


def summarize_extensions(file_infos):
    """Anzahl und Gesamtgröße pro Dateiendung."""
    counts = {}
    sizes = {}
    for fi in file_infos:
        ext = fi.ext or "<none>"
        counts[ext] = counts.get(ext, 0) + 1
        sizes[ext] = sizes.get(ext, 0) + fi.size
    return counts, sizes


def summarize_categories(file_infos):
    """Anzahl und Gesamtgröße pro Kategorie."""
    stats = {}
    for fi in file_infos:
        cat = fi.category or "other"
        if cat not in stats:
            stats[cat] = [0, 0]
        stats[cat][0] += 1
        stats[cat][1] += fi.size
    return stats


def scan_repo(repo, md5_limit_bytes):
    """
    Scannt ein einzelnes Repo und erzeugt FileInfo-Einträge.
    """
    repo = repo.resolve()
    root_label = repo.name
    files = []

    for dirpath, dirnames, filenames in os.walk(str(repo)):
        # Verzeichnisse filtern
        keep_dirs = []
        for d in dirnames:
            if d in SKIP_DIRS:
                continue
            keep_dirs.append(d)
        dirnames[:] = keep_dirs

        for fn in filenames:
            if fn in SKIP_FILES:
                continue

            # .env und .env.* ignorieren, außer expliziten Vorlagen
            if fn.startswith(".env") and fn not in (".env.example", ".env.template", ".env.sample"):
                continue

            abs_path = Path(dirpath) / fn
            try:
                st = abs_path.stat()
            except OSError:
                continue
            size = st.st_size

            rel = abs_path.relative_to(repo)
            ext = abs_path.suffix.lower()

            is_text = is_probably_text(abs_path, size)

            if is_text or size <= md5_limit_bytes:
                md5 = compute_md5(abs_path, md5_limit_bytes)
            else:
                md5 = ""

            category = classify_category(rel, ext)

            fi = FileInfo(
                root_label=root_label,
                abs_path=abs_path,
                rel_path=rel,
                size=size,
                is_text=is_text,
                md5=md5,
                category=category,
                ext=ext,
            )
            files.append(fi)

    files.sort(key=lambda fi: (fi.root_label.lower(), str(fi.rel_path).lower()))
    return files


def build_tree(file_infos):
    """
    Erzeugt eine einfache Baumdarstellung pro Root.
    """
    by_root = {}
    for fi in file_infos:
        by_root.setdefault(fi.root_label, []).append(fi.rel_path)

    lines = ["```"]
    for root in sorted(by_root.keys()):
        rels = by_root[root]
        lines.append(u"📁 {0}/".format(root))

        tree = {}
        for r in rels:
            parts = list(r.parts)
            node = tree
            for p in parts:
                if p not in node:
                    node[p] = {}
                node = node[p]

        def walk(node, indent):
            dirs = []
            files = []
            for k, v in node.items():
                if v:
                    dirs.append(k)
                else:
                    files.append(k)
            for d in sorted(dirs):
                lines.append(u"{0}📁 {1}/".format(indent, d))
                walk(node[d], indent + "    ")
            for f in sorted(files):
                lines.append(u"{0}📄 {1}".format(indent, f))

        walk(tree, "    ")

    lines.append("```")
    return "\n".join(lines)


def make_output_filename(sources, now):
    """
    Dateiname: <repo1>-<repo2>-..._<ddmm>.md
    """
    names = sorted(set([src.name for src in sources]))
    joined = "-".join(names)
    joined = joined.replace(" ", "-")
    if len(joined) > 60:
        joined = joined[:60]
    date_str = now.strftime("%d%m")
    return "{0}_{1}.md".format(joined, date_str)


# --- Report-Erzeugung --------------------------------------------------------

def write_report(files, level, max_file_bytes, output_path, sources,
                 encoding="utf-8", plan_only=False):
    """
    Schreibt den Merge-Report.
    """
    now = datetime.datetime.now()

    total_size = sum(fi.size for fi in files)
    text_files = [fi for fi in files if fi.is_text]
    binary_files = [fi for fi in files if not fi.is_text]

    if level == "overview":
        planned_with_content = 0
    elif level == "summary":
        planned_with_content = sum(1 for fi in text_files if fi.size <= max_file_bytes)
    else:  # full
        planned_with_content = len(text_files)

    ext_counts, ext_sizes = summarize_extensions(files)
    cat_stats = summarize_categories(files)

    with output_path.open("w", encoding=encoding) as f_out:
        def wl(line=""):
            f_out.write(str(line) + "\n")

        # Header & Hinweise
        wl("# Gewebe-Merge")
        wl("")
        wl("**Zeitpunkt:** {0}".format(now.strftime("%Y-%m-%d %H:%M:%S")))
        if sources:
            wl("**Quellen:**")
            for src in sources:
                wl("- `{0}`".format(src))
        wl("**Detailstufe:** `{0}`".format(level))
        wl("**Maximale Inhaltsgröße pro Datei:** {0}".format(human_size(max_file_bytes)))
        wl("")
        wl("> Hinweis für KIs:")
        wl("> - Dies ist ein Schnappschuss des Dateisystems, keine vollständige Git-Historie.")
        wl("> - Baumansicht: `## 📁 Struktur`.")
        wl("> - Manifest: `## 🧾 Manifest`.")
        if level == "overview":
            wl("> - In dieser Detailstufe werden keine Dateiinhalte eingebettet.")
        elif level == "summary":
            wl("> - In dieser Detailstufe werden Inhalte kleiner Textdateien eingebettet;")
            wl(">   größere Textdateien erscheinen nur im Manifest.")
        else:
            wl("> - In dieser Detailstufe werden Inhalte aller Textdateien eingebettet;")
            wl(">   große Dateien werden nach einer einstellbaren Byte-Grenze gekürzt.")
        wl("> - `.env`-ähnliche Dateien werden gefiltert; sensible Daten können trotzdem in")
        wl(">   anderen Textdateien vorkommen. Nutze den Merge nicht als öffentlichen Dump.")
        wl("")

        # Plan
        wl("## 🧮 Plan")
        wl("")
        wl("- Gefundene Dateien gesamt: **{0}**".format(len(files)))
        wl("- Davon Textdateien: **{0}**".format(len(text_files)))
        wl("- Davon Binärdateien: **{0}**".format(len(binary_files)))
        wl("- Geplante Dateien mit Inhalteinbettung: **{0}**".format(planned_with_content))
        wl("- Gesamtgröße der Quellen: **{0}**".format(human_size(total_size)))
        if any(fi.size > max_file_bytes for fi in text_files):
            wl(
                "- Hinweis: Textdateien größer als {0} werden abhängig von der Detailstufe "
                "gekürzt oder nur im Manifest aufgeführt.".format(human_size(max_file_bytes))
            )
        wl("")

        if cat_stats:
            wl("**Dateien nach Kategorien:**")
            wl("")
            wl("| Kategorie | Dateien | Gesamtgröße |")
            wl("| --- | ---: | ---: |")
            for cat in sorted(cat_stats.keys()):
                cnt, sz = cat_stats[cat]
                wl("| `{0}` | {1} | {2} |".format(cat, cnt, human_size(sz)))
            wl("")

        if ext_counts:
            wl("**Grobe Statistik nach Dateiendungen:**")
            wl("")
            wl("| Ext | Dateien | Gesamtgröße |")
            wl("| --- | ---: | ---: |")
            for ext in sorted(ext_counts.keys()):
                wl("| `{0}` | {1} | {2} |".format(
                    ext, ext_counts[ext], human_size(ext_sizes[ext])
                ))
            wl("")

        wl(
            "Da der repomerger häufig nacheinander unterschiedliche Repos verarbeitet, "
            "werden keine Diffs zu früheren Läufen berechnet. "
            "Jeder Merge ist ein eigenständiger Schnappschuss."
        )
        wl("")

        if plan_only:
            return

        # Struktur
        wl("## 📁 Struktur")
        wl("")
        wl(build_tree(files))
        wl("")

        # Manifest
        wl("## 🧾 Manifest")
        wl("")
        wl("| Root | Pfad | Kategorie | Text | Größe | MD5 |")
        wl("| --- | --- | --- | --- | ---: | --- |")
        for fi in files:
            wl(
                "| `{0}` | `{1}` | `{2}` | {3} | {4} | `{5}` |".format(
                    fi.root_label,
                    fi.rel_path,
                    fi.category,
                    "ja" if fi.is_text else "nein",
                    human_size(fi.size),
                    fi.md5,
                )
            )
        wl("")

        # Inhalte
        if level != "overview":
            wl("## 📄 Dateiinhalte")
            wl("")
            for fi in files:
                if not fi.is_text:
                    continue

                if level == "summary" and fi.size > max_file_bytes:
                    continue

                wl("### `{0}/{1}`".format(fi.root_label, fi.rel_path))
                wl("")
                if fi.size > max_file_bytes and level == "full":
                    wl(
                        "**Hinweis:** Datei ist größer als {0} – es wird nur ein Ausschnitt "
                        "bis zu dieser Grenze gezeigt.".format(human_size(max_file_bytes))
                    )
                    wl("")

                fence_opened = False
                try:
                    # Sprache defensiv ermitteln
                    try:
                        lang = lang_for(fi.ext)
                    except Exception:
                        lang = ""

                    with fi.abs_path.open("r", encoding=encoding, errors="replace") as f_in:
                        wl("```{0}".format(lang))
                        fence_opened = True
                        remaining = max_file_bytes if (level == "full" and fi.size > max_file_bytes) else None
                        last_chunk = ""
                        finished_by_truncation = False

                        if remaining is not None:
                            # Truncated mode
                            for line in f_in:
                                encoded = line.encode(encoding, errors="replace")
                                if remaining <= 0:
                                    finished_by_truncation = True
                                    break
                                if len(encoded) > remaining:
                                    part = encoded[:remaining].decode(encoding, errors="replace")
                                    f_out.write(last_chunk)
                                    last_chunk = part
                                    remaining = 0
                                    finished_by_truncation = True
                                    break
                                f_out.write(last_chunk)
                                last_chunk = line
                                remaining -= len(encoded)
                        else:
                            # Normal mode
                            while True:
                                chunk = f_in.read(65536)
                                if not chunk:
                                    break
                                f_out.write(last_chunk)
                                last_chunk = chunk

                        if finished_by_truncation:
                            f_out.write(last_chunk.rstrip("\n"))
                            f_out.write("\n[... gekürzt ...]")
                        else:
                            f_out.write(last_chunk.rstrip("\n"))

                        f_out.write("\n```\n\n")
                        fence_opened = False

                except OSError as e:
                    if fence_opened:
                        wl("```")
                        wl("")
                    wl("_Fehler beim Lesen der Datei: {0}_".format(e))
                    wl("")
                    continue


# --- CLI / Source-Erkennung / Delete-Logik ----------------------------------

def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Erzeuge einen Gewebe-Merge-Bericht für ein oder mehrere Repos."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help=(
            "Quellverzeichnisse (Repos). "
            "Wenn leer, werden alle Unterordner im Script-Ordner verwendet, "
            "die nicht mit '.' oder '_' beginnen."
        ),
    )
    parser.add_argument(
        "--level",
        choices=["overview", "summary", "full", "medium", "max"],
        help=(
            "Detailstufe: overview=Struktur+Manifest, summary=mit kleinen Inhalten, "
            "full=maximal. medium≈summary, max≈full."
        ),
    )
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=10_000_000,
        help="Maximale Bytes pro Datei für Inhalteinbettung (Standard: 10 MiB).",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="Encoding für Textdateien (Standard: utf-8).",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Nur den Plan-Teil des Berichts erzeugen (kein Manifest, keine Inhalte).",
    )
    parser.add_argument(
        "--no-delete",
        action="store_true",
        help="Quellordner nach dem Merge NICHT löschen.",
    )
    return parser.parse_args(argv)


def resolve_level(raw_level):
    """
    Übersetzt CLI/ENV-Level in eines der drei Kern-Level.
    Default = full.
    """
    if raw_level is None:
        return "full"
    raw = str(raw_level).lower()
    if raw == "overview":
        return "overview"
    if raw in ("summary", "medium"):
        return "summary"
    if raw in ("full", "max"):
        return "full"
    return "full"


def discover_sources(base_dir, paths):
    """
    Ermittelt die zu scannenden Repos.
    - Wenn paths angegeben: nutzt genau diese (falls Verzeichnisse).
    - Sonst: alle Unterordner im Script-Ordner, außer '.', '_', MERGES_DIR_NAME, SKIP_ROOTS.
    """
    if paths:
        sources = []
        for p in paths:
            path = Path(p).expanduser().resolve()
            if path.is_dir():
                sources.append(path)
            else:
                print("Warnung: Pfad ist kein Verzeichnis und wird ignoriert: {0}".format(p))
        return sources

    sources = []
    for child in sorted(base_dir.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name.startswith("_"):
            continue
        if child.name in SKIP_ROOTS:
            continue
        sources.append(child.resolve())
    return sources


def safe_delete_source(src, base_dir, merges_dir, no_delete):
    """
    Löscht eine Quelle nur, wenn:
    - sie im gleichen Ordner wie das Script liegt (parent == base_dir) UND
    - sie nicht der merges-Ordner ist.
    """
    if no_delete:
        print("Löschen deaktiviert (--no-delete): {0}".format(src))
        return

    try:
        src = src.resolve()
        base_dir = base_dir.resolve()
        merges_dir = merges_dir.resolve()
    except Exception as e:
        print("Warnung: Fehler beim Auflösen von Pfaden: {0}".format(e), file=sys.stderr)
        return

    parent = src.parent
    if parent != base_dir:
        print("Quelle wird nicht gelöscht (liegt nicht im Script-Ordner): {0}".format(src))
        return
    if src == merges_dir:
        print("Merges-Ordner wird nicht gelöscht: {0}".format(src))
        return

    try:
        shutil.rmtree(str(src))
        print("Quelle gelöscht: {0}".format(src))
    except Exception as e:
        print("Fehler beim Löschen von {0}: {1}".format(src, e))


def main(argv=None):
    import sys
    import traceback

    if argv is None:
        argv = sys.argv[1:]

    try:
        script_path = Path(__file__).resolve()
        base_dir = script_path.parent
        merges_dir = base_dir / MERGES_DIR_NAME
        merges_dir.mkdir(parents=True, exist_ok=True)

        args = parse_args(argv)

        sources = discover_sources(base_dir, args.paths)
        if not sources:
            print("Keine gültigen Quellverzeichnisse gefunden.", file=sys.stderr)
            return 1

        env_level = os.environ.get("REPOMERGER_LEVEL")
        raw_level = args.level or env_level
        level = resolve_level(raw_level)

        now = datetime.datetime.now()
        filename = make_output_filename(sources, now)
        output_path = merges_dir / filename

        md5_limit = args.max_file_bytes

        all_files = []
        for src in sources:
            print("Scanne Quelle: {0}".format(src))
            repo_files = scan_repo(src, md5_limit_bytes=md5_limit)
            print("  -> {0} Dateien gefunden.".format(len(repo_files)))
            all_files.extend(repo_files)

        if not all_files:
            print("Keine Dateien in den Quellen gefunden.", file=sys.stderr)
            return 1

        print("Erzeuge Merge-Bericht mit {0} Dateien: {1}".format(len(all_files), output_path))
        write_report(
            files=all_files,
            level=level,
            max_file_bytes=args.max_file_bytes,
            output_path=output_path,
            sources=sources,
            encoding=args.encoding,
            plan_only=args.plan_only,
        )
        print("Fertig.")

        # Quellordner löschen (falls im gleichen Ordner wie das Script)
        for src in sources:
            safe_delete_source(src, base_dir, merges_dir, args.no_delete)

        if args.plan_only:
            print("Hinweis: Es wurde nur der Plan-Teil erzeugt (--plan-only).")
        return 0

    except Exception as e:
        print("repomerger: Unbehandelter Fehler:", file=sys.stderr)
        print(str(e), file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
