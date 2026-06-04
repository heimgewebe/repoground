# Atlas-Blaupause

## These
Atlas soll kein Repo-Spezialscanner mit etwas Dateisystemdeko werden, sondern ein maschinenweiter Dateiatlas mit Zeitgedächtnis: PC, Heimserver, externe Platten, Backups, später auch weitere Hosts.

## Antithese
Wenn Atlas zu viel auf einmal tut, droht der klassische Werkzeugtod: ein Scanner, der alles können soll und deshalb vor allem langsam, teuer und epistemisch verwirrt wird. Der Dateibaum wird dann zum Opfer seiner eigenen Ambitionen – eine Art digitaler Messie mit Index.

## Synthese
Die tragfähige Lösung ist:
**Atlas = physische Wahrnehmungsschicht + Snapshot-Gedächtnis + optionale Inhaltserschließung**

Darauf setzen Retrieval, Analyse, Visualisierung und Agentenlogik auf. Lenskit bleibt die Denkmaschine; Atlas bleibt das Beobachtungsorgan. Das passt auch zum aktuellen Repo-Stand: Atlas ist im README ausdrücklich als vom Repository-Inspektionspfad getrennte Dateisystem-Erkundung beschrieben, inklusive Root-Modell für `preset`, `token` und `abs_path`.

---

## Status dieses Dokuments
* **Dies ist eine Blaupause / Zielarchitektur / Ausbau-Roadmap.**
* Sie beschreibt den **Soll-Zustand**, die Architekturentscheidungen und die priorisierten Ausbaupfade.
* Einzelne Passagen referenzieren den aktuellen Repo-Stand, aber **die meisten beschriebenen Bausteine sind ausdrücklich noch nicht vollständig implementiert**.
* Die Umsetzung erfolgt schrittweise in Folgearbeiten.

---

# Teil 1/4: Mandat, Zielbild, Invarianten, Bounded Context

Dieses Fundament sichert ab, dass spätere Features stabil aufgebaut werden können.


---

## 0. STATUS-SEMANTIK & DIMENSIONEN

Um die "epistemische Leerstelle" zwischen funktionaler Existenz und architektonischer Reife explizit zu machen, gilt folgende strikte Statussemantik in der Blaupause:

* **`[ ]` (Offen)**: Das Feature ist konzeptionell, aber nicht oder nur rudimentär belegbar implementiert.
* **`[x]` (Abgeschlossen)**: Das Feature ist vollständig implementiert, getestet und **vollständig gehärtet** (Edge-Cases, Reproduzierbarkeit und Systemintegration gelten als belastbar belegt).
* **`[~]` (Substanziell begonnen)**: Das Feature existiert funktional, aber es fehlt mindestens eine Dimension (meistens die Härtung). Um eine Überladung dieses Symbols zu verhindern, wird das `[~]` für fortgeschrittene Features ab Phase 5 standardmäßig durch drei orthogonale Dimensionen aufgeschlüsselt:
  * `- implementation:` [done | partial | none] (Ist der Code logisch vorhanden und in die Pipeline integriert?)
  * `- tests:` [present | partial | missing] (Ist die Logik durch dedizierte Unit-/Integrationstests abgesichert?)
  * `- hardening:` [complete | partial | missing] (Sind Edge-Cases, Stabilität und Policies nachweislich robust?)
  *(Hinweis: Frühere Phasen nutzen weiterhin das einfache `[~]` und müssen nicht rückwirkend in dieses Format überführt werden.)*

---

## 1. Ausgangslage: Was Atlas laut aktuellem Repo bereits ist
Der aktuelle Stand im Repo zeigt: Atlas ist bereits als Filesystem Exploration Tool angelegt, also gerade nicht primär als Repo-Scanner. Das README trennt Atlas explizit von der Repository-Aufbereitung und nennt das Scannen ganzer Systeme als Ziel. Gleichzeitig werden volatile/pseudo-Dateisysteme standardmäßig ausgeschlossen.

Im aktuellen Stand existieren außerdem bereits:
* ein formales Root-Modell (`preset`, `token`, `abs_path`) statt stiller Fallbacks, inklusive strikter Ablehnung relativer/manipulativer Pfade auf API-Ebene; die WebUI fängt ungültige manuelle Eingaben bereits vor dem Request ab.
* eine Atlas-Planungsschicht `merger/lenskit/atlas/planner.py`, die Artefakte nach `scan_mode` plant:
  * `inventory` → summary + inventory + dirs
  * `topology` → summary + topology
  * `content` → summary + inventory + content
  * `workspace` → summary + workspaces + hotspots
* Testabdeckung für diese Modus-Artefakte in `test_atlas_planner.py`, inklusive `write_mode_outputs` für Topology-, Content-, Workspaces- und Hotspots-Artefakte.
* insgesamt ein stark testdominiertes Repo: 113 Testdateien bei 254 Textdateien laut Architektur-Snapshot.

Die Blaupause dockt an diese vorhandenen Achsen an.

## 2. Primärmandat von Atlas

### 2.1 Kernauftrag
Atlas soll die physische Realität deiner Maschinen explizit und historisierbar erfassen:
* Welche Dateien gibt es?
* Wo liegen sie?
* Wie groß sind sie?
* Was hat sich verändert?
* Was ist textuell/inhaltlich zugänglich?
* Welche Maschinen- und Root-Kontexte gehören dazu?

Atlas ist damit Dateisystem-Observatorium, nicht Repo-Kognition.

### 2.2 Sekundäraufträge
Sekundär darf Atlas:
* Repos und Workspaces erkennen
* Inhalte extrahieren
* Hotspots berechnen
* Topologien ableiten
* Deltas zwischen Snapshots berechnen
* Lenskit/Heimgeist/HausKI mit Rohwirklichkeit versorgen

Das sind Aufbauten, nicht das Mandat selbst.

### 2.3 Was Atlas ausdrücklich nicht sein soll
Atlas soll nicht primär sein:
* Git-Analyse-Engine
* Code-Intelligence-Monolith
* IDE-Ersatz
* monolithischer Agenten-Orchestrator
* bloßer Repo-Bundler mit Dateisystem-Nebenfunktion

Ein wenig Repo-/Workspace-Erkennung ist legitim, aber nur als Annotation auf einem globalen Dateiatlas. Sobald Repo-Strukturen die primäre Ontologie werden, ist Atlas konzeptionell bereits halb auf Abwegen. Der aktuelle Repo-Stand zeigt zwar Workspace-/Hotspot-/Topology-Artefakte, aber das README hält die Trennung zur Repo-Pipeline weiterhin klar fest. Das ist als Invariante zu konservieren.

## 3. Zielbild: Atlas als Maschinen-Gedächtnis

### 3.1 Kurzform
Atlas soll zum globalen Dateisystem-Gedächtnis deiner Infrastruktur werden.

Nicht nur: *„Was ist jetzt da?“*
Sondern:
* „Was war da?“
* „Was ist gewachsen?“
* „Was fehlt zwischen Maschine A und B?“
* „Welche Wissensräume existieren physisch?“
* „Welche Inhalte sind neu, alt, doppelt, vergessen, relevant?“

### 3.2 Die entscheidende Sinnachse
Es gibt zwei mögliche Zielachsen:
* **Achse A – Scanner-Logik**: Atlas scannt Dateibäume und liefert Inventare.
* **Achse B – Gedächtnis-Logik**: Atlas speichert Zustände, vergleicht Zeiten und macht Dateirealität historisch navigierbar.

Die Blaupause entscheidet sich klar für **Achse B**. Scanner ohne Gedächtnis sind austauschbar. Gedächtnisse nicht. Der Computer weiß sonst immer nur „jetzt“. Atlas soll „jetzt“, „vorher“ und „Veränderung“ zugleich wissen.

## 4. Die drei verbindlichen Architekturentscheidungen

### 4.1 Entscheidung A: Atlas ist zustandsbehaftet
Atlas ist kein bloßer Lauf, sondern erzeugt persistente Zustände: `scan_result`, `snapshot`, `delta`, später evtl. `history_view`.

Jeder Scan muss also mindestens in diese Denkform gebracht werden:
`scan -> snapshot -> optional compare/delta -> index/derive`

**Konsequenz**: Ohne Snapshot-IDs, Root-IDs und Machine-IDs wird Atlas später nicht wachsen, sondern nur größer werden.

### 4.2 Entscheidung B: Atlas ist dateizentriert
Der stabile Kern ist nicht „Bedeutung“, sondern: Pfad, Datei, Verzeichnis, Größe, Zeit, Eigentümer, Typ, Hash, Root, Maschine.
Inhalte, Semantik, Klassifikation sind optionale obere Schichten.

**Konsequenz**: `content` darf nie Pflichtkern der Erfassung werden. Sonst kippt Performance, Speicherverbrauch und Komplexität.

### 4.3 Entscheidung C: Atlas ist Pipeline, kein Monolith
Die richtige Form ist:
1. Discovery
2. Snapshot/Persistenz
3. Enrichment
4. Derivation
5. Indexing
6. Serving / Retrieval / Automation

Der aktuelle `scan_mode`-Ansatz geht bereits in diese Richtung, weil unterschiedliche Artefakte gezielt geplant und geschrieben werden. Diese Tendenz sollte ausgebaut werden.

## 5. Bounded Context: Wofür Atlas zuständig ist

### 5.1 Atlas ist zuständig für
* **A. Physische Dateirealität**: Dateibäume, Verzeichnisse, Root-Kontexte, Dateimetadaten, Größen- und Zeitrealität
* **B. Historisierung**: Snapshots, Deltas, Datei-Historien, Root-Historien, Maschinenvergleiche
* **C. Selektive Inhaltserschließung**: Textklassifikation, MIME/Encoding, line_count, Volltext-Extraktion, Chunking-Vorbereitung, minimale Medienmetadaten
* **D. Systemanalytik**: Top-Dirs, große Dateien, Duplikate, alte Dateien, orphaned Bereiche, Hotspots
* **E. Exportierte Artefakte**: inventory, dirs inventory, summary, topology, content, workspaces, hotspots, später snapshots/deltas/history/search-indizes

### 5.2 Atlas ist nicht zuständig für
* **A. Semantische Tiefeninterpretation**: Dafür sind Lenskit, Heimgeist, HausKI besser geeignet.
* **B. Politische oder organisatorische Systemlogik**: Nicht Atlas’ Aufgabe.
* **C. Vollständige Git-Historienanalyse**: Atlas darf Repos erkennen, aber nicht in seinem Kern von Git abhängen.
* **D. UI-zentrierte Wahrheitsdefinition**: Die WebUI ist Konsument, nicht Kanon.

## 6. Kerninvarianten

1. **Invariante 1 – Atlas ist maschinenweit**: Atlas darf nie stillschweigend auf „Repo = Welt“ reduziert werden.
2. **Invariante 2 – Roots sind explizit**: Kein stilles Fallback, keine implizite Magie. Das aktuelle Root-Modell wird beibehalten.
3. **Invariante 3 – Discovery bleibt vom Enrichment trennbar**: Ein schneller, grober Scan muss immer möglich sein.
4. **Invariante 4 – Snapshot vor Erklärung**: Erst Realität speichern, dann interpretieren.
5. **Invariante 5 – Repo-/Workspace-Erkennung ist Annotation**: Nicht Primärobjekt.
6. **Invariante 6 – Höhere Artefakte sind ableitbar**: Hotspots, Topology, Content, Workspaces dürfen keine isolierten Sonderwelten sein, sondern müssen aus Kernartefakten oder klaren Enrichment-Stufen hervorgehen.
7. **Invariante 7 – Atlas bleibt source-of-truth für physische Dateiwirklichkeit**: Nicht Git, nicht Index-UI, nicht Agentenlogik.

## 7. Ontologie von Atlas

### 7.1 Primäre Entitäten

* **Machine**: Eine physische oder virtuelle Maschine. Felder: `machine_id`, `hostname`, `kind`, `os_family`, `arch`, `observed_at`.
* **Root**: Ein expliziter Scan-Root. Felder: `root_id`, `machine_id`, `root_kind`, `root_value`, `filesystem`, `mountpoint`, `label`.
* **Snapshot**: Ein persistenter Zustand eines Roots zu einem Zeitpunkt. Felder: `snapshot_id`, `machine_id`, `root_id`, `created_at`, `scan_config_hash`, `inventory_ref`, `dirs_ref`, `stats_ref`, `content_ref?`, `topology_ref?`, `workspaces_ref?`, `hotspots_ref?`.
* **FileEntity**: Die über Zeit wiedererkennbare Datei-Entität. Felder: `entity_id`, `machine_id`, `root_id`, `canonical_rel_path`, `inode?`, `device?`, `stable_hash?`.
* **FileObservation**: Beobachtung einer Datei in einem Snapshot. Felder: `snapshot_id`, `rel_path`, `size`, `mtime`, `ctime?`, `owner`, `group`, `permissions`, `ext`, `mime`, `is_symlink`, `is_text?`, `encoding?`, `line_count?`, `checksum?`.
* **DirectoryObservation**: Beobachtung eines Verzeichnisses.
* **Delta**: Differenz zwischen zwei Snapshots. Felder: `from_snapshot_id`, `to_snapshot_id`, `new_files`, `removed_files`, `changed_files`, `renamed_files?`, `summary`.

### 7.2 Sekundäre Entitäten
* WorkspaceAnnotation
* HotspotReport
* TopologyProjection
* DuplicateSet
* SearchIndexArtifact
* KnowledgeClusterProjection

## 8. Schichtenmodell

* **Schicht A – Discovery Layer**: Erfasst Pfade, Dateitypen, Basisstats (`inventory.jsonl`, `dirs.jsonl`, `summary.md`).
* **Schicht B – Snapshot Layer**: Persistiert Zustände als identifizierbare Snapshots (`snapshot_meta.json`, Snapshot-Registry, Delta-Registry).
* **Schicht C – Enrichment Layer**: Zusatzwissen pro Datei/Verzeichnis (`content.json`, `media.json`, `workspace_annotations.json`).
* **Schicht D – Derivation Layer**: Abgeleitete Sichten (`topology.json`, `hotspots.json`, `duplicates.json`, `history_views.json`).
* **Schicht E – Index Layer**: Suchen, Filtern, Retrieval (`FTS`, `Chunk-Index`, `Semantik-Index`).
* **Schicht F – Integration Layer**: Exports für Lenskit, Heimgeist, HausKI, Chronik, UI.

## 9. Soll-Ist-Abgleich zum aktuellen Repo-Stand

* **Bereits vorhanden**: Root-Modell (`preset`, `token`, `abs_path`), Scan-Modi (`inventory`, `topology`, `content`, `workspace`), Artefakt-Planung per `planner.py`, Artefakt-Ausgabe für Topology/Content/Workspaces/Hotspots, Testpfad für Atlas-Modi und Planner-Ausgaben.
* **Teilweise vorhanden / im Übergang**: Workspace-/Hotspot-/Topology-Ableitungen im Scannerpfad, Content-Statistik selektiv nach `scan_mode=content`, Snapshot-/Delta-Denken ist konzeptionell angelegt, aber noch nicht als vollständiges Zeitmodell durchgezogen.
* **Fehlend / blaupausenreif**: Multi-Machine-Root-Registry, explizite Snapshot-Registry, konsistente File-Entity-Identität, Datei-Historie über viele Snapshots, Cross-machine diff, Duplicate Detection, Watch-Mode, inkrementelles Re-Scanning, Suchschicht mit Query-API, Trennung zwischen Root-Atlas und Repo-Annotation noch expliziter machen.

## 10. Entscheidungsmatrix & Essenz Teil 1

Atlas ist das historische, maschinenweite Gedächtnis der physischen Dateiwelt; Repo-/Workspace-Strukturen sind darin nur bedeutungsvolle Sonderformen, nicht die Leitontologie.
1. Atlas ist zustandsbehaftetes Maschinen-Gedächtnis.
2. Kern ist dateizentriert.
3. Enrichment ist optional.
4. Pipeline über Monolith.
5. Repos sind Annotation, nicht Weltmodell.

---

# Teil 2/4: Datenmodell, Artefaktformate, Snapshot-/Delta-Mechanik, Storage-Strategie

## 1. Architektur-Prinzipien für Teil 2
1. **Append-first statt mutate-first**: Beobachtungen werden bevorzugt als neue Zustände gespeichert.
2. **Artefaktzentrierung**: Alles Relevante existiert als explizites Artefakt (`inventory`, `dirs`, `snapshot meta`, `delta`, `topology`, `content`, `hotspots`, `workspaces`, index artifacts).
3. **Ableitbarkeit vor Sonderwissen**: Höhere Sichten sollen aus Kernartefakten ableitbar sein.
4. **Host-/Root-/Snapshot-Trennung**: Maschine, Root und Zeitpunkt dürfen nie ineinander verschwimmen.
5. **Kleine Wahrheit zuerst**: Rohinventar vor Semantik, Snapshot vor Analyse, Analyse vor UI.

## 2. Kanonisches Datenmodell

Ich trenne strikt zwischen Identitäten, Beobachtungen und abgeleiteten Projektionen.

### 2.1 Identitäten

#### 2.1.1 Machine
Repräsentiert eine konkrete Maschine.
```yaml
machine:
  machine_id: heim-pc
  hostname: heim-pc
  kind: workstation
  os_family: linux
  arch: x86_64
  labels:
    - primary
    - local
```
**Pflichtfelder**: `machine_id`, `hostname`
**optionale Felder**: `kind`, `os_family`, `arch`, `labels`, `last_seen_at`
**Bemerkung**: `machine_id` muss stabiler sein als eine flüchtige Session-ID. Nicht ideal: nur Hostname. Besser: Hostname + installierte Maschinen-ID + manuell gesetzter Alias.

#### 2.1.2 Root
Ein Root ist ein expliziter Scanbereich auf einer Maschine.
```yaml
root:
  root_id: heim-pc__home
  machine_id: heim-pc
  root_kind: abs_path
  root_value: /home/alex
  filesystem: ext4
  mountpoint: /home
  label: home
```
**Pflichtfelder**: `root_id`, `machine_id`, `root_kind`, `root_value`
**optionale Felder**: `filesystem`, `mountpoint`, `label`, `allow_content`, `priority`
**Etymologie**: Root kommt vom altenglischen rōt bzw. germanisch wurzel. Hier sinnvoll: der Wurzelpunkt eines beobachteten Dateibaums.

#### 2.1.3 Snapshot
Ein Snapshot ist ein historischer Zustand eines Roots.
```yaml
snapshot:
  snapshot_id: snap_2026-03-10T05:35:19Z_heim-pc__home
  machine_id: heim-pc
  root_id: heim-pc__home
  created_at: 2026-03-10T05:35:19Z
  scan_profile: default
  scan_config_hash: 83b1...
  inventory_ref: artifacts/inventory/...
  dirs_ref: artifacts/dirs/...
  summary_ref: artifacts/summary/...
  content_ref: artifacts/content/...   # optional
  topology_ref: artifacts/topology/... # optional
  hotspots_ref: artifacts/hotspots/... # optional
  workspaces_ref: artifacts/workspaces/... # optional
```
**Pflichtfelder**: `snapshot_id`, `machine_id`, `root_id`, `created_at`, `scan_config_hash`, mindestens ein Kernartefakt-Ref (`inventory_ref` oder `dirs_ref`)
**Sinn**: Snapshot ist die Zeitanker-Entität. Ohne Snapshot gibt es keine robuste Historie.

#### 2.1.4 File Entity
Das ist die heikelste Entität. Nicht nur „Beobachtung einer Datei“, sondern die über Zeit erkennbare Dateiidentität, soweit möglich.
Problem: Pfad allein ist instabil (Umbenennung, Verschieben, Ersetzen).
Vorschlag: File Entity bleibt zunächst optional und heuristisch, nicht kanonischer Pflichtkern.
```yaml
file_entity:
  entity_id: fe_...
  machine_id: heim-pc
  root_id: heim-pc__home
  first_seen_snapshot_id: snap_...
  canonical_rel_path: docs/architecture.md
  stable_fingerprint:
    checksum: sha256:...
    inode: 182771   # optional
    device: 2049    # optional
```
**Urteil**: Für Phase 1/2 ist `FileObservation` wichtiger als `FileEntity`. `FileEntity` sollte später kommen, wenn Rename-/Move-Erkennung ernsthaft gebaut wird.

### 2.2 Beobachtungsmodell

Beobachtungen sind die eigentliche Rohwirklichkeit.

#### 2.2.1 FileObservation
```yaml
file_observation:
  snapshot_id: snap_...
  rel_path: docs/architecture.md
  abs_path_hint: /home/alex/docs/architecture.md   # optional, nicht index-primär
  ext: .md
  mime_type: text/markdown
  size_bytes: 18234
  mtime: 2026-03-10T05:12:03Z
  ctime: 2026-03-10T05:12:03Z
  is_symlink: false
  is_text: true
  encoding: utf-8
  line_count: 412
  checksum: sha256:...
  owner: alex
  group: alex
  permissions: "0644"
```
**Pflichtkern**: `snapshot_id`, `rel_path`, `size_bytes`, `mtime`, `is_symlink`
**Optional**: `MIME`, `owner`, `group`, `permissions`, `checksum`, `encoding`, `line_count`, `is_text`, `ctime`, `abs_path_hint`, `ext`
**Designentscheidung**: `abs_path_hint` darf existieren, aber `rel_path` bleibt die kanonische Pfadachse innerhalb eines Roots.

#### 2.2.2 DirectoryObservation
```yaml
directory_observation:
  snapshot_id: snap_...
  rel_path: docs
  depth: 1
  kept_file_count: 84
  recursive_bytes: 812345
  child_dirs:
    - docs/api
    - docs/runtime
```
**Pflichtfelder**: `snapshot_id`, `rel_path`, `depth`
**Optional**: `kept_file_count`, `recursive_bytes`, `child_dirs`, `signal_count`

### 2.3 Abgeleitete Projektionen

Diese Artefakte sind nicht Rohwirklichkeit, sondern interpretierte Sichten.

#### 2.3.1 Workspaces
Aktuell bereits als Kategorie sichtbar. Die Blaupause ordnet sie klar als Annotation ein.
```yaml
workspace_annotation:
  snapshot_id: snap_...
  workspace_id: ws_a1b2c3d4
  root_path: repos/lenskit
  workspace_kind: python_project
  signals:
    - .git
    - pyproject.toml
    - README.md
  confidence: 0.9
  tags:
    - python_project
    - repo
```
**Hinweis**: Repo-/Workspace-Erkennung ist nützlich, aber nicht der Kern der Ontologie. Sonst driftet Atlas wieder in Richtung Entwicklerzoo.

#### 2.3.2 Hotspots
```yaml
hotspots:
  snapshot_id: snap_...
  top_dirs:
    - path: .cache
      bytes: 1827364512
  highest_file_density:
    - path: repos
      count: 18210
  deepest_paths:
    - path: some/nested/path
      depth: 12
  highest_signal_density:
    - path: repos/lenskit
      signals: 4
```
**Geplante Erweiterungen**: `growth_hotspots`, `duplicate_hotspots`, `change_hotspots`, `media_hotspots`, `archive_hotspots`

#### 2.3.3 TopologyProjection
```yaml
topology:
  snapshot_id: snap_...
  root_path: .
  nodes:
    docs:
      path: docs
      depth: 1
      dirs:
        - docs/api
        - docs/runtime
    repos:
      path: repos
      depth: 1
      dirs:
        - repos/lenskit
        - repos/metarepo
```
**Bemerkung**: Ich würde mittelfristig `root_path: "."` bevorzugen, weil das deterministischer ist. Aber das ist keine Grundsatzfrage des Fundaments, sondern ein späterer Contract-Schliff.

#### 2.3.4 ContentProjection
```yaml
content:
  snapshot_id: snap_...
  text_files_count: 8123
  binary_files_count: 391
  large_files:
    - path: videos/urlaub.mp4
      size: 1847234512
  extensions:
    .md: 421
    .py: 1821
    .jpg: 2031
```
**Später erweiterbar um**: `language_counts`, `mime_counts`, `encoding_counts`, `preview_refs`, `chunk_refs`

## 3. Snapshot-Mechanik

### 3.1 Snapshot-Erzeugung
Phasen: Root auflösen -> Rohinventar erzeugen -> Basisstats berechnen -> optionale Enrichment-Artefakte erzeugen -> Snapshot-Metadaten schreiben -> Snapshot registrieren.

Minimaler Write: `scan_result` -> `inventory.jsonl` -> `dirs.jsonl` -> `summary.md` -> `snapshot_meta.json` -> `snapshot_registry` append.

### 3.2 Snapshot-ID-Strategie
Format: `snap_<machine_id>__<root_id>__<UTC timestamp>__<short config hash>` (Beispiel: `snap_heim-pc__home__2026-03-10T053519Z__83b1`). Dies ist global unterscheidbar, Root-/Maschinenkontext ist sichtbar.

### 3.3 Snapshot-Registry
Atlas braucht eine Registry-Datei oder Tabelle.
```yaml
snapshot_registry:
  - snapshot_id: snap_...
    machine_id: heim-pc
    root_id: heim-pc__home
    created_at: 2026-03-10T05:35:19Z
    inventory_ref: ...
    content_ref: ...
    status: complete
```
**Speicherorte**:
* SQLite-Tabelle
* oder append-only JSONL/manifest + SQLite-Sekundärindex

**Meine Präferenz**: SQLite als Registry, Artefakte als Dateien. Nicht alles in SQLite, nicht alles im Dateisystem. Mischform.

## 4. Delta-Mechanik

### 4.1 Delta-Typen
* **Snapshot-to-Snapshot Delta**: Vergleich zweier Snapshots desselben Roots.
* **Cross-machine Delta**: Vergleich zweier Roots auf unterschiedlichen Maschinen.
* **Time-window Delta**: Vergleich erste vs letzte Beobachtung in Zeitraum.

### 4.2 Delta-Kernstruktur
```yaml
delta:
  delta_id: delta_...
  from_snapshot_id: snap_old
  to_snapshot_id: snap_new
  created_at: 2026-03-10T06:00:00Z
  new_files:
    - docs/new.md
  removed_files:
    - docs/old.md
  changed_files:
    - docs/architecture.md
  renamed_files: []   # später
  summary:
    new_count: 1
    removed_count: 1
    changed_count: 1
```
**Pflicht**: sortierte Listen, deterministische Ausgabe, klare Referenz auf beide Snapshots.

### 4.3 Renames
Rename-Erkennung ist verführerisch, aber teuer und fehleranfällig.
**Entscheidung**: Nicht Pflichtkern in Phase 1.
Später: optional über Hash-Matching, evtl. Heuristik (gleicher checksum, neuer Pfad, alter Pfad entfernt).

## 5. Artefaktklassen
* **Klasse A – Kernartefakte** (Immer): `inventory.jsonl`, `dirs.jsonl`, `summary.md`, `snapshot_meta.json`.
* **Klasse B – Enrichment-Artefakte** (Optional): `content.json`, `media.json`, `mime_summary.json`, `hashes.jsonl`.
* **Klasse C – Derivation-Artefakte** (Abgeleitet): `topology.json`, `hotspots.json`, `workspaces.json`, `duplicates.json`, `history_views.json`.
* **Klasse D – Index-Artefakte** (Suche/Retrieval): `fts.sqlite`, `chunk_index.sqlite`, `semantic_index/...`.

## 6. Speicherstrategie & Verzeichnisstruktur

### 6.1 Speicherstrategie
Registry + Indizes in SQLite (für Snapshot/Root/Machine Registries und schnelle Suche). Rohartefakte als Dateien (für große Inventare, Versionierung).

### 6.2 Verzeichnisstruktur-Vorschlag
```text
atlas/
  machines/
    heim-pc/
      roots/
        home/
          snapshots/
            snap_.../
              summary.md
              inventory.jsonl
              dirs.jsonl
              content.json
              topology.json
              hotspots.json
              workspaces.json
              snapshot_meta.json
        repos/
          snapshots/...
    heimserver/
      roots/...
  registry/
    atlas_registry.sqlite
  indexes/
    fts.sqlite
    semantic_chunks.sqlite
```

## 7. Index-Strategie
Suchachsen:
* **Dateimetadaten-Suche** (Pfad, Ext, Größe, Root)
* **Inhalts-Suche** (Volltext, Chunks)
* **Historie-Suche** (wann gesehen/geändert).
Backend: Primär SQLite + FTS.

## 8. Contracts, die Atlas künftig braucht

Hier wird es wichtig. Wenn diese Contracts fehlen, beginnt Drift.

### 8.1 Root Contract
Definiert:
* zulässige Root-Typen
* machine_id-Bindung
* Mount-/Filesystem-Metadaten
* Berechtigungsflags
* Inhaltszugriff ja/nein

### 8.2 Snapshot Contract
Definiert:
* Pflichtfelder eines Snapshots
* Artefakt-Refs
* scan_config_hash
* Status (running, complete, failed, partial)

### 8.3 Inventory Contract
Definiert:
* Pflichtfelder pro Datei
* optionale Felder
* JSONL-Form
* Stabilitätsgarantien

**Wichtige offene Stelle**: `is_text` sollte künftig explizit im Contract stehen als: optional oder guaranteed only in content-enabled scans. Diese Entscheidung darf nicht still im Code wohnen.

### 8.4 Delta Contract
Definiert:
* deterministische Listen
* Sortierreihenfolge
* Vergleichslogik
* Fehlerstruktur

### 8.5 Mode Output Contract
Definiert für `inventory`, `topology`, `content`, `workspace`:
* welche Artefakte mindestens entstehen
* welche leer sein dürfen
* welche Felder garantiert sind

Der aktuelle `planner.py` ist dafür ein guter technischer Anfang, aber noch kein offizieller Contract.

## 9. API-Strategie

Ich würde jetzt schon die verbalen Endpunkte festziehen, selbst wenn sie intern noch nicht voll ausgebaut sind.

### 9.1 Kernoperationen
* `atlas scan`
* `atlas snapshot`
* `atlas derive`
* `atlas diff`
* `atlas history`
* `atlas search`
* `atlas machines`
* `atlas roots`

**Wichtig**: Nicht wieder alles in `atlas scan --do-everything` kippen.

### 9.2 Semantischer Vorteil
Dann kannst du später:
* schnelle Discovery-Scans
* selektives Enrichment
* spätere Derivation
* getrennten Index-Rebuild
sauber auseinanderhalten.

## 10. Multi-Machine-Universum

Das ist die Achse, auf der Atlas wirklich groß wird.

### 10.1 Machine Registry
```yaml
machines:
  - machine_id: heim-pc
    hostname: heim-pc
    labels: [primary, workstation]
  - machine_id: heimserver
    hostname: heimserver
    labels: [server, remote]
```

### 10.2 Root Registry
```yaml
roots:
  - root_id: heim-pc__home
    machine_id: heim-pc
    path: /home/alex
  - root_id: heimserver__srv
    machine_id: heimserver
    path: /srv
```

### 10.3 Cross-Machine-Fähigkeiten
* Root-Vergleich
* Snapshot-Vergleich
* Diff
* Sync-Lücken
* Backup-Vollständigkeit

## 11. Alternative Sinnachse

Die übliche Frage lautet: *Wie scannt Atlas Dateien?*
Die wichtigere Frage lautet: *Wie erinnert Atlas Maschinenzustände so, dass spätere Systeme darüber denken können?*

Das ist der eigentliche architektonische Hebel. Nicht der Scannerlauf selbst, sondern die Form, in der Realität konserviert wird.

---

# Teil 3/4: Ausbaupfade, Phasenmodell, Kernfeatures mit höchstem Hebel

## 1. Strategische Leitfrage für den Ausbau

Die eigentliche Frage lautet nicht: *Welche Features wären cool?*
Sondern: *Welche Features erhöhen Atlas’ Wirklichkeitstreue und Nutzbarkeit am stärksten, ohne das System zu verkomplizieren?*

Daraus ergibt sich eine harte Priorisierung. Nicht jede brillante Funktion ist jetzt sinnvoll.

## 2. Priorisierungslogik

Ich ordne die kommenden Atlas-Funktionen nach fünf Kriterien:
1. **Hebel**: Wie stark erhöht die Funktion den praktischen Nutzen im Alltag?
2. **Systemtiefe**: Verbessert sie nur die Oberfläche oder den Kern?
3. **Replizierbarkeit**: Ist das Verhalten stabil, deterministisch, testbar?
4. **Anschlussfähigkeit**: Kann Lenskit/Heimgeist/HausKI später darauf aufsetzen?
5. **Drift-Risiko**: Verführt die Funktion Atlas dazu, seine Kernrolle zu verlieren?

## 3. Die große Ausbau-Roadmap (Übersicht)

Die detaillierte, abhakbare Roadmap mit spezifischen Tasks und Stop-Kriterien befindet sich in Teil 4. Hier ist die strategische Phasierung skizziert:

### Phase A – Atlas als belastbarer Kernscanner
**Muss können**: vollständige Datei-Inventur, Root-/Machine-Kontext, Snapshot-Erzeugung, saubere Registry.
**Warum diese Phase zuerst?**: Weil alle späteren Wunderwerke sonst auf unstabiler Rohwirklichkeit aufbauen. Ein wackliger Scanner mit toller Suchoberfläche ist nur ein eloquenter Irrtum.

### Phase B – Zeitgedächtnis
**Muss können**: Snapshot-Vergleich, deterministische Delta-Artefakte, Datei-/Root-Historie.
**Praktische Wirkung**: Ab hier wird Atlas von einem Scanner zu einem Gedächtnisorgan. (Was war gestern neu? Was änderte sich auf Heimserver vs. Heim-PC?)

### Phase C – Incrementalität und Watch-Mode
**Muss können**: inkrementelle Re-Scans, heuristische Änderungserkennung.
**Warum erst jetzt?**: Weil Incrementalität ohne gutes Snapshot-Modell gefährlich ist. Sonst optimierst du auf eine Realität, die du noch nicht sauber modelliert hast.

### Phase D – Inhaltszugang und Suchschicht
**Muss können**: Pfadsuche, Namenssuche, Extension-/MIME-Suche, Volltextsuche.
**Designregel**: Die Suche baut auf Artefakten auf, nicht auf ständigem Re-Scanning.

### Phase E – Systemanalyse und Cross-Machine Intelligence
**Muss können**: Cross-machine diff, Duplicate Detection, Storage-Hotspots, Old/Orphan analysis.

### Phase F – Wissenskarte und höhere Projektionen
**Muss können**: Knowledge Clusters, Dateiraum-Topologie, Wissenszonen, semantische Dateitags.

## 4. Die 12 Kernfeatures in endgültiger Priorisierung

### 4.1 Feature 1 – Snapshot Registry
**Warum so hoch?**: Ohne Registry kein Zeitmodell, ohne Zeitmodell kein Gedächtnis.
**Muss enthalten**: `machine_id`, `root_id`, `snapshot_id`, `created_at`, `artefact refs`, `status`.
**Priorität**: kritisch

### 4.2 Feature 2 – Incremental Scan
**Warum?**: Große Systeme mit Millionen Dateien werden sonst unerquicklich langsam.
**Minimalmechanik**: Vergleiche gegen letzten Snapshot, mtime/size/inode heuristics, optional Hash nur selektiv.
**Priorität**: kritisch

### 4.3 Feature 3 – File History
**Warum?**: Der größte Nutzsprung nach Snapshot/Diff.
**Ziel**: Fragen wie: wann erstmals gesehen? wann zuletzt geändert? in welchen Snapshots enthalten?
**Priorität**: sehr hoch

### 4.4 Feature 4 – Content Search
**Warum?**: Atlas wird ab hier alltagstauglich, nicht nur archivalisch.
**Ziel**: Volltextsuche, Content-Preview, strukturierte Parsergebnisse.
**Priorität**: sehr hoch

### 4.5 Feature 5 – Cross-Machine Diff
**Warum?**: Dein Setup lebt von mehreren Maschinen.
**Ziel**: Heim-PC vs Heimserver, Root A vs Root B, Backup-Lücken.
**Priorität**: sehr hoch

### 4.6 Feature 6 – Duplicate Detection
**Warum?**: Extrem hoher praktischer Nutzen bei Plattenrealität.
**Mechanik**: size prefilter -> hash confirmation -> cluster output.
**Priorität**: hoch

### 4.7 Feature 7 – Watch-Mode
**Warum?**: Macht Atlas lebendig und chronikfähig.
**Aber**: Nicht vor Snapshot-/Incremental-Grundlage.
**Priorität**: hoch, aber nach Incrementalität

### 4.8 Feature 8 – Storage Hotspots
**Warum?**: Schneller Nutzen, geringer Interpretationsaufwand.
**Typen**: largest dirs, largest files, growth hotspots, signal hotspots.
**Priorität**: hoch

### 4.9 Feature 9 – Orphan Detection
**Warum?**: Praktisch für Aufräumen und Ordnung.
**Typen**: forgotten downloads, dead dirs, stale archives, possibly unused repos.
**Priorität**: mittel-hoch

### 4.10 Feature 10 – Knowledge Clusters
**Warum?**: Wird für Navigation und Agenten sehr wertvoll.
**Aber**: Benötigt gute Such-/Inhaltsbasis.
**Priorität**: mittel

### 4.11 Feature 11 – Semantic File Tags
**Warum?**: Hilft bei Navigation, aber ist noch nicht Kern.
**Beispiele**: document, media, archive, backup, config, repo.
**Priorität**: mittel

### 4.12 Feature 12 – System Knowledge Map
**Warum?**: Sehr attraktiv, aber späte Projektion.
**Gefahr**: Zu früh gebaut → schöne UI ohne tragfähige Rohwirklichkeit.
**Priorität**: spät, aber wertvoll

## 5. Duplicate Detection im Detail
Das ist praktisch so nützlich, dass es erstaunlich lange als „später“ ignoriert wird.
**Ziel**: Duplikatgruppen über Maschinen, Roots und Medien hinweg finden.
* **Stufe 1**: Gruppierung nach Dateigröße
* **Stufe 2**: Hashbildung für Kollisionen
* **Stufe 3**: Gruppenartefakt erzeugen
```yaml
duplicate_set:
  duplicate_id: dup_...
  checksum: sha256:...
  members:
    - machine_id: heim-pc
      root_id: home
      rel_path: photos/img1.jpg
    - machine_id: backup-disk
      root_id: archive
      rel_path: backup/photos/img1.jpg
```

## 6. Watch-Mode und Chronik-Integration
Hier liegt ein großer Heimgewebe-Hebel.
### 6.1 Watch-Mode
`atlas watch /home/alex`
**Ziel**: Dateiänderungen live erkennen.
**Eventtypen**: `file_created`, `file_modified`, `file_deleted`, `file_moved`, `directory_created`, `directory_deleted`.

### 6.2 Chronik-Anbindung
Atlas sollte Watch-Events als Chronik-kompatible Artefakte exportieren.
**Pipeline**: `filesystem events -> atlas watch -> normalized file events -> chronik -> hausKI / heimgeist / leitstand`
**Nutzen**: Atlas wird von einem passiven Beobachter zu einem Echtzeit-Sensor.

## 7. Change Intelligence
Delta allein reicht nicht. Es braucht zweite Ordnung.
* **Erste Ordnung**: neue Datei, entfernte Datei, geänderte Datei
* **Zweite Ordnung**: wachsendes Verzeichnis, häufig modifizierter Bereich, plötzliche Datenflut, verdächtige Verschiebung von Wissensräumen, chronisch vergessene Archive
**Beispiel**: `atlas analyze changes --since 30d` (Output: Top growth roots, Most volatile directories, File type shifts).

## 8. Repo-/Workspace-Erkennung neu eingeordnet
Dieser Punkt muss explizit entgiftet werden, damit Atlas nicht driftet.
**Was bleibt sinnvoll?**: `.git`, `pyproject.toml`, `package.json`, `compose.yml`, `.ai-context.yml`, `.wgx`
**Warum?**: Weil sie nützliche Marker im Dateiraum sind.
**Die korrekte Einordnung**: Diese Marker definieren keine Hauptwelt, sondern nur eine zusätzliche Lesart: „Hier liegt vermutlich ein Entwicklungs-/Projektkontext.“
Damit bleibt Atlas sauber: Repo-/Workspace-Erkennung bleibt Annotation auf dem globalen Dateiatlas.

## 9. Was bewusst nicht priorisiert wird
Damit Atlas nicht entgleist:
* keine tiefe AST-/Codeanalyse im Atlas-Kern
* keine Git-Historie als Primärachse
* keine LLM-Semantik im Basisscan
* kein schweres UI vor stabilen Artefakten
* kein monolithischer Scan-Alleskönner
* keine frühe Backend-Religion (SQLite vs Tantivy als Glaubenskrieg)

---

# Teil 4/4: Verbindliche Architekturentscheidungen, Contracts, Verzeichnisstruktur, abhakbare Roadmap

## 1. Verbindliche Architekturentscheidungen (Setzungen)

### Entscheidung A — Atlas ist ein zustandsbehaftetes Gedächtnis
Jeder relevante Scan erzeugt einen persistenten Snapshot. Deltas und Historien bauen auf Snapshots auf. Pflichtobjekte: `machine`, `root`, `snapshot`.

### Entscheidung B — Atlas ist dateizentriert, Inhalte sind optionale Schicht
Pflichtkern: Pfad, Größe, Zeit, Typ, Root, Maschine.
Optional: `is_text`, encoding, line_count, preview, chunks, Volltextindex. Content darf nie den Discovery-Kern blockieren.

### Entscheidung C — Atlas ist eine Pipeline, kein Monolith
1. Discovery -> 2. Snapshot -> 3. Enrichment -> 4. Derivation -> 5. Indexing -> 6. Serving/Integration. Keine Gottfunktion (`atlas scan --everything`).

### Entscheidung D — Repo-/Workspace-Erkennung ist Annotation, nicht Leitontologie
Atlas modelliert primär Dateiwirklichkeit, nicht Projektpsychologie. Repo-Marker dürfen Atlas bereichern, aber nicht semantisch kapern.

### Entscheidung E — Registry in SQLite, schwere Artefakte als Dateien
SQLite für Machine Registry, Root Registry, Snapshot Registry, Delta Registry, Suchmetadaten/FTS.
Dateien für `inventory.jsonl`, `dirs.jsonl`, `content.json`, `topology.json`, `hotspots.json`, `workspaces.json`.
Atlas-Artefakte werden deterministisch gegen einen kanonischen Atlas-Basisordner aufgelöst (abgeleitet aus dem Registry-Pfad), nicht gegen den aktuellen Prozess-CWD.

## 2. Contracts, die du wirklich anlegen solltest

* **Machine Contract**: Pflichtfelder (`machine_id`, `hostname`). `machine_id` muss stabil sein.
* **Root Contract**: Pflichtfelder (`root_id`, `machine_id`, `root_kind`, `root_value`). Kein Scan ohne expliziten Root-Kontext.
* **Snapshot Contract**: Pflichtfelder (`snapshot_id`, `machine_id`, `root_id`, `created_at`, `scan_config_hash`, `status`, mindestens ein Kernartefakt-Ref). Statuswerte (`running`, `complete`, `partial`, `failed`).
* **Inventory Contract**: Pflichtfelder (`snapshot_id`, `rel_path`, `size_bytes`, `mtime`, `is_symlink`). Harte Entscheidung: `is_text` wird nicht universell garantiert, sondern nur wenn Content-Enrichment aktiv ist.
* **Delta Contract**: Pflichtfelder (`from_snapshot_id`, `to_snapshot_id`, `created_at`, `new_files`, `removed_files`, `changed_files`). Listen sind deterministisch, sortiert, reproduzierbar.
* **Mode Output Contract**: Garantiert spezifische Pflichtartefakte für `inventory`, `topology`, `content`, `workspace`.

## 3. ADR-artige Setzungen (Architecture Decision Records)
- [x] ADR-001 Atlas is filesystem-first, not repo-first
- [x] ADR-002 Atlas is stateful and snapshot-driven
- [x] ADR-003 Atlas uses pipeline stages, not monolithic scan flows
- [x] ADR-004 Repo/workspace detection is annotation only
- [x] ADR-005 Registry in SQLite, large artifacts as files
- [x] ADR-006 Content enrichment is optional and mode-dependent
- [x] ADR-007 Canonical Artifact Resolution for diff/comparison paths (Resolves against registry_db path, independent of CWD)
- [x] ADR-008 Official Atlas directory structure (machines/registry/indexes layout)
- [x] ADR-009 Atlas FTS search index (global index, derive write-path, hard-delete, latest-only default)

## 4. Abhakbare Roadmap

### Phase 0 — Konstitution und Contracts
Ziel: Atlas semantisch festziehen, bevor weiterer Ausbau Drift erzeugt.
- [x] ADR-001 bis ADR-007 anlegen
- [x] Machine Contract definieren
- [x] Root Contract definieren
- [x] Snapshot Contract definieren
- [x] Inventory Contract definieren
- [x] Delta Contract definieren
- *Implementierungsnotiz:* Delta und Comparison konsolidieren nun ihre CWD-unabhängige Artefaktauflösung und nutzen eine geteilte Parser-Logik; die bereits zuvor bestehende robuste Behandlung fehlerhafter Inventory-Zeilen (z.B. leere Zeilen, ungültiges JSON) ist damit konsistent in beiden Pfaden zentralisiert.
- [x] Mode Output Contract definieren
- [x] is_text-Garantie explizit dokumentieren
- [x] Verzeichnisstruktur offiziell festlegen (als Zielstruktur dokumentiert)

**Stop-Kriterium**: Atlas hat eine explizite, maschinenlesbare und dokumentierte Grundverfassung.

### Phase 1 — Registry-Kern
Ziel: Machine-, Root- und Snapshot-Wirklichkeit persistent und abfragbar machen.
- [x] atlas_registry.sqlite einführen
- [x] Machine Registry implementieren
- [x] Root Registry implementieren
- [x] Snapshot Registry implementieren (für CLI-Scan; Service-Integration folgt)
- [x] Snapshot-Status (running/complete/failed) implementieren
- [x] Snapshot-Artefakt-Refs konsistent in Zielstruktur speichern
- [x] Snapshot-ID-Schema vorläufig stabilisiert
- [x] CLI: `atlas machines`
- [x] CLI: `atlas roots`
- [x] CLI: `atlas snapshots`

**Stop-Kriterium**: Jeder Scan taucht als Snapshot mit Root-/Machine-Kontext in der Registry auf.

### Phase 2 — Zeitgedächtnis
Ziel: Atlas wird historisch nutzbar.
- [x] Snapshot-to-Snapshot Delta formal einführen
- [x] Delta Registry ergänzen
- [x] `from_snapshot_id` / `to_snapshot_id` standardisieren
- [x] sortierte Delta-Listen garantieren
- [x] CLI: `atlas diff <snapA> <snapB>`
- [x] CLI: `atlas history <machine_id> <root_id> <rel_path>`
- [x] Datei-Historienmodell definieren (Eine Datei-Historie wird über chronologisch sortierte `inventory.jsonl` Beobachtungen der Snapshots desselben Roots und canonical `rel_path` abgeleitet).
- [x] Root-Historienmodell definieren (Eine Root-Historie ergibt sich implizit durch alle `complete` Snapshots, die der `root_id` in der Registry zugeordnet sind).
- [x] Zeitfenster-Vergleiche konzipieren (Ein Zeitfenster-Vergleich entspricht der Aggregation von Deltas über alle Snapshots im Zielzeitraum, abgeleitet durch Registries).
- [x] Fehler-/Partial-Delta-Verhalten standardisieren (Ein Delta kann nur zwischen zwei `status="complete"` Snapshots auf derselben Machine und Root berechnet werden, sonst Abbruch).

**Stop-Kriterium**: Atlas kann Zustand und Veränderung über Zeit explizit zeigen.

### Phase 3 — Incrementalität
Ziel: Große Roots effizient aktualisierbar machen.
- [x] Re-Scan gegen letzten Snapshot vorbereiten
- [x] mtime-/size-Heuristik definieren
- [x] inode/device optional erfassen
- [x] selektives Hashing-Modell festlegen
- [x] heuristische Teilbaum-Kandidaten erkennen (`mtime`, counts, `direct_children_fingerprint`) ohne Traversal-Abbruch
- [ ] sicheren Teilbaum-Skip ermöglichen (benötigt externes Änderungsorakel wie Watcher)
  - *Methodischer Rückbau/Klärung: Der `recursive_hash` wurde als bottom-up Artefakt für Integrität und Vergleich eingeführt, ist aber ohne Orakel kein magischer Vorab-Skipper. Der eigentliche Skip (`dirs[:] = []`) bleibt deaktiviert, bis ein echtes Change-Oracle existiert. Zudem ist der Hash ein Vergleichsartefakt innerhalb des selektiven Hashing-Modells und damit nicht für alle Dateien zwingend rein inhaltsbasiert.*
- [x] `scan_config_hash` wirksam in Reuse-Logik einbeziehen
- [x] Basis-Incremental-Metriken erfassen
- [x] CLI: `atlas scan --incremental`
- [x] Regressionstests für inkrementelles Verhalten ergänzen

**Stop-Kriterium**: Ein Folgescan großer Roots ist deutlich günstiger als ein Vollscan.

### Phase 4 — Suchschicht
Ziel: Dateien und Inhalte systemweit abfragbar machen.
- [x] SQLite-FTS evaluieren und festziehen
  - *Architekturnotiz: FTS5 ist technologisch bestätigt (bereits für Chunks im Einsatz) und performant. Die vier offenen Integrationsentscheidungen aus `docs/architecture/atlas-fts-integration.md` wurden in **ADR-009** verbindlich entschieden (global index, derive-write-path, hard-delete-per-snapshot, latest-only-default). Implementiert als globaler Index `atlas/indexes/fts.sqlite` in `merger/lenskit/atlas/index.py` (`AtlasFTSIndex`): Scope/`ext`/Größe/Datum werden aus indizierten SQLite-Spalten bedient statt aus erneutem JSONL-Parsing (Glob-/Name-/Path-Exaktheit und die generische `query`-Substring-Prüfung bleiben Python-Postfilter über den SQL-eingegrenzten Kandidaten — nicht via FTS); die Indizierung läuft als best-effort Derivation-Schritt nach Snapshot-Abschluss. `search.py` nutzt den Index, wenn er alle Kandidaten-Snapshots konsistent abdeckt, und fällt sonst transparent auf den linearen Scan zurück. CLI: `atlas index rebuild` / `atlas index stats`, `atlas search --all-snapshots` / `--no-index`, `atlas scan --no-index`. Content-Suche: konservatives FTS-Narrowing (nur beweisbare Superset-Eingrenzung, sonst Live-Scan) + Live-Confirm; Invariante: indexgestützte Content-Suche verliert nie Treffer ggü. dem linearen Pfad (Snippet-Semantik unverändert).*
- [x] Metadaten-Suchschema definieren
- [x] Path-Search implementieren
- [x] Name-Search implementieren
- [x] Extension-/MIME-Search implementieren
- [x] Größen-/Datumsfilter implementieren
- [x] Content-Search implementieren (Hinweis: Volltextsuche liest 'best-effort' vom Live-Filesystem, keine strenge Snapshot-Inhalts-Reproduzierbarkeit)
- [x] Scope-Filter (machine, root, snapshot) implementieren
- [x] CLI: `atlas search`
- [x] Preview-/Snippet-Format definieren (erste Match-Zeile, getrimmt auf max. 200 Zeichen)

**Stop-Kriterium**: Dateibestände sind reproduzierbar über Registry + Index durchsuchbar. Inhaltssuche erfolgt best-effort über das Live-Dateisystem innerhalb der durch Snapshot/Root vorgefilterten Kandidatenmenge (keine strenge Snapshot-Reproduzierbarkeit).

### Phase 5 — Inhaltsanreicherung
Ziel: Dateien über Rohmetadaten hinaus erschließen, ohne den Kern zu überladen.

*(Konvention: [ ] = offen, [~] = substanziell begonnen bzw. funktional vorhanden, [x] = vollständig gehärtet und abgeschlossen.)*

*(Methodischer Hinweis: Die vormals hier abgehakten Features MIME/Encoding/line_count wurden im Rahmen des Phase-0-Audits bewusst zurückgebaut und de-markiert, da ihre erste Implementierung rein heuristisch war und noch nicht dem Robustheitsanspruch der Blaupause genügte.)*

- [~] MIME-Typ-Erkennung (Extension + Magic-Byte-Fallback)
  - implementation: done
  - tests: present
  - hardening: partial (best-effort Heuristik, Formatabdeckung ausbaufähig)
  - *Semantische Notiz: `mime_type` ist ein best-effort Feld. Die Erkennung ist heuristisch und teilweise umgebungsabhängig (z. B. durch `mimetypes`). Sie ist nicht gleichbedeutend mit einer vollständig reproduzierbaren Inhaltsklassifikation.*
- [~] Encoding-Erkennung (kleines best-effort Set)
  - implementation: done
  - tests: present
  - hardening: partial (Reproduzierbarkeit und Robustheit offen)
  - *Semantische Notiz: `encoding` ist ein best-effort Feld basierend auf einer 4KB-Heuristik. Es wird nur für plausibel textuelle Inhalte emittiert und ist keine garantierte Klassifikation.*
- [~] line_count im Content-Modus (`enable_content_stats`)
  - implementation: done
  - tests: present
  - hardening: partial (Verhalten für Non-Content-Scans methodisch unklar)
  - *Semantische Notiz: `line_count` ist ein best-effort Feld basierend auf zeilenweiser Zählung innerhalb des Content-Modus. Dateien >20MB werden aus Performance-Gründen übersprungen. Die Genauigkeit hängt bei Nicht-UTF-8-Dateien von der best-effort Encoding-Erkennung ab.*
- [ ] Parser für JSON/YAML/TOML/Markdown/CSV/HTML
- [ ] Medien-Minimalmetadaten (Bilddimensionen, Audio-/Video-Dauer)
- [ ] Preview-/Chunk-Artefakte definieren
- [ ] Content-Policy pro Root ermöglichen
- [~] Binary-/Huge-file-Strategie klären
  - implementation: done (Erfassung und Content-Bypass)
  - tests: present
  - hardening: partial (Abgrenzung zu reinen Binaries und Policy-Ebene fehlen)
- [x] Tests für modeabhängige Inhaltsfelder ergänzen (vorheriger `test_atlas_content_fields.py` war methodisch zu dünn)

**Stop-Kriterium**: Content-Enrichment ist modular, root- und modeabhängig zuschaltbar.

### Phase 6 — Analyseartefakte
Ziel: Atlas wird diagnostisch.
- [ ] Hotspots erweitern um Growth-/Change-Achsen
- [~] Duplicate Detection (size prefilter + hash confirm)
  - implementation: done (Offline CLI)
  - tests: present
  - hardening: partial (Echtzeit-/Online-Erkennung fehlt)
- [x] duplicates.json definieren (Wird generiert, als Artefakt im Snapshot abgelegt und formell in der Registry unter duplicates_ref hinterlegt)
- [x] orphans.json definieren (Wird generiert, als Artefakt im Snapshot abgelegt und formell in der Registry unter orphans_ref hinterlegt)
- [x] disk.json definieren (Wird generiert, als Artefakt im Snapshot abgelegt und formell in der Registry unter disk_ref hinterlegt)
- [~] analyze disk standardisieren
  - implementation: done (CLI Output und Disk-Artifact)
  - tests: present
  - hardening: partial (Vollständige Historienauswertung fehlt)
- [x] analyze duplicates implementieren (als CLI command `atlas analyze duplicates <snapshot_id>`)
- [x] analyze orphans implementieren (als CLI command `atlas analyze orphans <snapshot_id>`)
- [x] Oldest-/Largest-Files-Artefakte vereinheitlichen
- [~] Cross-root growth reports definieren
  - implementation: done (`atlas analyze growth`)
  - tests: present
  - hardening: partial (nur Snapshot-ID-Pfad und grundlegende Auflösung getestet; keine Zwischenhistorie, keine semantische Inhaltsgleichheit, keine persistierten Growth-Artefakte)

**Stop-Kriterium**: Atlas zeigt nicht nur Bestände, sondern konkrete Aufräum-, Speicher- und Vergleichsprobleme.

### Phase 7 — Multi-Machine-Atlas
Ziel: Maschinenübergreifende Dateiwirklichkeit sichtbar und vergleichbar machen.
- [x] mehrere Machines sauber registrieren (via --machine-id/--hostname CLI flags)
- [x] Root-Namenskonventionen zwischen Hosts vereinheitlichen
  - *Architekturnotiz: `root_label` ist nun systemisch als semantische Gruppierungsachse etabliert. Fehlende explizite Labels werden kanonisch aus dem Verzeichnisnamen generiert.*
- [~] Cross-machine snapshot diff definieren
  - implementation: done (struktureller Metadaten-Abgleich)
  - tests: present
  - hardening: partial (tiefe Inhaltsgleichheit nicht bewiesen)
- [x] CLI: `atlas diff heim-pc:/home heimserver:/home`
  - *Methodische Notiz: `machine:path` löst deterministisch auf den neuesten vollständigen Snapshot auf.*
  - *Semantische Notiz: `atlas diff` leitet cross-root Anfragen intern auf `cross-root-comparison` um (statt strengem `same-root-delta`). Der aktuelle Vergleich ist ein strukturbezogener Metadatenabgleich (`rel_path`, `size_bytes`, `mtime`) und kein inhaltlich tief gehärteter Gleichheitsbeweis.*
- [~] Backup-gap-Analyse definieren
  - implementation: done (CLI Command)
  - tests: present
  - hardening: partial (wie beim Diff fehlt inhaltliche Tiefe)
- [ ] Remote-Collector-/SSH-Modell festlegen
- [x] Konfliktfälle (gleiches root label, andere Pfade) definieren
  - *Semantische Notiz: Die label-basierte Diff-Auflösung verlangt pro Maschine Eindeutigkeit. Wenn ein Label auf einer Maschine mehrdeutig ist, muss zwingend `machine:path` oder `snapshot_id` verwendet werden.*
- [x] CLI: label-basierte Referenzauflösung in `atlas diff` und `atlas analyze backup-gap` (`machine_id:label:root_label`)
  - *Beispiel: `atlas diff laptop:label:documents nas:label:documents` (bzw. `atlas analyze backup-gap ...`)*
  - *Syntax-Notiz: Die zulässigen Snapshot-Referenzen sind explizit definiert:*
    * `snapshot_id`
    * `machine_id:path`
    * `machine_id:label:root_label`
  - *Regeln: `machine_id` und `root_label` werden normalisiert (getrimmt) und dürfen nicht leer sein. Im Fall `machine_id:path` bleibt der Path als ungetrimmter Referenzstring bestehen, um Whitespace-Grenzfälle auf Dateisystemen zu erhalten. `machine_id` darf kein `:` enthalten; `root_label` darf `:` enthalten. Ein Label muss pro Maschine für den Diff-Vergleich eindeutig sein.*
- [x] Maschinen-Health-/Last-Seen-Sicht ergänzen

**Stop-Kriterium**: Atlas kann Root- und Snapshot-Zustände über Maschinen hinweg vergleichen.

### Phase 8 — Watch-Mode und Chronik-Anbindung
Ziel: Atlas wird zu einem lebendigen Sensorsystem.
- [ ] Watch-Mode-Modell definieren
- [ ] inotify/fanotify-Strategie evaluieren
- [ ] Event-Schema für Dateiänderungen definieren
- [ ] Debounce-/Batching-Logik definieren
- [ ] Chronik-kompatiblen Exportpfad bauen
- [ ] CLI: `atlas watch /path`
- [ ] Snapshot-/Event-Verhältnis klären
- [ ] Watch-Failure-Recovery definieren

**Stop-Kriterium**: Atlas kann Dateiereignisse laufend beobachten und an Chronik weiterreichen.

### Phase 9 — Wissenskarte
Ziel: Die digitale Landschaft wird kartierbar.
- [ ] Knowledge-Cluster-Modell definieren
- [ ] systemweite Kategorien bestimmen
- [ ] `atlas map` Output-Format festlegen
- [ ] Root-/Machine-Karten definieren
- [ ] Cluster-Heuristiken bauen
- [ ] semantische Dateitags ergänzen
- [ ] UI-/Exportformate für Karten vorbereiten

**Stop-Kriterium**: Atlas kann Bestände nicht nur listen, sondern als maschinenweite Wissenslandschaft zeigen.

## 5. Meta-Reflexion: Sind wir kritisch genug?

Ja, aber mit zwei blinden Flecken, die explizit benannt werden müssen:

### Blinder Fleck 1
Wir haben noch keine exakte Aussage über die reale Dateimenge der Maschinen.
Größenordnungen und Scanfrequenzen fehlen; sie sind nötig, um Incrementalität, Hashing und Indexgröße präzise zu dimensionieren.

### Blinder Fleck 2
Wir haben noch keine endgültige Entscheidung über Content-Zugriffstiefe pro Root.
Das beeinflusst:
* Speicherbedarf
* Suchqualität
* Datenschutz-/Sicherheitsrestfragen
* Performance

## 6. Schlussverdichtung der gesamten Blaupause

Atlas soll werden: **der globale, historische Dateiatlas deiner Infrastruktur**

Mit diesem festen Kern:
* maschinenweit
* snapshot-getrieben
* dateizentriert
* pipelinebasiert
* suchfähig
* analysierbar
* repo-sensitiv, aber nicht repo-dominiert

Die entscheidende Formel lautet:
`Discovery -> Snapshot -> Enrichment -> Derivation -> Index -> Integration`

Und die wichtigste inhaltliche Invariante bleibt:
**Atlas modelliert zuerst Dateiwirklichkeit, nicht Entwicklerwirklichkeit.**

### Root Naming Convention (Cross-Host)
Um Maschinen systemweit und betriebssystemübergreifend vergleichen zu können, reicht die instanzbezogene `root_id` (z. B. `heim-pc__documents`) oft nicht aus. Lokale Dateipfade (`root_value`) benötigen für plattformübergreifende Äquivalenz ein abstraktes, gemeinsames semantisches Label (z. B. als künftiger eigener Bezeichner oder als kanonische Namenskonvention).
- **Windows:** `root_value="C:/Users/Name/Documents"` -> Semantisches Label: `documents`
- **Linux:** `root_value="/home/name/Documents"` -> Semantisches Label: `documents`
Während `root_id` die maschinenspezifische Instanz identifiziert und `root_value` den physischen Ankerpunkt darstellt, ermöglicht erst ein einheitliches semantisches Label, dass Cross-Machine-Analysen künftig automatisiert geclustert werden können.
- `root_label` ist die semantische Vergleichsebene für Roots.
- Mehrere `root_ids` können denselben `root_label` haben, um anzuzeigen, dass sie logisch das gleiche Verzeichnis (auf verschiedenen Hosts) repräsentieren.
- Cross-Machine-Analysen (wie Sync-Lücken oder Duplikate) werden perspektivisch auf `root_label` als gemeinsame Identitätsachse basieren.
- `atlas roots` gibt standardmäßig strukturierte JSON-Daten zurück, um den maschinenlesbaren Contract zu wahren. Eine gruppierte Ansicht ist explizit über `--group-by-label` als zusätzliche Projektion verfügbar.

### Root Identity Contract
- Lokale Roots können beim initialen Scan explizite Identifier (`--root-id`) und semantische Labels (`--root-label`) erhalten, um auto-generierte Default-IDs deterministisch zu übersteuern.
- Explizite Identitäten werden vor der Registry-Zuweisung kanonisch normalisiert (`strip()`). Explizite Leerstrings sind als Überschreibung unzulässig.
- `root_id` muss streng filesystem-sicher sein, d. h. sie muss dem Muster `^[A-Za-z0-9._-]+$` entsprechen. Isolierte Pfad-Navigatoren wie `.` oder `..` sind unzulässig.
- `root_id` identifiziert eine konkrete Root-Instanz. Eine bestehende `root_id` darf nicht still auf einen anderen `root_value` derselben Maschine umgebogen werden. Rebinding ohne explizite Migrations-/Umschreiblogik ist verboten.
- Ebenso darf eine bestehende `root_id` nicht still überschrieben und einer anderen Maschine (`machine_id`) zugeordnet werden.

### Machine Identity Contract
- `machine_id` und `hostname` werden vor Registrierung kanonisch normalisiert (`strip()`, `lower()`). Bei Legacy-Reuse kann jedoch zur Wahrung bestehender Referenzen (z. B. auf Snapshots oder Roots) die bereits gespeicherte Registry-ID weiterverwendet werden.
- `machine_id` ist der stabile Identifier für ein Gerät. Er muss das Format `^[a-z0-9_.-]+$` erfüllen (z. B. `heim-pc`, `macbook-pro-m1`).
- Eine `machine_id` darf nicht beliebig mehrfach mit verschiedenen Hostnamen verknüpft werden. Konfliktprüfung erfolgt auf den normalisierten Werten. Wenn eine `machine_id` bereits existiert und ein Scan mit abweichendem `hostname` gestartet wird, wird die Registrierung abgelehnt.
- Die Auflösungsreihenfolge ist strikt: explizite CLI-Overrides (`--machine-id`, `--hostname`) stechen die Umgebungsvariable `ATLAS_MACHINE_ID`, welche wiederum den System-Hostname-Fallback aussticht.
