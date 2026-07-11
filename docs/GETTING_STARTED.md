# Getting Started mit Lenskit

> Aktualisiert am 2026-05-31.
> Einstieg in fünf Minuten: Repository aufbereiten, Ergebnis lesen, durchsuchen.
> Für die normative Spezifikation siehe
> [`merger/lenskit/repoLens-spec.md`](../merger/lenskit/repoLens-spec.md),
> für die Architektur die
> [Systemkarte](architecture/system-map.lenskit.md), für Begriffe das
> [Glossar](glossary.md).

## 1. Was ist Lenskit?

Lenskit ist **Merger** und **Scanner** im Heimgewebe-Organismus. Es überführt
Arbeitskopien von Repositories in strukturierte, für LLMs navigierbare und
**zitierbare** Hyper-Merge-Berichte (Bundles). Es gibt zwei funktionsgleiche
Frontends:

- **repoLens** — die Pythonista/iPad- und CLI-Oberfläche
  (`merger/lenskit/frontends/pythonista/repolens.py`).
- **rLens** — die Web-UI/Service-Schicht für Heim-PC/Server
  (`merger/lenskit/cli/rlens.py`, `merger/lenskit/service/app.py`).

Die **Wahrheitsquelle** ist immer der kanonische Markdown-Dump (`canonical_md`).
Alle anderen Artefakte (Index, Citation-Map, Agent Reading Pack, Health) sind
**Navigation/Diagnose, nicht Wahrheit**.

## 2. Voraussetzungen

- Python 3.12 ist die CI- und Release-Kandidaten-Basis; lokale Aufrufe erfolgen
  über `python3` (ältere 3.x-Versionen können funktionieren, gehören aber nicht
  zum reproduzierbaren Lockvertrag)
- Kern-Pipeline läuft ohne Drittpakete. Für Validierung/Service/Tests:

```bash
python3 -m pip install --require-hashes -r requirements/repobrief-dev.lock.txt
# optional und noch nicht Teil des Release-Lockvertrags:
# merger/lenskit/requirements-semantic.txt
```

## 3. Minimalbeispiel: einen Dump erzeugen

Aus dem Repo-Wurzelverzeichnis, das aktuelle Verzeichnis (`.`) aufbereiten:

```bash
# Schneller Überblick
python3 -m merger.lenskit.frontends.pythonista.repolens . --level overview

# Voller Merge mit Split (20MB), voller Metadichte, Dual-Output (MD + Index)
python3 -m merger.lenskit.frontends.pythonista.repolens . \
  --level max \
  --split-size 20MB \
  --meta-density full \
  --output-mode dual
```

Wichtige Flags (vollständig via `--help`):

| Flag | Werte | Bedeutung |
| --- | --- | --- |
| `--level` | `overview`, `summary`, `dev`, `max` | Detailtiefe / Profil |
| `--mode` | `gesamt`, `pro-repo` | Single- vs. Multi-Repo-Merge |
| `--output-mode` | `archive`, `retrieval`, `dual` | nur MD / nur Index / beides |
| `--meta-density` | `min`, `standard`, `full`, `auto` | Metadaten-Drosselung (Default `auto`) |
| `--split-size` | z. B. `20MB`, `1GB` | Ausgabe in Teile splitten |
| `--path-filter` | Substring, z. B. `docs/` | nur passende Pfade |
| `--extensions` | z. B. `.md,.py` | nur diese Endungen |
| `--code-only` / `--plan-only` | – | nur Code / nur Plan |
| `--json-sidecar` | – | maschinenlesbarer JSON-Zwilling |
| `--redact-secrets` | – | heuristische Secret-Redaktion |

> `--meta-density auto` wählt automatisch: `full` bei vollständigem Dump,
> `standard` sobald ein Pfad-/Endungsfilter aktiv ist.

## 4. Was kommt heraus? (Bundle lesen)

Ein Merge erzeugt ein Bundle mit invarianter Sektionsreihenfolge (Spec v2.4):
*Source & Profile → Profile Description → Reading Plan → Plan → Structure →
Manifest → Content*. Die wichtigsten Dateien:

| Datei (Rolle) | Wofür | Authority |
| --- | --- | --- |
| `*.merge.md` (`canonical_md`) | **Die Wahrheitsquelle.** Vollständiger Dump zum Zitieren. | `canonical_content` |
| `*.bundle.manifest.json` | Registry aller Bundle-Artefakte (Rollen, Pfade, Hashes). | – |
| `*.agent_reading_pack.md` | **Hier zuerst lesen** (LLM-Agent). Lese-Policy, Artefaktrollen, Suchanleitung, Health-Verdict, Top-Chunk-Spans. | `navigation_index` |
| `*.chunk_index.jsonl` | Chunk-Spannen für FTS/Range-Auflösung. | `retrieval_index` |
| `*.citation_map.jsonl` | Quell-Byte-Bereich → stabile Citation-ID. | `navigation_index` |
| `*.output_health.json` | Maschinenlesbarer Selbsttest (FTS leer? Range-Ref ok? Hash ok?). | `diagnostic_signal` |

Reihenfolge für LLM-Agents: **agent_reading_pack.md → manifest → canonical_md**.
Zitiert wird ausschließlich gegen `canonical_md`.

## 5. Durchsuchen & zitieren (`lenskit` CLI)

```bash
# 1) Index bauen (SQLite FTS5)
python3 -m merger.lenskit.cli.main index \
  --dump <dump_index.json> --chunk-index <chunk_index.jsonl> --out index.sqlite

# 2) Volltextsuche
python3 -m merger.lenskit.cli.main query --index index.sqlite --q "range resolver" --k 10

# 3) Deterministischen Byte-Bereich auflösen (verifiziert Hash)
python3 -m merger.lenskit.cli.main range get --manifest <bundle.manifest.json> --ref ref.json

# 4) Citation-Map erzeugen / Bundle-Health prüfen
python3 -m merger.lenskit.cli.main citation produce <bundle.manifest.json> --json
python3 -m merger.lenskit.cli.main bundle-health post <bundle.manifest.json>

# 5) Agent Reading Pack regenerieren
python3 -m merger.lenskit.cli.main agent-pack produce <bundle.manifest.json> --json
```

Weitere Subkommandos: `eval`, `architecture`, `atlas`, `federation`,
`context-quality`, `governance`, `parity`, `artifact`, `rlens-client`, `verify`,
`pr-explain`. Jeweils `--help` für Details.

Federierte Query ohne persistierten Index:

```bash
lenskit federation query --bundle repo_a=/path/to/bundle-a --bundle repo_b=/path/to/bundle-b -q "symbol" --trace
```

## 6. Fehlerbehebung (Kurz)

- **„range_ref failed schema" / Hash mismatch:** Der `range_ref` passt nicht
  zum Artefakt-Inhalt — Bundle veraltet oder Ref von Hand editiert. Bundle neu
  erzeugen; Felder nicht manuell ändern. Mehr im [FAQ](FAQ.md).
- **FTS-Index leer:** Repo enthält keinen indexierbaren Text, oder
  `--output-mode archive` (kein Index). Mit `dual`/`retrieval` neu bauen.
- **„No module named pytest" o. Ä.:** Dev-Abhängigkeiten installieren
  (Abschnitt 2).
- **Atlas verweigert Pfad:** `..`/relative Pfade sind verboten; absolute Pfade
  oder Presets nutzen (s. README, „ATLAS MODE").

## 7. Weiterlesen

- [Master-Roadmap](roadmap/lenskit-master-roadmap.md) — Reihenfolge & Tracks
- [Systemkarte](architecture/system-map.lenskit.md) — Modul-Zusammenspiel
- [Glossar](glossary.md) · [FAQ](FAQ.md) · [CONTRIBUTING](../CONTRIBUTING.md)
- [Service-API](service-api.md) · [Parity-Guard](PARITY_GUARD.md)
