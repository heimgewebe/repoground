# Glossar

> Aktualisiert am 2026-05-31.
> Knappe Definitionen der load-bearing Begriffe. Kanonische Rollennamen folgen
> `merger/lenskit/contracts/bundle-manifest.v1.schema.json` und der
> Namensdisziplin der [Master-Roadmap](roadmap/lenskit-master-roadmap.md).

## Kern & Organismus

- **Heimgewebe-Organismus** — Verbund mehrerer Repos; Lenskit ist darin
  **Merger**, **Scanner** und epistemischer Kern.
- **repoLens** — Pythonista/iPad- und CLI-Frontend zum Erzeugen von Bundles.
- **rLens** — Web-UI/Service-Schicht (FastAPI) für Heim-PC/Server. Funktionsgleich
  zu repoLens (Parität verpflichtend). *Hinweis:* `cli/rlens.py` ist der
  Service-Launcher, `cli/cmd_rlens_client.py` der HTTP-Client.
- **Bundle** — Ausgabe eines Merges: Sammlung von Artefakten zu einem Lauf,
  registriert im `bundle_manifest`.
- **Invariante Sektionsreihenfolge** (Spec v2.4) — *Source & Profile → Profile
  Description → Reading Plan → Plan → Structure → Manifest → Content*. Fehlende
  oder vertauschte Sektion = Fehler.

## Artefakte & Rollen

- **`canonical_md`** — der vollständige Markdown-Dump; **die Wahrheitsquelle**,
  gegen die zitiert wird (kanonischer Dateiname: `*.merge.md`).
- **`bundle_manifest`** — Registry aller Bundle-Artefakte (Rolle, Pfad, Hash);
  perspektivisch zentrale Registry.
- **`dump_index_json` / `derived_manifest_json`** — abgeleitete Index-/Manifest-
  Views (historisch auch `derived_index_json`).
- **`sqlite_index`** — SQLite-FTS5-Volltextindex (historisch `chunk_index_sqlite`).
- **`chunk_index_jsonl`** — Chunk-Spannen (Bytes/Zeilen) für FTS & Range-Auflösung.
- **`citation_map_jsonl`** — bildet Quell-Byte-Bereiche auf stabile **Citation-IDs**
  ab; `derived`/`navigation_index`. Ersetzt **nicht** den `chunk_index`.
- **`agent_reading_pack`** — kompaktes Markdown, das ein LLM-Agent **zuerst** liest
  (Lese-Policy, Artefaktrollen, Suchanleitung, Health-Summary, Top-Chunk-Spans);
  `navigation_index`, **nicht Wahrheit**.
- **`output_health`** — maschinenlesbarer Selbsttest des Bundles
  (`diagnostic_signal`).

## Range-Referenzen

- **`range_ref`** — präzise, hash-verifizierte Adresse auf einen Byte-/Zeilen-
  Bereich in einem Artefakt oder einer Quelldatei.
- **v1 vs v2** — v2 (`range-ref.v2.schema.json`) trennt **Artefakt**-Koordinaten
  (`artifact_byte_start/-_line_start`, `range_content_sha256`) sauber von
  **Quell**-Koordinaten (`source_file_path`, `source_line_start`) und ist
  v1-kompatibel (Legacy-Aliase werden auf Konsistenz geprüft).
- **explicit vs derived** — bundle-gestützte vs. quell-gestützte Auflösung.

## Authority / Canonicality / Risk-Class (Governance, Track C)

- **Authority** — was ein Artefakt aussagen *darf*: `canonical_content`,
  `navigation_index`, `runtime_cache`, `diagnostic_signal`, `runtime_observation`,
  `agent_context_projection`.
- **Canonicality** — `canonical` | `derived` | `diagnostic`.
- **Risk-Class** — abgeleitet aus Authority: `content`, `navigation`, `cache`,
  `diagnostic` (für `retrieval_index` bewusst **kein** Wert — Schema sperrt ihn).
- **`allowed_inferences` / `forbidden_inferences`** — optionale, maschinenlesbare
  Inferenz-Grenzen in Diagnose-Contracts (was man aus dem Artefakt schließen darf
  bzw. nicht).
- **Anti-Hallucination-Lints L1–L6** — L3/L5 contract-statisch (blockierend);
  L1/L2/L4 AST-/codepfadbasiert (experimentell, marker-gated, nicht-blockierend);
  L6 = Export-Gate-Integration.
- **Authority-Upgrade-Registry** — deklariert *bewusste* Authority-Hebungen (z. B.
  `derived_projection → canonical_content` in `resolve_canonical_md`), damit der
  AST-Lint Intent von echter Warnung unterscheidet — ohne Detektion abzuschalten.

## Evidence-Levels

- **Evidence-Level** — gestufte Belegtiefe eines Bundles. **`forensic_strict`** ist
  die strengste Stufe; sie verlangt eine vorhandene **`claim_evidence_map`** und ist
  bis dahin „blocked until available" (siehe
  `docs/architecture/artifact-evidence-levels.md`).
- **`claim_evidence_map`** — geplantes Artefakt (output-optimierung Arbeitspaket F),
  das Behauptungen auf Belege abbildet; Voraussetzung für `forensic_strict`.

## Meta-Density & Extras

- **`meta_density`** — Drosselung der Metadaten: `min` | `standard` | `full` |
  `auto`. `auto` ⇒ `standard` bei aktivem Filter, sonst `full`.
- **Extras (`ExtrasConfig`)** — additive Report-Module (Health, Organism-Index,
  Fleet-Panorama, Augment-/JSON-Sidecar, Delta-Reports, Heatmap). Rein additiv —
  verändern die Kernstruktur nicht.
- **Coverage** — Header-Zeile „N/M Dateien mit vollem Inhalt".

## Parität & Gates

- **`content_parity_pass`** — gleiche Repo-Dateien, Source-Hashes, source-basierte
  Chunk-Abdeckung, logisch gleiche FTS-Inhalte (leere FTS bei textlosen Repos
  erlaubt).
- **`diagnostic_parity_pass`** — zusätzlich `output_health.verdict==pass`,
  `range_ref_resolution_status==ok`, keine Health-Warnings/-Errors, konsistente
  Artefakt-Hashes; profilabhängige Artefakte nur bei gesetztem `*_expected`-Flag
  (fail-closed).
- **Parity-Guard** — Skript (`tools/parity_guard.py`), das Backend-Modell ↔ CLI ↔
  HTML ↔ JS-Payload abgleicht (CI-Gate).

## Retrieval & Graph

- **FTS** — Full-Text-Search über `sqlite_index`.
- **Semantic Re-Ranking** — 2-Stufen-Design: lexikalische Kandidaten →
  Embedding-Rerank; gesteuert über `embedding-policy.v1` inkl. `fallback_behavior`.
- **Graph-Index / Import-Graph / Entrypoints** — Architektur-Graph, der Retrieval
  optional verbessert (boost nahe Entrypoints), aber Evidence-Addressing nicht
  ersetzt.

## Federation (Cross-Repo, Phase 4)

- **`cross_repo_links`** — Verknüpfungen korrelierter Artefakte über Repo-Grenzen.
- **`federation_conflicts`** — sichtbar gemachte Cross-Bundle-Konflikte.
- **`federation_trace`** — Provenance der föderierten Query.

## Atlas (Paralleltrack)

- **Atlas** — Dateisystem-Explorer (physische Wahrnehmung / FS-Snapshot), getrennt
  von der Repo-Merge-Pipeline.
- **Snapshot / Delta** — persistierter FS-Zustand bzw. Differenz zweier Snapshots.
- **`root_kind`** — `preset` | `token` | `abs_path` (kein impliziter Fallback;
  `..`/relative Pfade abgewiesen).
