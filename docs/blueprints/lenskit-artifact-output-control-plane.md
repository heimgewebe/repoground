# Lenskit Artifact Output Control Plane

Status: Blueprint  
Scope: repolens, rlens, Lenskit CLI, UI, Manifest, Output Health  
Version: v0.1

Ziel: Artefaktproduktion profilierbar, beweisbar, laufzeitbewusst und UI-tauglich machen, ohne Inhaltswahrheit, Navigation, Diagnose und Cache zu vermischen.

## 0. Kernentscheidung

Nicht Artefakte hart zusammenlegen.  
Nicht alle Artefakte immer sichtbar machen.  
Nicht einzelne Toggles als Default anbieten.

Stattdessen:

1. Rollenmodell bleibt strikt.
2. Profile sind UI- und CLI-Presets.
3. Capability-Matrix entscheidet, was eine Umgebung wirklich prüfen kann.
4. Evidence-Level beschreibt, welches Vertrauensniveau erreicht wurde.
5. Pre- und Post-Health trennen Erzeugungszeitpunkte.
6. Konsumentenmatrix verhindert stille Legacy-Brüche.

## 1. Begriffe

### 1.1 Artifact Role

Eine Artefaktrolle beschreibt, was ein Artefakt sagen darf.

Beispiele:
- `canonical_md`: Inhaltswahrheit
- `bundle_manifest`: Artefaktregistry und Rollen-/Hashwahrheit
- `agent_reading_pack`: Agenten-Navigation
- `chunk_index_jsonl`: Retrieval-Navigation mit Byte-/Line-Ranges
- `citation_map_jsonl`: stabile Evidenzadressierung
- `output_health`: Diagnose
- `sqlite_index`: Runtime-Cache für FTS5/BM25
- `index_sidecar_json`: Legacy-/Navigation-Sidecar
- `dump_index_json`: Navigationsindex
- `derived_manifest_json`: abgeleitete Artefaktregistry
- `architecture_summary`: kompakter Architekturüberblick
- `retrieval_eval_json`: Retrieval-Diagnose

### 1.2 Capability

Eine Capability beschreibt, was die aktuelle Umgebung wirklich kann.

Beispiele:
- `jsonschema_available`
- `sqlite_fts5_available`
- `secure_path_resolution_available`
- `post_emit_validation_available`
- `citation_map_validation_available`
- `claim_evidence_map_available`
- `redaction_enabled`
- `local_filesystem_access`
- `ios_sandbox_runtime`
- `service_runtime`

### 1.3 Evidence Level

Ein Evidence Level beschreibt, wie stark ein Bundle als Agenten- oder Review-Grundlage taugt.

Level:
- `readable`
- `navigable`
- `citable`
- `range_strict`
- `searchable`
- `diagnostic_full`
- `forensic_strict`

Wichtig: Ein Profil fordert Ziel-Level an. Health beweist, welcher Level tatsächlich erreicht wurde.

## 2. Normative Invarianten

### 2.1 Wahrheit ist singulär

Nur `canonical_md` trägt Inhaltswahrheit.

Verboten:
- SQLite als Wahrheit lesen
- JSON-Sidecar als vollständigen Inhalt behandeln
- Agent Reading Pack als Beleg zitieren
- Health-Warnungen in UI oder Agent Pack verstecken

### 2.2 Navigation ist kein Beweis

`agent_reading_pack`, `chunk_index_jsonl`, `citation_map_jsonl`, `dump_index_json`, `derived_manifest_json` und `index_sidecar_json` dürfen Inhalte finden, aber nicht ersetzen.

### 2.3 Manifest ist Artefaktregistry

`bundle_manifest` registriert alle erzeugten Artefakte mit:
- role
- path
- content_type
- bytes
- sha256
- authority
- canonicality
- regenerable
- staleness_sensitive

### 2.4 Health ist zweistufig

Ein einzelner Health-Lauf ist nicht ausreichend, wenn Artefakte erst nach ihm erzeugt werden.

Pflicht ist die Unterstützung eines zweistufigen Health-Modells. Die konkrete Requiredness ist profil- und runtimeabhängig:
- `pre_emit_health` ist Baseline für alle Profile; während der Migration entspricht bestehendes `output_health` diesem Zustand.
- `post_emit_health` ist required für agentische, lokale Such- und Debug-Profile, aber nicht zwingend für minimale Lean-Archive.

`pre_emit_health` prüft:
- canonical hash
- chunk index hash
- sqlite consistency, falls erzeugt
- range_ref soweit in der Umgebung möglich
- redaction status

`post_emit_health` prüft:
- final manifest completeness
- agent_reading_pack presence/hash
- profile conformance
- skipped roles explained
- emitted roles match manifest
- evidence level actually reached

## 3. Quellenlage und Ausgangsbefund

Aktueller Befund:
- `agent_reading_pack` ist ausdrücklich `navigation_index` und `derived`; `canonical_md` ist die einzige Quelle der Wahrheit.
- Die Artefakte sind bereits nach Rollen und Autorität unterscheidbar.
- Der aktuelle repolens-Output enthält `canonical_md`, `chunk_index_jsonl`, `citation_map_jsonl`, `derived_manifest_json`, `dump_index_json`, `index_sidecar_json`, `output_health` und `sqlite_index`.
- `output_health` kann `warn` sein, wenn Range-Ref-Validierung wegen fehlendem `jsonschema` nicht streng geprüft werden kann.
- `claim_evidence_map` existiert noch nicht und bleibt eine explizite epistemische Leerstelle.

## 4. Artifact Role Matrix

| Role | Authority | Canonicality | Pflicht? | Hauptzweck | Wahrheit? |
|---|---|---|---|---|---|
| canonical_md | canonical_content | content_source | immer | Inhalt | ja |
| bundle_manifest | navigation/control | registry | immer | Rollen, Hashes, Pfade | nur Artefaktwahrheit |
| output_health | diagnostic_signal | diagnostic | migration/current | aktuelles Health-Artefakt; vorläufig Legacy-Pre-Health | nein |
| pre_emit_health | diagnostic_signal | diagnostic | target/immer | Produktionsdiagnose nach Health-Split | nein |
| post_emit_health | diagnostic_signal | diagnostic | agent+ | finale Bundle-Diagnose | nein |
| agent_reading_pack | navigation_index | derived | agent+ | Agenteneinstieg | nein |
| chunk_index_jsonl | retrieval_index | derived | agent+ | Suche/Range-Navigation | nein |
| citation_map_jsonl | navigation_index | derived | evidence+ | stabile Zitate | nein |
| sqlite_index | runtime_cache | cache | local-search+ | schnelle FTS5-Suche | nein |
| dump_index_json | navigation_index | index_only | legacy/debug | Range-/Dump-Navigation | nein |
| derived_manifest_json | navigation_index | derived | debug | Derived Registry | nein |
| index_sidecar_json | navigation_index | index_only | legacy/debug | alter Agent-Sidecar | nein |
| architecture_summary | navigation_index | derived | debug | Architekturüberblick | nein |
| retrieval_eval_json | diagnostic_signal | diagnostic | debug/CI | Retrieval-Benchmark | nein |
| claim_evidence_map | evidence_index | derived | future forensic | Claim → Beleg | nein, aber beweisnah |

## 5. Capability Matrix

Pflichtdokument: `docs/architecture/artifact-capability-matrix.md`.

Regel: Ein Profil darf angefordert werden. Health entscheidet, ob es vollständig erfüllt wurde oder nur degradiert.

## 6. Evidence Levels

### 6.1 `readable`
Erreicht, wenn:
- `canonical_md` vorhanden
- Manifest vorhanden
- Hash von `canonical_md` ok
- Pre-health nicht fail

### 6.2 `navigable`
Zusätzlich:
- `agent_reading_pack` vorhanden
- `chunk_index_jsonl` vorhanden
- Chunk-Index Hash ok

### 6.3 `citable`
Zusätzlich:
- `citation_map_jsonl` vorhanden
- Citation Map gegen `canonical_md` validierbar
- stabile canonical ranges vorhanden

### 6.4 `range_strict`
Zusätzlich:
- `jsonschema_available`
- range_ref resolution ok
- keine environment_error-Degradation

### 6.5 `searchable`
Zusätzlich:
- `sqlite_index` vorhanden
- sqlite row count == chunk count
- sqlite FTS row count == chunk count
- fts_content_non_empty == true

### 6.6 `diagnostic_full`
Zusätzlich:
- debug sidecars vorhanden
- retrieval_eval_json vorhanden, wenn angefordert
- architecture_summary vorhanden
- skipped diagnostics explizit erklärt

### 6.7 `forensic_strict`
Zukunftslevel. Zusätzlich:
- claim_evidence_map vorhanden
- keine required checks skipped
- post_emit_health pass
- range_strict erfüllt
- citable erfüllt
- redaction policy explizit

## 7. Output-Profile

### 7.1 `lean-readable`
Enthält: `canonical_md`, `bundle_manifest`, `pre_emit_health`.

### 7.2 `lean-evidence`
Enthält: `canonical_md`, `bundle_manifest`, `pre_emit_health`, `citation_map_jsonl` sowie `chunk_index_jsonl` als temporäre Abhängigkeit, solange Citation-Validation nicht als chunk-unabhängig nachgewiesen ist.

Migrationsziel: `chunk_index_jsonl` kann für `lean-evidence` optional werden, sobald die Validierung von `citation_map_jsonl` gegen `canonical_md` robust ohne Chunk-Index belegt ist.

### 7.3 `agent-portable`
Enthält: `canonical_md`, `bundle_manifest`, `pre_emit_health`, `post_emit_health`, `agent_reading_pack`, `chunk_index_jsonl`, `citation_map_jsonl`.

### 7.4 `local-search`
Enthält alles aus `agent-portable` plus `sqlite_index`.

### 7.5 `debug-full`
Enthält alles aus `local-search` plus `dump_index_json`, `derived_manifest_json`, `index_sidecar_json`, `architecture_summary` und optional `retrieval_eval_json`.

### 7.6 `forensic-strict`
Zukunftsprofil; blockiert bis `claim_evidence_map` verfügbar ist.

## 8. Runtime Defaults

| Runtime | Default-Profil | Begründung |
|---|---|---|
| iOS/repoLens | agent-portable | wenig Ballast, Agentenfähigkeit, portable Warnlogik |
| Heim-PC/rLens | local-search | SQLite-Suche lokal sinnvoll |
| Heimserver/rLens | local-search | Service-Runtime profitiert von Cache |
| CI | debug-full | Regression und Diagnose wichtiger als Größe |
| Archivexport | lean-evidence | klein, aber zitierbar |
| Sicherheits-/Auditexport | forensic-strict (später) | derzeit blockiert |

## 9. UI-Modell

UI zeigt primär Profile, nicht Einzeldateien; Status muss echten Health- und Evidence-Stand anzeigen (`pass`, `warn`, `fail`, `blocked`) statt kosmetischer Ampel.

## 10. CLI-Modell

Ziel-Interface (geplant; nicht aktueller CLI-Stand):

```bash
python3 -m merger.lenskit.cli.main merge --profile max --artifact-profile agent-portable
```

Weitere Profile analog: `local-search`, `debug-full`; Custom via `--with/--without`.

CLI validiert vor Produktion:
- missing dependency
- unsupported capability
- impossible evidence level
- deprecated role
- forbidden role in runtime

## 11. Manifest-Erweiterung

`bundle_manifest` erhält einen Block `artifact_output` mit requested/effective profile, requested/achieved evidence level, emitted roles und explained skipped roles.

## 12. Health-Erweiterung

Transitional Naming (Kompatibilität):
- Während der Migration bleibt bestehendes `output_health` als kompatibler Vorläufer bestehen und entspricht vorläufig `pre_emit_health`.
- `post_emit_health` wird additiv eingeführt (kein harter Rename in Phase A).
- Consumers dürfen bis zur Umstellung weiter `output_health` lesen.

Naming-Mapping:

| Phase | Rolle | Dateiname | Status |
|---|---|---|---|
| current / migration | `output_health` als Legacy-Pre-Health | `<stem>.output_health.json` | bestehend, kompatibel |
| future split | `post_emit_health` | `<stem>.bundle_health.post.json` | geplant/additiv |

Verdicts:
- `pass`: alle required checks erfüllt
- `warn`: nutzbar, aber Degradation sichtbar
- `fail`: Profilziel nicht sicher nutzbar
- `blocked`: angefordertes Profil in Runtime nicht erzeugbar

## 13. Konsumentenmatrix

Pflichtdokument: `docs/architecture/artifact-consumer-matrix.md`.

Keine Rolle darf aus einem Default-Profil entfernt werden, solange ihr Konsumentenstatus unbekannt ist.

## 14. Capability-Matrix

Pflichtdokument: `docs/architecture/artifact-capability-matrix.md`.

## 15. Evidence-Level-Matrix

Pflichtdokument: `docs/architecture/artifact-evidence-levels.md`.

## 16. Contract-Strategie

Nicht sofort schema-first.

- Phase 1: Dokumente und Matrizen
- Phase 2: Non-normative JSON examples
- Phase 3: Schema `merger/lenskit/contracts/artifact-output-policy.v1.schema.json`
- Phase 4: CI-validierte Beispiele

## 17. Dependency-Regeln

Hard rules:
- `canonical_md` darf nie fehlen.
- `bundle_manifest` darf nie fehlen.
- Health darf nie fehlen.
- `agent_reading_pack` braucht `canonical_md + bundle_manifest`.
- `chunk_index_jsonl` braucht `canonical_md`.
- `citation_map_jsonl` braucht `canonical_md`.
- `sqlite_index` braucht `chunk_index_jsonl`.
- `range_strict` braucht `jsonschema_available`.
- `searchable` braucht `sqlite_fts5_available`.
- `forensic_strict` braucht `claim_evidence_map`.
- Kein derived artifact darf `canonical_content`-Authority beanspruchen.

## 18. Migration

Phase A bis G:
- A: Policy Docs
- B: Health Split
- C: Profile Engine
- D: Manifest Extension
- E: CLI
- F: UI
- G: Deprecation (erst nach Konsumentenmatrix)

## 19. Tests

Unit, Integration, Regression und UI-Checks gemäß Profil-/Evidence-/Health-Logik; insbesondere `jsonschema unavailable => warn`, und fehlender `agent_reading_pack` wird post-emit erkannt.

## 20. Acceptance Criteria

Umgesetzt, wenn u. a. gilt:
- UI nutzt Profile statt Rohartefaktliste.
- CLI erzeugt Profile deterministisch.
- Manifest erklärt requested/effective/emitted/skipped.
- Health ist zweistufig oder äquivalent post-hoc.
- Achieved Evidence Level wird ausgewiesen.
- `canonical_md` bleibt einzige Inhaltswahrheit.
- `forensic-strict` bleibt blockiert, solange `claim_evidence_map` fehlt.
