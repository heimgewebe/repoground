# Lenskit Output- und Repo-Härtung v1 (Abhakbare Blaupause)

> **Reconciliation (2026-05-21):** Die Anti-Hallucination-Erweiterung dieser Roadmap
> ist reconciled in `docs/blueprints/lenskit-anti-hallucination-output-architecture.md`,
> der Befund/Falsifikation in `docs/proofs/anti-hallucination-capability-audit.md`.
> Dort sind die Arbeitspakete A–H auf die Anti-Hallucination-PRs (A1–A5, B1–B3, C1–C2,
> D, E, F1–F3, G) abgebildet, inkl. der epistemischen Korrektur an Arbeitspaket F.

## These / Antithese / Synthese

### These
- [x] Lenskit besitzt eine tragfähige Artefaktordnung (canonical Markdown, Chunk-Index, Dump-Index, SQLite-Cache, Manifest, Architektur-Summary).
- [x] Rollen sind im Manifest getrennt:
  - [x] `canonical_md` = Inhaltsquelle.
  - [x] `chunk_index_jsonl` = Retrieval-Index.
  - [x] `sqlite_index` = Runtime-Cache.

### Antithese
- [x] Output ist vollständig, aber für Agenten noch nicht zuverlässig genug suchbar, zitierbar und health-geprüft.
- [x] Historischer Lokalbefund (Snapshot `lenskit-max-260502-1126_*`):
  - [x] `chunk_index.jsonl`: 539 Chunks.
  - [x] `content_range_ref` bei 539/539.
  - [x] `content` bei 0/539.
  - [x] SQLite: 539 FTS-Zeilen, `avg(length(content)) = 0.0`.
- [x] Kurzbild: sauberer Katalog, leere Bücher.

### Synthese
- [ ] Fokus nicht auf „größerem Dump", sondern auf **Evidence-Control-Plane**.
- [ ] Jeder Output muss sich selbst beweisen können: vollständig, suchbar, auflösbar, zitierbar, hash-konsistent, agententauglich.
- [ ] Leitfrage: Wie erzeugt Lenskit Outputs, die Agenten nicht mehr falsch lesen können?

---

## Präzisierungen vor Umsetzung

- Lokal geprüfte Befunde sind Momentaufnahmen des Outputs `lenskit-max-260502-1126_*`; sie gelten nicht automatisch für spätere Outputs.
- Jeder Lokalbefund muss vor Codeänderung durch ein reproduzierbares Diagnose-Skript oder einen Test bestätigt werden.
- Hash-Prüfung erfolgt über den originalen Byte-Slice aus `canonical_md`, nicht über dekodierten oder normalisierten Text.
- Noch nicht existierende CLI-Kommandos werden ausdrücklich als „geplant" markiert.
- `output_health.json` prüft zunächst Range-Ref v1; Range-Ref v2 erweitert später die Zeilenachsen.
- `agent_pack_present` ist bis Abschluss von Arbeitspaket D nur warnend, danach blockierend.
- `derived_index.json` bleibt Registry für abgeleitete Artefakte; `output_health.json` bleibt funktionaler Health-Report.

---

## 0) Zielbild

- [ ] Pipeline als prüfbare Kette etablieren:
  - [ ] `canonical_md` = vollständige Wahrheit.
  - [ ] `chunk_index_jsonl` = präzise Range-Navigation.
  - [ ] `sqlite_index` = echte Volltextsuche.
  - [ ] `agent_reading_pack` = kompakter Einstieg.
  - [ ] `output_health.json` = Selbstprüfung.
  - [ ] Query/Context APIs = zitierbar, begrenzt, claim-bewusst.

---

## 1) Belegter Ist-Zustand

- [x] Dump vollständig: 357/357 Textdateien.
- [x] `merge.md` als kanonische Quelle markiert.
- [x] Reading Policy: Markdown kanonisch, JSON Navigation/Metadaten.
- [x] Rollenmodell trennt Autoritäten (`canonical_content`, `navigation_index`, `retrieval_index`, `runtime_cache`, `diagnostic_signal`).
- [x] `range-ref.v1`: Byte-/Line-Range + `content_sha256`.
- [x] Query-Result-Schema kennt `claim_boundaries`, `evidence_basis`, `requires_live_check`.
- [x] Lokal geprüft: Chunk-Index ohne Inline-Content, SQLite-FTS ohne Content.
- [ ] `derived_index.json` bleibt Registry für abgeleitete Artefakte; `output_health.json` wird separates funktionales Prüfartefakt. `derived_index.json` kann auf `output_health.json` verweisen.

---

## 2) Leitentscheidung (Priorität)

- [x] **P1:** SQLite-FTS mit echtem Inhalt füllen (Status: abgeschlossen und durch Target-Proof bestätigt, 2026-05-03).
- [ ] **P2:** Range-Refs semantisch entwirren.
- [ ] **P3:** Output-Health erzwingen.
- [x] **P4:** Agent Reading Pack erzeugen (v1 abgeschlossen; siehe Arbeitspaket D).
- [ ] **P5:** Redaction/Profile trennen.
- [ ] **P6:** Architektur-Summary vertiefen.

---

## Arbeitspaket A — FTS aus Range-Refs rekonstruieren (Optimierungsgrad 0.88)

### Problem
- [x] Chunk-Index hat keinen Inline-`content`.
- [x] SQLite-Builder darf nicht blind `chunk["content"]` erwarten.

### Ziel
- [x] `sqlite_index` liefert echte Volltextsuche, auch ohne Inline-Content im Chunk-Index.

### Umsetzung
- [x] Dateien sind umgesetzt und mit Tests abgesichert:
  - [x] `merger/lenskit/retrieval/index_db.py`
  - [x] `merger/lenskit/core/range_resolver.py`
  - [x] `merger/lenskit/tests/test_retrieval_index.py`
  - [x] `merger/lenskit/tests/test_dump_retrieval.py`
- [x] Algorithmus ist vorhanden:
  - [x] `content = chunk.get("content")`
  - [x] Fallback ohne Inline-Content nutzt `content_range_ref` + Resolver.
  - [x] `resolved = resolve_range_ref(manifest_path, content_range_ref)`
  - [x] Extrahierter Text wird als FTS-Content übernommen.
  - [x] Hash wird über Byte-Slice geprüft (`content_sha256`).
  - [x] Persistenz in `chunks_fts(chunk_id, content, path_tokens)`.

### Target-Proof
- [x] Vorher/Nachher-Check erfüllt (Target-Proof am 2026-05-03):
  - [x] `count(*) > 0` und konsistent (`chunks_fts.count = 1`, `chunk_stats.chunks = 1`).
  - [x] `avg(length(content)) > 0` (`134.0`).
  - [x] `max(length(content)) > 0` (`134`).

### Stop-Kriterium
- [x] Query auf reinen Dateiinhalt liefert Treffer (`canonicalonlytokenproofx9q2` -> 1 Hit in `chunks_fts`).

### Target-Proof-Evidenz (2026-05-03)

- Ausgeführte Tests:
  - `python3 -m pytest merger/lenskit/tests/test_retrieval_index.py -q` -> `9 passed`
  - `python3 -m pytest merger/lenskit/tests/test_dump_retrieval.py -q` -> `2 passed`
  - `python3 -m pytest merger/lenskit/tests/test_output_health.py -q` -> `31 passed`
  - `python3 -m pytest merger/lenskit/tests/test_bundle_manifest_integration.py -q` -> `13 passed`
- Frischer Dual-Bundle-Laufzeitbeweis:
  - `chunk_stats`: `chunks=1`, `with_content=0`, `with_content_range_ref=1`
  - SQLite FTS: `count=1`, `avg(length(content))=134.0`, `max(length(content))=134`
  - FTS-Hit: Token `canonicalonlytokenproofx9q2` liefert `token_hit_count=1`
  - Hydration-Metadatum: `index_meta['ingest.fts_hydrated_from_range_ref'] = '1'`
- Hash-Mismatch-Härtung:
  - Abgedeckt durch `test_fts_content_hydration_hash_mismatch_raises` in `test_retrieval_index.py`.

### Risiko
- [ ] Speicher-/Leak-Risiko durch echten SQLite-Content mit Redaction-Profil absichern.

### Follow-up (nicht Teil von PR 1)
- [ ] **Resolver-Caching:** `resolve_range_ref()` lädt Manifest und JSON-Schema derzeit pro Chunk neu. Bei großen Indexläufen (>10k Chunks) empfiehlt sich ein Manifest- und Schema-Cache in `build_index()`. Implementierung folgt als separater PR (PR 4 o. ä.) ohne API-Änderung an `resolve_range_ref()` selbst.

---

## Arbeitspaket B — Range-Ref v2 (Optimierungsgrad 0.79)

### Problem
- [x] `start_line/end_line` in v1 potenziell missverständlich (Source vs. Artefaktachse).

### Ziel
- [ ] Zeilenachsen explizit trennen; Fehlzitate verhindern.

### Umsetzung
- [ ] Neue Schema-Datei: `merger/lenskit/contracts/range-ref.v2.schema.json`
- [ ] v2-Felder einführen:
  - [ ] `artifact_byte_start`, `artifact_byte_end`
  - [ ] `artifact_line_start`, `artifact_line_end`
  - [ ] `source_file_path`, `source_line_start`, `source_line_end`
  - [ ] `content_sha256`
- [ ] Kompatibilität:
  - [ ] v1 weiter lesbar.
  - [ ] v2 für neue Outputs bevorzugt.
  - [ ] query-result.v1 akzeptiert v1/v2.

### Tests
- [ ] `test_range_ref_v2_schema.py`
- [ ] `test_range_roundtrip_artifact_and_source_lines.py`
- [ ] `test_context_bundle_line_axes.py`

---

## Arbeitspaket C — output_health.json (Optimierungsgrad 0.84)

### Ziel
- [ ] Jeder Output erhält maschinenlesbaren Selbsttest (`<stem>.output_health.json`).

### Muss-Checks
- [ ] `manifest_present`
- [ ] `canonical_md_hash_ok`
- [ ] `chunk_index_hash_ok`
- [ ] `chunk_count`
- [ ] `sqlite_row_count`
- [ ] `fts_content_non_empty`
- [ ] `range_ref_resolution_ok`
- [ ] `sample_query_content_hit`
- [x] `agent_pack_present` — verdrahtet (`compute_output_health(agent_reading_pack_path=…, agent_reading_pack_expected=…)`); in v1 warnend (nicht blockierend). Blockierende Erzwingung folgt mit dem Post-hoc-Validator aus Arbeitspaket H.
- [ ] `redaction_status_explicit`
- [ ] `verdict: pass/fail`

### CI-Fail-Kriterien
- [ ] `fts_content_non_empty == false`
- [ ] `range_ref_resolution_ok == false`
- [ ] `sqlite_row_count != chunk_count`
- [ ] `canonical_md_hash_ok == false`

---

## Arbeitspaket D — Agent Reading Pack (Optimierungsgrad 0.73)

### Ziel
- [x] `<stem>.agent_reading_pack.md` erzeugen (kompakt, deterministisch, zitierfähig). Größe skaliert mit Repo; Top-Files sind auf 30 begrenzt, damit der Pack auch für große Repos im Zielkorridor bleibt.

### Inhalt (v1 umgesetzt)
- [x] Reading Policy (mit Authority-Rangordnung)
- [x] Artefaktrollen (maschinenlesbare Tabelle aus dem Bundle-Manifest)
- [x] Query-/Retrieval-Fluss (`HOW_TO_SEARCH` mit konkreten CLI-Befehlen: FTS-Query, `range get`, Citation-Map)
- [x] Output-Health-Summary (Verdict + Kernchecks aus `output_health.json`)
- [x] Top-30-Dateien mit Range-Refs (`TOP_FILES`: canonical Byte-/Zeilenspannen je Quelldatei)
  - **Migrationsnotiz (2026-05-21):** Heading `TOP_FILES → TOP_CHUNK_SPANS` (PR A1),
    da "TOP" Wichtigkeit impliziert; gemeint ist Chunk-Coverage, keine Wichtigkeit.
    Bis dahin gilt `TOP_FILES` als deprecated-aber-lesbar. Siehe
    `docs/blueprints/lenskit-anti-hallucination-output-architecture.md`.
- [x] Epistemische Leere: fehlende/erwartete Artefakte werden explizit ausgewiesen

### Inhalt (für v2 offen, im Pack als epistemische Leere markiert)
> **Guardrail:** Diese Punkte dürfen **keine** unqualifizierten Importance-/Purpose-/
> Architektur-Behauptungen erzeugen. Erlaubt sind nur heuristische Kandidaten
> (`selection_basis`, `confidence`, `not_evidence:true`) oder repo-deklarierte
> Aussagen aus `.lenskit/`. Keine freie Architektur-Prosa.
- [ ] Top-Level-Architektur (nur als Embed/Verdichtung von `architecture_summary`, diagnostisch)
- [ ] Entry-Point-**Kandidaten** (heuristisch, `not_evidence:true`)
- [ ] Contracts-Abschnitt (Rollen→Contract-Mapping; mechanisch, keine Wichtigkeitsaussage)
- [ ] Artifact-Lookup/Trace/Context-Lookup-Fluss
- [ ] Driftpunkte
- [ ] Claim-Evidence-Map (hängt an Arbeitspaket F)

### Governance
- [x] Klar markieren: Navigation, nicht Wahrheit (Sentinel-Kommentar + Banner).
- [x] Manifest-Rolle: `agent_reading_pack`, Authority: `navigation_index`, Canonicality: `derived` (role_only, `text/markdown`).

### Umsetzung (v1)
- [x] Producer: `merger/lenskit/core/agent_reading_pack.py` (pure Funktionen + IO-Adapter, atomic write, SHA-Verifikation der Wahrheitsanker `canonical_md`/`chunk_index`).
- [x] Rolle: `ArtifactRole.AGENT_READING_PACK` in `core/constants.py`; Schema-Enum + per-role `if/then` in `bundle-manifest.v1.schema.json`; `AUTHORITY_REGISTRY` in `merge.py`.
- [x] Pipeline-Emission: am Ende von `write_reports_v2` aus dem finalen Manifest; `MergeArtifacts.agent_reading_pack`.
- [x] CLI: `lenskit agent-pack produce <bundle_manifest> [--output] [--json]` (`cli/cmd_agent_pack.py`).
- [x] `output_health.agent_pack_present` ist verdrahtet (Parameter `agent_reading_pack_path`/`agent_reading_pack_expected`), in v1 nicht blockierend (warnend), für einen späteren Post-hoc-Validator (Arbeitspaket H).
- [x] Tests: `test_agent_reading_pack.py`, `test_cli_agent_pack.py`, Integration in `test_bundle_manifest_integration.py`, Health-Param in `test_output_health.py`.
- [x] Determinismus-Beleg: Standalone-Re-Run reproduziert den Pipeline-Pack byte-identisch (Self-Role wird übersprungen). Beleg: `docs/proofs/agent-reading-pack-producer-proof.md`.

---

## Arbeitspaket E — Output-Profile trennen (Optimierungsgrad 0.70)

> **Namens-Reconciliation (2026-05-21):** Es existieren zwei Profilnamensschemata
> (hier vs. `docs/blueprints/lenskit-artifact-output-control-plane.md` §7). **Kanonisch
> sind die control-plane-Namen** (`lean-readable`, `lean-evidence`, `agent-portable`,
> `local-search`, `debug-full`, `forensic-strict`). Die folgenden Namen bleiben als
> Verwendungsabsicht/Alias bestehen und mappen wie folgt:

### Ziel
- [ ] Profile nach Verwendungszweck trennen (kanonische Namen aus control-plane §7).

### Profile (Intent → kanonisches Profil)
- [ ] `max-private` → intern (`debug-full`/lokal), `agent_export=false`, redact_secrets=false.
- [ ] `agent-safe` → `agent-portable` **+ `redact_secrets=true` + `post_emit_health` required**.
- [ ] `public-review` → `lean-evidence`/`agent-portable`, `include_hidden=false`, redact_secrets=true.
- [ ] `ci-diagnostic` → `debug-full` (metadata+ranges-Fokus), agent_export=false.

### Tests
- [ ] `test_profile_agent_safe_redacts.py`
- [ ] `test_public_review_excludes_hidden.py`
- [ ] `test_output_health_redaction_status.py`

---

## Arbeitspaket F — Claim-Evidence-Map (Optimierungsgrad 0.76)

> **Epistemische Korrektur (2026-05-21):** Die ursprüngliche Formulierung
> ("supported / unsupported" pro Claim) ist zurückgezogen. Lenskit darf Belege
> **adressieren**, nicht **bewerten** — `supported/unsupported/true/false/proven`
> ist eine LLM-/Review-Aufgabe, kein Lenskit-Output. Auflösung des Widerspruchs siehe
> `docs/proofs/anti-hallucination-capability-audit.md` §2.6 und
> `docs/blueprints/lenskit-anti-hallucination-output-architecture.md` (PR F1–F3).

### Ziel
- [ ] `<stem>.claim_evidence_map.json` einführen — **nur Referenz, kein Verdikt**.
- [ ] Pro Claim maschinenlesbar ausweisen:
  - [ ] `claim → evidence_refs` (evidenztragende Artefakte + Range-Refs)
  - [ ] `relation: citation_attached`
  - [ ] `does_not_establish` (`truth`, `sufficiency`, `causality`, `completeness`)
  - [ ] `requires_live_check`
- [ ] **Verboten:** `supported`, `unsupported`, `true`, `false`, `proven`,
  `auto_extracted`.

---

## Arbeitspaket G — Architektur-Summary ausbauen (Optimierungsgrad 0.62)

### Ziel
- [ ] Summary von Statistik zu Flussdiagnose erweitern.

### Neue Abschnitte
- [ ] Entry Points
- [ ] Artifact Producers
- [ ] Artifact Consumers
- [ ] Query Pipeline
- [ ] Context Bundle Pipeline
- [ ] Runtime Cache Pipeline
- [ ] Contracts Coverage
- [ ] Unknown Cluster
- [ ] Drift Risks
- [ ] Guard Coverage

### Stop-Kriterium
- [ ] `unknown` nicht nur zählen, sondern clustern:
  - [ ] frontend-static
  - [ ] docs-normative
  - [ ] generated-artifacts
  - [ ] fixtures
  - [ ] legacy-tools

---

## Arbeitspaket H — CI-Gates für Output-Kohärenz (Optimierungsgrad 0.81)

### Ziel
- [ ] Neuer CI-Job: `output-health-validate`.

### Geplante CLI-/CI-Checks nach Implementierung:
- [ ] `python -m merger.lenskit.cli.main validate-output-health <stem>` *(geplant; neuer Command)*
- [ ] Aktueller Query-Vertrag: `python -m merger.lenskit.cli.main query --index <sqlite> --q "range_resolver" --emit json`
- [ ] Trefferprüfung für CI zunächst über Wrapper/Python/JQ aus dem JSON-Output ableiten; ein mögliches `--expect-hit` wäre ein zukünftig einzuführendes Assert-Flag, nicht aktueller CLI-Vertrag.
- [ ] Aktuelle Range-Auflösung: `python -m merger.lenskit.cli.main range get --manifest <bundle.manifest.json|dump_index.json> --ref <range_ref.json> --format json`
- [ ] Aktueller Stored-Artifact-Lookup: `python -m merger.lenskit.cli.main artifact --id <artifact-id> --artifact-type <query_trace|context_bundle|agent_query_session>`

Hinweis: `query --index/--q`, `range get --manifest/--ref` und `artifact --id/--artifact-type` spiegeln den aktuellen CLI-Vertrag. Neue Convenience-Flags wie `--expect-hit` oder neue Commands wie `validate-output-health` müssen separat implementiert und getestet werden, bevor sie in CI blockierend verwendet werden.

### Blockierend
- [ ] hash mismatch
- [ ] range_ref broken
- [ ] SQLite rows != chunks
- [ ] FTS content empty
- [ ] output_health missing

### Nicht blockierend
- [ ] agent_reading_pack too large
- [ ] unknown cluster above threshold
- [ ] diagnostic warnings

---

## Priorisierte PR-Reihenfolge

- [ ] **PR 1 — FTS Content Hydration**
  - [ ] `chunks_fts.content` Ø-Länge `> 0`
  - [ ] Sample-Content-Query mit Treffer
  - [ ] Hash-Verifikation erfolgreich
- [ ] **PR 2 — Output Health Artefakt**
- [ ] **PR 3 — Range-Ref v2**
- [x] **PR 4 — Agent Reading Pack** (v1: Kern-Pack — Reading Policy, Artefaktrollen, Output-Health-Summary, HOW_TO_SEARCH, Top-30 Range-Refs, epistemische Leere; Architektur-/Contracts-/Trace-Embeds offen für v2)
- [ ] **PR 5 — Safe Output Profiles**

---

## Diagnose-Gate vor Umsetzung

- [x] Gate durchgeführt (2026-05-03).
- [x] Ergebnis: kein Code-Patch in `index_db.py` nötig; Fokus verschiebt auf Folgepaket Range-Ref v2.
- [x] Belegkriterien im aktuellen Lauf:
  - [x] `chunks > 0`
  - [x] `with_content == 0`
  - [x] `with_content_range_ref == chunks`
  - [x] `avg(length(content)) > 0`
  - [x] `max(length(content)) > 0`

Reproduzierbares Befundskript (Pfade gelten für den Befundträger `lenskit-max-260502-1126_*`; für spätere Outputs `STEM` und Dateinamen entsprechend anpassen):

```bash
python - <<'PY'
import json, sqlite3, pathlib

# Befundträger dieser Blaupause: lenskit-max-260502-1126_*
# Für spätere Outputs STEM hier anpassen:
STEM = "lenskit-max-260502-1126"

chunk = pathlib.Path(f"{STEM}_merge.chunk_index.jsonl")
db = pathlib.Path(f"{STEM}_merge.chunk_index.index.sqlite")

n = has_content = has_ref = 0
for line in chunk.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    o = json.loads(line)
    n += 1
    has_content += bool(o.get("content"))
    has_ref += bool(o.get("content_range_ref"))

print({"chunks": n, "with_content": has_content, "with_content_range_ref": has_ref})

con = sqlite3.connect(db)
print(con.execute(
    "select count(*), avg(length(content)), max(length(content)) from chunks_fts"
).fetchone())
PY
```

Patch für PR 1 ist nur zulässig, wenn bestätigt:

- `chunks > 0`
- `with_content == 0`
- `with_content_range_ref == chunks`
- `avg(length(content)) == 0`
- `max(length(content)) == 0`

---

## Resonanz-/Kontrastprüfung

- [ ] Deutung A prüfen: contentloser Chunk-Index ist bewusst, Builder hydriert falsch.
- [ ] Deutung B prüfen: unvollständiger Umbau, E2E-Test fehlt.
- [ ] Synthese umsetzen: Hydration + echter Generator→Index→Query-Test.

---

## Risiko / Nutzen

### Nutzen
- [ ] echte Volltextsuche
- [ ] bessere Context Bundles
- [ ] weniger Truncation-Reibung
- [ ] sauberere Agentenantworten
- [ ] weniger Pseudo-Belege
- [ ] bessere CI-Diagnostik

### Risiken
- [ ] größere SQLite-Dateien
- [ ] sensiblere Cache-Inhalte
- [ ] mögliche v2-Kompatibilitätsbrüche
- [ ] höhere Artefaktkomplexität
- [ ] Missverständnis „Agent Pack = Wahrheit"

### Gegenmaßnahmen
- [ ] SQLite-Content nur profilgesteuert (Redaction).
- [ ] Range-Ref v1 behalten.
- [ ] Agent Pack als `navigation_index` markieren.
- [ ] Output Health blockierend machen.
- [ ] Claim-Evidence-Map gegen Überschluss nutzen.

---

## Für Dummies

- [x] `merge.md` ist das vollständige Buch.
- [x] Index/Cache sind Hilfsmittel (Inhaltsverzeichnis/Suche).
- [x] Problem heute: Suchindex hat leere Inhaltsfelder.
- [ ] Ziel: Suchindex lädt/verifiziert Text aus dem kanonischen Buch (Byte-Slice-basierte Hash-Prüfung) und sucht dann wirklich Inhalte.

---

## Epistemische Leere (offene Punkte)

- [ ] Exakte Branch-Diffs für präzise Patchzeilen fehlen.
- [ ] Query-API-Laufzeitlogs für Nutzungsfehleranalyse fehlen.
- [ ] Designabsicht hinter contentlosem Chunk-Index klären.
- [ ] Secret-Policy für private Dumps als Default definieren.

---

## Belegt / plausibel / spekulativ

- [x] **Belegt:** Rollenmodell, Reading Policy, Dump-Vollständigkeit, Range-Ref-v1, Query-Claim-Boundaries, Manifest-Autoritäten.
- [x] **Lokal geprüft:** Chunk-Index ohne Inline-Content, SQLite-FTS mit leerem Content.
- [ ] **Plausibel:** Leere FTS-Felder sind Hauptursache unzuverlässiger Agentenlesequalität.
- [ ] **Spekulativ:** Agent Reading Pack reduziert ChatGPT-File-Search-Probleme signifikant (Messung erforderlich).

---

## Essenz (1-Minute-Plan)

- [x] Hebel: SQLite-FTS aus `content_range_ref` hydratisieren.
- [x] Entscheidung: Erst Output-Beweisfähigkeit, dann neue Features.
- [x] Agent Reading Pack (PR 4) v1 umgesetzt: deterministisches Navigations-Einstiegsdokument für Agents.
- [ ] Nächste Aktion: Range-Ref v2 (Arbeitspaket B, docs-first) oder Agent-Pack v2 (Architektur-/Contracts-/Trace-Embeds).
