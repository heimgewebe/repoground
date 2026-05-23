# Context Quality Signals (`context_quality`) — Implementation Proof

Status: Implementation note for roadmap **PR B1** (Context Quality Signals).
Belegbasis: `docs/blueprints/lenskit-anti-hallucination-output-architecture.md` §3 (Milestone B, PR B1),
`docs/architecture/artifact-evidence-levels.md`,
`docs/proofs/anti-hallucination-capability-audit.md` (Zeile 20 / B1),
`docs/proofs/post-emit-health-implementation-proof.md` (Vorbild für unregistrierte Diagnose-Artefakte).

## 1. Diagnose (vor der Implementierung)

- `git status --short` war sauber auf `claude/modest-bohr-SJJXj`.
- `rg "context_quality|understanding_health|agent_use_constraints|does_not_mean|risk_class"`:
  vor dieser PR existierten nur **Doku-Verweise** (Blueprint B1, Audit-Zeile 20), **kein**
  `context_quality.json`, **kein** Core-Modul, **kein** Schema, **keine** CLI.
- Bestehende Muster bestätigt und wiederverwendet: `core/output_health.py`,
  `core/post_emit_health.py`, `core/agent_export_gate.py`, deren Schemas, `cli/cmd_bundle_health.py`,
  `core/path_security.resolve_secure_path`, `core/post_emit_health.derive_post_health_path`.
- Ergebnis: B1 existierte nicht — additiv neu gebaut (kein Duplikat).

## 2. Kernaussage: was `context_quality` ist und was nicht

`context_quality` ist eine **diagnostische Projektion** bereits vorhandener Signale
(Manifest-Rollen-Verfügbarkeit, `output_health`-Checks, `post_emit_health`-Status / erreichter
Evidence-Level, `retrieval_eval`-Metriken, optionales `agent_export_gate`-Ergebnis). Es ist
ausdrücklich:

- **kein** kanonischer Inhalt (kanonische Wahrheit bleibt `canonical_md`),
- **kein** Verstehens-Verdict (kein `understanding_health`, kein Gesamt-Score),
- **kein** Retrieval-Vollständigkeitsbeweis (Metriken sind mechanisch, nicht „complete"),
- **kein** Antwort-Sicherheits-Gate (keine Aussage über antwort-sichere Nutzung),
- **keine** Claim-Wahrheitsbewertung (keine Verdikte `supported/unsupported/true/false/proven`),
- **kein** Ersatz für `output_health` oder `post_emit_health` — beide bleiben unverändert und
  werden nur als Beobachtung projiziert.

`authority` ist immer `diagnostic_signal`, `risk_class` immer `diagnostic`.

## 3. Was gebaut wurde (additiv, lokal)

- `merger/lenskit/contracts/context-quality.v1.schema.json` — neuer, lokaler Contract.
- `merger/lenskit/core/context_quality.py` — Projektor: `compute_context_quality` (rein, keine
  Writes) und `write_context_quality` (optional persistierend), plus
  `derive_context_quality_path`.
- `merger/lenskit/cli/cmd_context_quality.py` + Dispatch in `cli/main.py`:
  `lenskit context-quality inspect <manifest> [--json] [--emit-artifact] [--output PATH]`.
- Datei-Artefakt (nur bei `--emit-artifact`/`--output`): `<stem>.context_quality.json`.
- Tests: `merger/lenskit/tests/test_context_quality.py`,
  `merger/lenskit/tests/test_cli_context_quality.py`.
- Diese Beweisnotiz: `docs/proofs/context-quality-signals-proof.md`.

## 4. Naming-Disziplin: `projection_status`, kein globaler Verdict

Das Kopf-Feld heißt **`projection_status`** mit Werten `complete | degraded | blocked`. Es
beschreibt **ausschließlich** die Vollständigkeit der Projektion — nicht Kontextqualität, nicht
Repository-Verstehen, nicht Antwortsicherheit:

- `complete` — Manifest lesbar **und** alle projizierten Signalquellen verfügbar, ohne Warnungen.
- `degraded` — Manifest lesbar, aber ≥1 optionale Signalquelle fehlt/ist invalide oder es gab
  eine Warnung. Das ist der **erwartete Normalzustand** für minimale Bundles.
- `blocked` — Manifest unlesbar/fehlend/kein JSON/kein `repolens.bundle.manifest`; es konnte
  **keine** Projektion erstellt werden. Auch der `blocked`-Report ist schema-valide.

Es gibt bewusst **kein** globales `status`-Feld. Die in der Anweisung vorgesehene Ausnahme
(„falls top-level `status` unvermeidbar") war nicht nötig.

## 5. Harte Grenzen (eingehalten)

- **Reine Projektion, keine Inferenz:** `output_health.verdict` → `verdict_observed`
  (Beobachtung). `post_emit_health.status` → `status_observed` (Projektion). Aus `output_health`
  wird **nie** Post-Emit-Validität abgeleitet; aus `post_emit_health` **nie** Antwortsicherheit;
  aus `retrieval_eval` **nie** Vollständigkeit; das `agent_export_gate` wird **nie** als
  Claim-Wahrheit umgedeutet. Die Pflicht-Constraints (`agent_use_constraints`) und Disclaimer
  (`does_not_mean`) sagen das maschinenlesbar.
- **Verbotenes Vokabular:** keine Feldnamen/Verdikt-Werte `understanding_health`,
  `understanding_score`, `context_score`, `agent_safe`, `agent_ready`, `safe`, `unsafe`,
  `green`, `yellow`, `red`, `supported`, `unsupported`, `true`, `false`, `proven`, kein
  aggregierter Score. `answer_safe_without_citations` erscheint **nur** in `does_not_mean`.
  Negativtest: `test_no_global_understanding_or_safety_verdict` (geht den gesamten Report durch).
- **Evidence-Vokabular wiederverwendet:** `evidence_level`/`evidence_levels_reached` stammen aus
  `post_emit_health` und nutzen nur das bestehende Vokabular (`readable…forensic_strict`). Keine
  neuen Level, kein `understanding_health`.
- **Sichere Pfadauflösung:** manifest-deklarierte Artefakte werden über
  `resolve_secure_path(manifest_dir, …)` aufgelöst (kein Directory-Traversal, keine absoluten
  Pfade aus dem Manifest).
- **Keine Manifest-Mutation, keine Registrierung:** `write_context_quality` schreibt nur die
  Sidecar-Datei; das Bundle-Manifest wird **nicht** verändert und das Artefakt **nicht**
  registriert. Tests: `test_write_persists_unregistered_without_mutating_manifest`,
  `test_context_quality_cli_emit_artifact_does_not_mutate_manifest`. Manifest-Registrierung ist
  in dieser PR **bewusst nicht** implementiert und bleibt einem späteren, explizit
  registrierenden Schritt vorbehalten.
- **B2 bleibt getrennt:** **PR B2 (Retrieval Miss Taxonomy) ist in dieser PR NICHT
  implementiert.** Misses werden hier **nicht** klassifiziert; `retrieval_eval` wird nur
  mechanisch projiziert. B2 bleibt ein separates, zukünftiges Arbeitspaket.
- **Unverändert gelassen:** `output_health`, `post_emit_health`, `retrieval_eval`
  (Scoring/Schema), `agent_export_gate`-Semantik, Redaction-Enforcement,
  Manifest-Mutation/-Registrierung, MCP/Task-Pack/Dashboard/Monitor, Claim-Wahrheitsvokabular.

## 6. Inventar / Contracts-Matrix: bewusst nicht erweitert (mit Begründung)

`docs/architecture/artifact-inventory.md` und `docs/contracts/contracts-matrix.md` listen
manifest-registrierte bzw. vertraglich getrackte Artefakte. Die unmittelbaren Vorbilder
`post_emit_health` (PR A4) und `agent_export_gate` (PR A5) sind **unregistrierte
Diagnose-Projektionen** und stehen **ebenfalls nicht** in diesen beiden Dokumenten. Da
`context_quality` zur gleichen Klasse gehört (unregistriert, nicht im Manifest), folgt diese PR
dem Präzedenzfall und erweitert Inventar/Matrix **nicht**. Das vermeidet Drift; die
Roadmap-/Proof-Pflege bleibt der maßgebliche Tracker. (Anweisungskonform: „update inventory/matrix
only if their current structure tracks this new artifact/contract".)

## 7. Roadmap geprüft und aktualisiert

- Geprüft: `docs/roadmap/lenskit-master-roadmap.md`,
  `docs/blueprints/lenskit-anti-hallucination-output-architecture.md`,
  `docs/architecture/artifact-evidence-levels.md`, `docs/architecture/artifact-inventory.md`,
  `docs/contracts/contracts-matrix.md`.
- Aktualisiert: Master-Roadmap (neuer B1-Status-Abschnitt: implementiert, Dateien, Validierung,
  Nicht-Ziele, B2 separat) und Blueprint B1 (`UMGESETZT`, Repo-Befund nicht länger
  „kein `context_quality.json`"). Der historische Audit-Eintrag (Zeile 20) erhält eine
  Vorwärts-Notiz, damit kein Dokument still „kein `context_quality.json`" behauptet.

## 8. Validierung

```
ruff check --select=F401,F811 --exclude='**/fixtures/**' .          # All checks passed!
python3.11 -m pytest merger/lenskit/tests/test_context_quality.py \
                     merger/lenskit/tests/test_cli_context_quality.py    # 24 passed
python3.11 -m pytest merger/lenskit/tests/test_output_health.py \
                     merger/lenskit/tests/test_post_emit_health.py \
                     merger/lenskit/tests/test_cli_bundle_health.py \
                     merger/lenskit/tests/test_bundle_manifest_integration.py  # 93 passed (keine Regression)
```

Forbidden-Vocabulary-Check: programmatisch über `test_no_global_understanding_or_safety_verdict`
(walkt den gesamten Report: keine verbotenen Schlüssel/Verdikt-Werte, kein `*_score`,
`answer_safe_without_citations` nur in `does_not_mean`) sowie per `rg` über die neuen
Implementierungs-/Schema-/Doku-Dateien.
