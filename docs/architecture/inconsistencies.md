# Offene Inkonsistenzen-Liste (Lenskit Phase 0)

Stand: Phase 0 Re-Audit (Implementierungsstand von Phase 1 bis 4)

Diese Liste dokumentiert systematisch die Lücken zwischen der visionären Zielarchitektur (Blaupause), der aktuellen Code-Basis (`merger/lenskit/`) und der tatsächlichen Testabdeckung. Ziel ist es, den Ist-Zustand als Vermessungsprotokoll belastbar darzustellen.

## 1. Was ist implementiert, dokumentiert und methodisch belegt?
*(Diese Aspekte sind durch Code, Contracts und spezifische Test-Invarianten nachgewiesen)*

*   **Artefakt-Zentrierung & Contracts (Phase 1):** Die Kernartefakte (`canonical_md`, `chunk_index.jsonl`, `index.sqlite`, `dump_index.json`, `index_sidecar.json`) werden konsistent und deterministisch erzeugt. Die Manifest-Rollen (`ArtifactRoles`) decken sich exakt mit dem `bundle-manifest.v1.schema.json`. Ein `Role-Completeness-Check` schützt vor Enum-Drift.
*   **Query-Runtime & Explain (Phase 2):** Die `execute_query` Pipeline in `query_core.py` ist gestuft (Parse, Retrieve, Rerank, Provenance, Explain). Der Score (z.B. BM25) spiegelt sich in den Explain-Daten wider. Fehlerpfade verwenden Fallback-Marker statt stillem Abbruch.
*   **Graph-Runtime (Phase 3):**
    *   `load_graph_index` lädt und normalisiert den Graphen zentral (Fail-Closed).
    *   Das Explain-Objekt zeigt `graph_used`, `graph_status`, `distance` und `graph_bonus` präzise an.
    *   Eval (`test_eval_graph_delta_reporting`) berichtet Deltas (`baseline_mrr` vs `graph_mrr`).
    *   Staleness (`canonical_dump_index_sha256`) wird beim Laden verifiziert (`stale_or_mismatched`).
*   **Context-Bundle & Output-Profile (Phase 4, strukturell):**
    *   Hit, Evidence (Snippet) und Context (`graph_context`) sind getrennt.
    *   Context-Expansion (exact, window) ist implementiert und erzeugt gültige JSON-Strukturen.
    *   Die Provenance (explicit `range_ref` vs derived `derived_range_ref`) bleibt stabil.
    *   Output-Profile (`human_review`, `agent_minimal`, `ui_navigation`) filtern interne Status-Variablen heraus.

## 2. Was war in der Blaupause abgehakt, aber "nur" strukturell oder unvollständig belegt?
*(Hier drohte Architektur-Drift durch vorzeitige "Fertig"-Meldungen. Diese Punkte wurden in der Blaupause wieder de-markiert)*

*   **API/UI-ready Struktur & WebUI (Phase 4):**
    *   *Befund:* API-Endpunkte (FastAPI, `service/app.py`) und ein rudimentäres WebUI (`app.js`, `index.html` mit Badges) existieren strukturell.
    *   *Lücke:* Ein vollständiger, repo-weiter End-to-End-Nachweis der API-Sicherheit, Skalierbarkeit und echten Produktionsreife fehlt in der aktuellen Testsuite. Die UI/Agent-Integration ist methodisch nur im Ansatz belegt. Die entsprechenden Roadmap-Punkte und das Gate für Phase 4 wurden zurückgenommen.
*   **Context-Nutzbarkeit (Phase 4):**
    *   *Befund:* Tests für Context-Bundles prüfen Output-Profile auf korrekte Struktur und Datenfilterung (`test_ui_payload_excludes_internal_fields`).
    *   *Lücke:* Dies belegt formale Strukturkonformität, ist aber kein umfassender Beleg für inhaltliche oder ergonomische "Kontextnutzbarkeit" im Sinne von Agenten-Feedbackschleifen.

## 3. Offene und teilweise offene Inkonsistenzen / Nicht-Ziele
*(Diese Aspekte sind in der Blaupause definiert, aber im Code nicht oder nur partial/minimal belastbar umgesetzt.)*

*   **Phase 5 (Cross-Repo-Knowledge-Layer):** Nicht mehr als vollständig nicht existent zu beschreiben. Aktueller Status ist **partial/minimal**: `federation_index`-Schema/Grundlagen sind vorhanden, `cross_repo_links` hat Contract plus minimalen heuristischen Producer, `federation_conflicts` wird heuristisch/minimal emittiert; föderierte Query-Pfade sind teilweise vorhanden. Offen bleiben belastbare Identity-Engine, Conflict-Semantik, Cross-Bundle-Evidence, API-/Runtime-Integration sowie Tests/Hardening.

## 4. Geschlossene Altbefunde / PR-0-Restcheck

Dieser Abschnitt dokumentiert ehemalige Inkonsistenzbefunde, die durch aktuellen Repo-Stand nicht mehr als offene Lücke geführt werden.

*   **Phase 6 (Agent Control Surface - Session Trace):** Altbefund ist **closed/resolved**. `agent_query_session` wird als Runtime-Artefakt gebaut (`build_agent_query_session_v2`), bei aktivem Store persistiert und via `/api/artifact_lookup` referenzierbar gemacht.

| Historischer Begriff / Altbefund | Kanonischer Begriff / Ist-Zustand | Betroffene Datei(en) | Aktueller Status | Folgeaktion |
| :--- | :--- | :--- | :--- | :--- |
| `agent_query_session.json` „wird noch nicht geschrieben“ | Runtime-Artefakt `agent_query_session` wird gebaut und (bei aktiviertem `QueryArtifactStore`) gespeichert; Lookup über `artifact_ids.agent_query_session` und `/api/artifact_lookup` | `merger/lenskit/retrieval/session.py`, `merger/lenskit/service/app.py`, `docs/architecture/runtime-matrix.md`, `docs/architecture/artifact-inventory.md` | resolved/closed | keine Folgeaktion für PR-0 |

## 5. Architektonische Zusammenfassung
Die Grundlagen der Phase 1 bis 3 und wesentliche Strukturbausteine der Phase 4 sind für isolierte, lokale Bundles nachvollziehbar implementiert und reduzieren den Drift vor der Cross-Repo-Komplexität erheblich. Für die verbleibenden Gates der Phase 4 (insbesondere API/UI-Struktur und tatsächliche Agenten-Sicherheit) sind jedoch stärkere Integrationstests erforderlich. Die Föderation (Phase 5) ist im aktuellen Stand **partial/minimal** umgesetzt, aber als robuste Architekturphase noch offen; Hardening bleibt eine eigenständige Komplexitätsstufe.

## 6. Anti-Hallucination Output Audit (2026-05-21)

Vollbefund: `docs/proofs/anti-hallucination-capability-audit.md`. Neu sichtbar gemachte
Drifts/Widersprüche (nicht Phase-0-Altbefunde):

| Befund | Beleg | Status | Folge |
| :--- | :--- | :--- | :--- |
| README beschreibt `TOP_FILES` als "wichtigste Quelldateien" (Importance-Claim), Pack-Producer dagegen "by chunk coverage" | `README.md:35` (korrigiert) vs `merger/lenskit/core/agent_reading_pack.py:489-494` | resolved (README) / offen (Heading-Rename PR A1) | `TOP_FILES → TOP_CHUNK_SPANS` |
| `output_health.verdict=pass` möglich trotz `redact_secrets=false` und `agent_pack=skipped` | `merger/lenskit/core/output_health.py:461-491` | offen (by design der Health-Schicht) | separates Gate `post_emit_health`/agent-safe (PR A4/A5), Health nicht umbiegen |
| Auto-Claim-Bewertung: AP F verlangt `supported/unsupported` | `docs/blueprints/lenskit-output-optimierung-v1.md` AP F (korrigiert) | resolved | nur `claim → evidence_refs` + `does_not_establish`, kein Verdikt |
| Zwei Profilnamensschemata | AP E vs `docs/blueprints/lenskit-artifact-output-control-plane.md` §7 | resolved (Mapping) | control-plane-Namen kanonisch |
| `is_noise_file.noisy_dirs` inkonsistent mit `SKIP_DIRS` | `merger/lenskit/core/merge.py:1772-1780` vs `merger/lenskit/core/merge.py:297-314` | offen | reconcile (PR A2) |
| `.ruff_cache` im Output (Plan-Beleg) | Plan-extern, Snapshot `lenskit-max-260502-*` | **stale/closed** | bereits behoben durch `SKIP_DIRS` (#681–#683) |
