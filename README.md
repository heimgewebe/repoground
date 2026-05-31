# lenskit – Index

Kurzüberblick über Ordner:
- `scripts/` – wiederverwendbare Helfer
- `merger/lenskit/` – **repoLens** (Primary Tool) – erzeugt strukturierte Merge-Berichte für KIs.
- `merger/repomerger/` – Legacy-Merger (Standalone).

## Einstieg & Dokumentation

- 🚀 [Getting Started](docs/GETTING_STARTED.md) – Dump erzeugen, Bundle lesen, durchsuchen
- 📖 [Glossar](docs/glossary.md) · [FAQ](docs/FAQ.md)
- 🗺️ [Systemkarte](docs/architecture/system-map.lenskit.md) – Modul-Zusammenspiel
- 🧭 [Master-Roadmap](docs/roadmap/lenskit-master-roadmap.md) – Reihenfolge & Tracks
- 🤝 [CONTRIBUTING](CONTRIBUTING.md) · [CHANGELOG](CHANGELOG.md)

## Nutzung (Beispiele)

### repoLens (Empfohlen)

Das Hauptwerkzeug, um Repositories für LLMs aufzubereiten.
`merger.lenskit.frontends.pythonista.repolens` ist der direkte repoLens Dump-/Bundle-Emitter für lokale Modulaufrufe, insbesondere aus Pythonista/iPad-Kontexten.
`merger.lenskit.cli.rlens` ist die rLens-Service-/Host-Surface und nicht der direkte `repoLens . --level ...`-Aufruf; rLens bleibt die operative Heim-PC/Service-Schicht.

```bash
# Overview
python3 -m merger.lenskit.frontends.pythonista.repolens . --level overview

# Full Merge mit Split (20MB), voller Metadichte und Dual-Output
python3 -m merger.lenskit.frontends.pythonista.repolens . \
  --level max \
  --split-size 20MB \
  --meta-density full \
  --output-mode dual
```

Direkte Datei-Ausführung ist ebenfalls möglich, falls der Modulaufruf in einer lokalen Umgebung nicht greift:

```bash
python3 merger/lenskit/frontends/pythonista/repolens.py . --level max --split-size 20MB --meta-density full --output-mode dual
```

Siehe [merger/lenskit/repoLens-spec.md](merger/lenskit/repoLens-spec.md) für Details.

### Agent Reading Pack (Einstieg für LLM-Agents)

Jedes Bundle enthält `<stem>.agent_reading_pack.md` — ein kompaktes, deterministisches
Markdown-Dokument, das ein LLM-Agent **zuerst** lesen sollte. Es ist
**Navigation, nicht Wahrheit** (`authority=navigation_index`, `canonicality=derived`);
die einzige Wahrheitsquelle bleibt `canonical_md`.

Der Pack fasst zusammen:
- **Reading Policy** + Artefaktrollen (welches Artefakt was aussagen darf),
- **HOW_TO_SEARCH**: konkrete CLI-Befehle für Volltextsuche, Range-Auflösung und Citations,
- **OUTPUT_HEALTH_SUMMARY**: Selbsttest-Verdict des Bundles,
- **TOP_CHUNK_SPANS**: die nach Chunk-Coverage größten aggregierten canonical Spans je
  Quelldatei (Navigationshilfe für präzises Zitieren in `canonical_md`) — **keine**
  Wichtigkeitsaussage. (Früher: `TOP_FILES`.)
- **EPISTEMIC_EMPTINESS**: was im Bundle fehlt.

Standalone erzeugen oder regenerieren:

```bash
python3 -m merger.lenskit.cli.main agent-pack produce <stem>.bundle.manifest.json --json
```

### ATLAS MODE

Atlas is a filesystem exploration tool capable of scanning entire systems, distinct from the repository inspection pipeline.

Pseudo-filesystems and volatile paths (`/proc`, `/sys`, `/dev`, `/run`, etc.) are excluded by default to avoid recursion loops, device streams, and meaningless inventory entries. The merge pipeline remains completely unchanged by this feature.

**Atlas Root Model:**
Atlas employs a formalized root model internally, permitting execution against different types of targets without implicitly falling back or hiding behaviors. The `root_kind` in API requests must be one of:
* `preset`: Used to refer to predefined, trusted directories like `hub`, `merges`, or `system` (user home).
* `token`: Used with an opaque, server-signed token, primarily meant for file pickers and external integrations.
* `abs_path`: Explicitly targets an absolute file system path (e.g., `/home/user/project`). This is an explicit internal mode. Traversal exploits (`..`) or relative paths are strictly rejected. Note that the WebUI catches invalid manual path inputs (like "home" instead of "/home") before creating an API request, preventing unnecessary Bad Requests.

Example usage:

```bash
# Explore arbitrary filesystem roots via CLI (when integrated) or API
rlens atlas scan /
rlens atlas scan /home
rlens atlas scan /etc
```

### JSONL Tools

Minimale Befehle, um die verfügbaren Werkzeuge aufzurufen:

```bash
bash scripts/jsonl-validate.sh --help
bash scripts/jsonl-tail.sh --help
```

- `scripts/jsonl-validate.sh` – prüft NDJSON (eine JSON-Entität pro Zeile) gegen ein JSON-Schema (AJV v5).
- `scripts/jsonl-tail.sh`
- `scripts/jsonl-compact.sh`

## Organismus-Kontext

Dieses Repository ist Teil des **Heimgewebe-Organismus**.

Rolle dieses Repos im Organismus: **Merger**, **Scanner** und epistemischer Kern
für strukturierte Repository-Aufbereitung.

Die übergeordnete Architektur, Achsen, Rollen und Contracts sind zentral beschrieben im  
👉 [`metarepo/docs/heimgewebe-organismus.md`](https://github.com/heimgewebe/metarepo/blob/main/docs/heimgewebe-organismus.md)  
👉 [`metarepo/docs/heimgewebe-zielbild.md`](https://github.com/heimgewebe/metarepo/blob/main/docs/heimgewebe-zielbild.md).

Alle Rollen-Definitionen, Datenflüsse und Contract-Zuordnungen dieses Repos
sind dort verankert.

### Merge Job Deduplizierung

Wenn ein non-plan Repository-Merge über die WebUI angefordert wird, enthält der JSON-Payload `force_new: true`. Dies stellt sicher, dass ein frischer Merge ausgeführt wird, anstatt einen gecachten Job wiederzuverwenden. Plan-only Jobs lassen das `force_new` Flag weg, damit gecachte Planungsergebnisse wenn möglich wiederverwendet werden können.
