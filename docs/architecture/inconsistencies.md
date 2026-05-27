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
| README beschreibt `TOP_FILES` als "wichtigste Quelldateien" (Importance-Claim), Pack-Producer dagegen "by chunk coverage" | `README.md:35` (korrigiert) vs `merger/lenskit/core/agent_reading_pack.py:489-494` | **resolved** (README + Pack-Heading, PR A1 umgesetzt) | Heading ist `TOP_CHUNK_SPANS` (`agent_reading_pack.py:489`); `test_agent_reading_pack.py` asserted `## TOP_FILES` nicht mehr vorhanden |
| `output_health.verdict=pass` möglich trotz `redact_secrets=false` und `agent_pack=skipped` | `merger/lenskit/core/output_health.py:461-491` | offen (by design der Health-Schicht) | separates Gate `post_emit_health`/agent-safe (PR A4/A5), Health nicht umbiegen |
| Auto-Claim-Bewertung: AP F verlangt `supported/unsupported` | `docs/blueprints/lenskit-output-optimierung-v1.md` AP F (korrigiert) | resolved | nur `claim → evidence_refs` + `does_not_establish`, kein Verdikt |
| Zwei Profilnamensschemata | AP E vs `docs/blueprints/lenskit-artifact-output-control-plane.md` §7 | resolved (Mapping) | control-plane-Namen kanonisch |
| `is_noise_file.noisy_dirs` inkonsistent mit `SKIP_DIRS` | `merger/lenskit/core/merge.py:1772-1780` vs `merger/lenskit/core/merge.py:297-314` | **resolved** (PR A2 umgesetzt) | single source of truth `_BUILD_AND_CACHE_DIRS` (`merge.py:309`) speist sowohl `SKIP_DIRS` (`merge.py:327`) als auch `is_noise_file` (`merge.py:1792`); Drift strukturell ausgeschlossen |
| `.ruff_cache` im Output (Plan-Beleg) | Plan-extern, Snapshot `lenskit-max-260502-*` | **stale/closed** | bereits behoben durch `SKIP_DIRS` (#681–#683) |

## 7. Suboptimalitäten-Audit (2026-05-25)

Systematischer Sweep über Code (`merger/lenskit/`, `scripts/`, `tools/`) und Tests auf
Drift, Inkonsistenzen und Tech-Debt. Behobene Punkte sind verifiziert (Python-/Repo-Testlauf:
1456 passed, 1 skipped; zusätzlich wurden 7 vorbestehende Browser-/Playwright-Errors beobachtet,
ohne Bezug zu diesem Audit-Patch).
Offene Punkte tragen eine klare Folgeaktion und wurden bewusst **nicht** blind geändert.

| Befund | Beleg | Status | Folge |
| :--- | :--- | :--- | :--- |
| MD5-Aufrufe ohne `usedforsecurity=False` (inkonsistent mit kanonischem Muster, triggert bandit B303) | `merge.py:2674`, `adapters/sources.py:318` vs. kanonisches Muster `merge.py:1907`, `cli/cmd_atlas.py:663`, `adapters/atlas.py:516` | **behoben** | beide Stellen auf `usedforsecurity=False` + `# nosec B303` angeglichen (nicht-sicherheitsrelevante Namens-/Snapshot-Hashes) |
| Debug-Ausgaben auf **stdout** statt stderr (verschmutzt den Daten-Kanal bei aktivem `debug`) | `merge.py:3330, 3401-3404, 3654, 4975` (alle `if debug:`-gated) vs. CLI-Konvention `file=sys.stderr` (`cmd_query.py:98,119`) | **behoben** | alle auf `file=sys.stderr` umgestellt; kein Test hing an stdout-Erfassung dieser Strings |
| `lenskit verify` war ein Platzhalter-No-op ("Verify command placeholder. Use pr-schau-verify for now.") | `cli/main.py:219-221` (alt) | **behoben** | an den vorhandenen contract-gestützten Verifier (`pr-schau.v1`) verdrahtet: neuer Library-Entry `pr_schau_verify.run_verify(bundle, level)` (Exit-Code statt `sys.exit`), Subparser mit `bundle`/`--level`; Standalone-`main()`-Verhalten erhalten; Verifier-Tests erweitert/grün; E2E-Smoke geprüft |
| Irreführender `DEPRECATED`-Hinweis an `build_agent_query_session` (v1) — würde zu verlustbehafteter Migration verleiten | `retrieval/session.py:167` (alt). v1 ist **live**: Datei-Artefakt mit Integrity+Environment, genutzt von `cli/cmd_query.py:108`, getestet gegen `agent-query-session.v1.schema.json` (`test_cli_agent_session.py:93`). v2 ist die Runtime-Inline-Form des Service (`service/app.py:671,843`) | **behoben** (Hinweis korrigiert) / **offen** (Konsolidierung) | Note präzisiert: v1/v2 sind parallele Liefer-Formen, kein Vorgänger/Nachfolger; naive Migration würde Integrity/Environment verlieren und das On-Disk-Schema ändern. Folge: separater Design-PR, ob auf eine einzige Session-Schema-Form (v2-Datei-Variante mit Integrity/Environment) konsolidiert wird |
| Test-Lint-Debt (F841 ungenutzte Vars, E712 `== True/False`) außerhalb des CI-Gates (CI = nur F401/F811) | 18 Treffer in 13 Test-Dateien (u.a. `test_atlas_custom.py`, `test_atlas_registry.py`, `test_runner_pool.py`, `test_citation_validate.py`) | **behoben** | tote Zuweisungen entfernt / Seiteneffekt-Calls ohne Bindung belassen / `== True/False` → `is True/False`; `ruff --select=F401,F811,F841,E711,E712` jetzt sauber |
| Atlas-CLI-Definitionen dupliziert (manuelle Sync-Pflicht, Drift-Risiko) | `cli/main.py:131-132` (NOTE) und `cli/rlens.py` | **behoben** | Atlas-Subparser zentralisiert: `register_atlas_commands(subparsers)` + `handle_atlas_command(args)` in `cli/cmd_atlas.py` (Muster `register_*_commands`); `cli/main.py` und `cli/rlens.py` rufen beide den Registrar auf; Entry-Point-Parser-Drift zwischen lenskit und rlens strukturell ausgeschlossen; Dispatch-Drift innerhalb des zentralen Atlas-Moduls wird durch `handle_atlas_command` laut statt still fehlschlagen. Verifikation: `merger/lenskit/tests/test_cli_atlas_registrar.py` deckt lenskit- und rlens-Dispatch, analyze-growth-Argumente, Subcommand-Set des gemeinsamen Registrars und unbekannte Dispatch-Werte ab; bewusst kein roher Help-String-Vergleich als Primärnachweis wegen entrypoint-spezifischer usage-Präfixe. Zusätzlich manueller Help-Smoke: `lenskit atlas --help` / `rlens atlas --help`. |
| Breite `except Exception: pass`-Blöcke (stilles Fehler-Schlucken) in Kern/Service | u.a. `core/merge.py:5889,5911`, `service/app.py:70,334,1026`, `service/jobstore.py:179,194,202,268` | **offen (Audit)** | bewusst nicht pauschal geändert (viele sind defensive Pfade, v.a. Pythonista-Frontend). Getrackt: gezielter Audit, ob Kern/Service-Stellen min. auf `logger.debug/warning` statt stillem `pass` umgestellt werden |

### Nicht-Befunde (geprüft, kein Handlungsbedarf)
- Produktionscode ist auf den CI-relevanten Regeln (`F401`, `F811`) sauber; die ~136 Default-ruff-Treffer (`E701`, `E402`, `E741`, …) sind bewusst **nicht** im CI-Gate und wurden **nicht** angefasst (keine Konventions-Überschreitung).
- Die in §6 als „offen" geführten PR-A1/PR-A2-Punkte sind im Code bereits umgesetzt; ihre Statuszeilen wurden in diesem Audit korrigiert (Doku-Drift behoben).
