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

## 3. Was fehlt komplett (Echte Inkonsistenzen / Nicht-Ziele)?
*(Diese Aspekte sind in der Blaupause definiert, aber im Code nicht existent)*

*   **Phase 5 (Cross-Repo-Knowledge-Layer):** Nicht mehr als vollständig nicht existent zu beschreiben. Aktueller Status ist **partial/minimal**: `federation_index`-Schema/Grundlagen sind vorhanden, `cross_repo_links` hat Contract plus minimalen heuristischen Producer, `federation_conflicts` wird heuristisch/minimal emittiert; föderierte Query-Pfade sind teilweise vorhanden. Offen bleiben belastbare Identity-Engine, Conflict-Semantik, Cross-Bundle-Evidence, API-/Runtime-Integration sowie Tests/Hardening.
*   **Phase 6 (Agent Control Surface - Session Trace):** Ein explizites `agent_query_session.json` (Session Trace) Artefakt wird noch nicht geschrieben, obwohl ein HTTP API-Endpoint existiert.

## 4. Architektonische Zusammenfassung
Die Grundlagen der Phase 1 bis 3 und wesentliche Strukturbausteine der Phase 4 sind für isolierte, lokale Bundles nachvollziehbar implementiert und reduzieren den Drift vor der Cross-Repo-Komplexität erheblich. Für die verbleibenden Gates der Phase 4 (insbesondere API/UI-Struktur und tatsächliche Agenten-Sicherheit) sind jedoch stärkere Integrationstests erforderlich. Die Föderation (Phase 5) ist im aktuellen Stand **partial/minimal** umgesetzt, aber als robuste Architekturphase noch offen; Hardening bleibt eine eigenständige Komplexitätsstufe.