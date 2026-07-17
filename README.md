# repoground – Index

Kurzüberblick über Ordner:
- `scripts/` – wiederverwendbare Helfer
- `merger/repoground/` – **RepoGround** (Primary Tool) – erzeugt strukturierte Merge-Berichte für KIs.
- `merger/repomerger/` – Legacy-Merger (Standalone).

## Einstieg & Dokumentation

- 🚀 [Getting Started](docs/GETTING_STARTED.md) – Dump erzeugen, Bundle lesen, durchsuchen
- 📖 [Glossar](docs/glossary.md) · [FAQ](docs/FAQ.md)
- 🗺️ [Systemkarte](docs/architecture/system-map.repoground.md) – Modul-Zusammenspiel
- 🧭 [Master-Roadmap](docs/roadmap/repoground-master-roadmap.md) – Reihenfolge & Tracks
- 🤝 [CONTRIBUTING](CONTRIBUTING.md) · [CHANGELOG](CHANGELOG.md)

## Nutzung (Beispiele)

### RepoGround (Empfohlen)

Das Hauptwerkzeug, um Repositories für LLMs aufzubereiten.
`merger.repoground.frontends.pythonista.build` ist der direkte RepoGround Dump-/Bundle-Emitter für lokale Modulaufrufe, insbesondere aus Pythonista/iPad-Kontexten.
`merger.repoground.cli.serve` ist die RepoGround-Service-/Host-Surface und nicht der direkte `RepoGround . --level ...`-Aufruf; RepoGround bleibt die operative Heim-PC/Service-Schicht.

```bash
# Overview
python3 -m merger.repoground.frontends.pythonista.build . --level overview

# Full Merge mit Split (20MB), voller Metadichte und Dual-Output
python3 -m merger.repoground.frontends.pythonista.build . \
  --level max \
  --split-size 20MB \
  --meta-density full \
  --output-mode dual
```

Direkte Datei-Ausführung ist ebenfalls möglich, falls der Modulaufruf in einer lokalen Umgebung nicht greift:

```bash
python3 merger/repoground/frontends/pythonista/build.py . --level max --split-size 20MB --meta-density full --output-mode dual
```

Siehe [merger/repoground/repoground-build-spec.md](merger/repoground/repoground-build-spec.md) für Details.

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
python3 -m merger.repoground.cli.main agent-pack produce <stem>.bundle.manifest.json --json
```

### RepoGround als lokaler MCP-Server

Vorhandene Brief Bundles können direkt als MCP-Ressourcen und Werkzeuge für Coding-Agenten
eingehängt werden. Für MCP-Clients ist der checkout-unabhängige Starter vorgesehen:

```bash
python3 /absoluter/pfad/zu/repoground/scripts/repoground-mcp-stdio.py \
  --bundle-root /absoluter/pfad/zu/briefs \
  --repo-root /absoluter/pfad/zum/repository
```

Der Server stellt standardmäßig `ask_context`, `grounding_verify`, `live_freshness` und die
`repoground://snapshot/...`-Ressourcen bereit. Lesezugriffe erzeugen oder aktualisieren keinen
Snapshot. Live-Freshness meldet abweichendes `HEAD` oder einen Dirty Working Tree als `stale`.
Der schreibende `snapshot_create`-Pfad bleibt verborgen, solange der Server nicht ausdrücklich
mit `--enable-snapshot-create` gestartet wird. In diesem Modus sind Quellrepository und Ausgabeziel
weiterhin an `--repo-root` und `--bundle-root` des Serverstarts gebunden.

Konfiguration, Zustände und Sicherheitsgrenzen:
[RepoGround MCP stdio](docs/usage/repoground-mcp-stdio.md).

### ATLAS MODE

Atlas is a filesystem exploration tool capable of scanning entire systems, distinct from the repository inspection pipeline.

Pseudo-filesystems and volatile paths (`/proc`, `/sys`, `/dev`, `/run`, etc.) are excluded by default to avoid recursion loops, device streams, and meaningless inventory entries. The merge pipeline remains completely unchanged by this feature.

**Atlas Root Model:**
Atlas employs a formalized root model internally, permitting execution against different types of targets without implicitly falling back or hiding behaviors. The `root_kind` in API requests must be one of:
* `preset`: Used to refer to predefined, trusted directories like `hub`, `merges`, or `system` (the service user's home directory). The `system` preset requires loopback, configured Bearer authentication, and a Home path resolved successfully during startup. If Home is unavailable, the service starts in authenticated root-only mode, omits `system` from `/api/fs/roots`, and keeps explicit filesystem-root access available.
* `token`: Used with an opaque, server-signed token, primarily meant for file pickers and external integrations.
* `abs_path`: Explicitly targets an absolute file system path (e.g., `/home/user/project`). This is an explicit internal mode. Traversal exploits (`..`) or relative paths are strictly rejected. Note that the WebUI catches invalid manual path inputs (like "home" instead of "/home") before creating an API request, preventing unnecessary Bad Requests.

Example usage:

```bash
# Service API: broad system roots require loopback plus --token / RLENS_TOKEN.
# The standalone Atlas CLI remains a local, explicit filesystem operation.
repoground atlas scan /
repoground atlas scan /home
repoground atlas scan /etc
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
