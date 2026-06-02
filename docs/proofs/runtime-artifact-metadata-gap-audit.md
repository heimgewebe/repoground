# Runtime Artifact Metadata Gap Audit

## These / Antithese / Synthese

**These:** Runtime-Artefakte (`query_trace`, `context_bundle`, `agent_query_session`) sind persistent im `QueryArtifactStore` abgelegt und über drei typsichere Lookup-APIs abrufbar. Die Infrastruktur ist vollständig.

**Antithese:** Maschinenlesbare Klassifizierung fehlt. Ein Consumer der Lookup-APIs kann ohne Quelltextlektüre nicht erkennen, dass diese Artefakte `runtime_observation / observation` sind, keinen GC-Schutz haben, und dass `context_bundle` in projizierter Form gespeichert wird. `claim_boundaries` fehlt in allen drei Lookup-Schemas — obwohl es in `query-result.v1.schema.json` und `retrieval-eval.v1.schema.json` bereits vorhanden ist und die `docs/retrieval/recipes.md` die Weitergabe explizit auf einen „separaten Folge-PR" verschoben hat.

**Synthese:** Der Patch ist additiv. Keine Breaking Changes. Keine neue Wahrheit, kein neues Schema-Top-Level-Dokument. Nur: was der Docstring weiß, soll auch die Maschine wissen.

---

## Belegter Ist-Zustand

### Repo-Stand

```
Branch: claude/audit-runtime-metadata-I02Qv
Stand:  2026-05-01
```

### Scan-Ergebnis (rg)

```
# Felder im Store (query_artifact_store.py:98-104)
"id": artifact_id
"artifact_type": artifact_type          # query_trace | context_bundle | agent_query_session
"data": data
"provenance": prov                      # source_query, timestamp, index_id, run_id
"created_at": now                       # ISO-8601 UTC

# Felder in artifact-lookup.v1.schema.json (ArtifactPayload)
provenance: {source_query, timestamp, index_id, run_id}
created_at
data

# Felder in trace-lookup.v1.schema.json (root)
status, id, trace, provenance, created_at, warnings

# Felder in context-lookup.v1.schema.json (root)
status, id, context_bundle, provenance, created_at, warnings
```

**Kein Treffer für** `runtime_observation | canonicality | observation | retention_policy | artifact_shape | claim_boundaries`
in `merger/lenskit/service/`, `merger/lenskit/contracts/artifact-lookup*`,
`merger/lenskit/contracts/trace-lookup*`, `merger/lenskit/contracts/context-lookup*`.

**Treffer vorhanden in:**
- `merger/lenskit/contracts/bundle-manifest.v1.schema.json` — `authority: runtime_observation`, `canonicality: observation` (Zeilen 137–158)
- `merger/lenskit/contracts/query-result.v1.schema.json` — `claim_boundaries` (Zeile 251)
- `merger/lenskit/contracts/retrieval-eval.v1.schema.json` — `claim_boundaries` (Zeile 260)
- `docs/retrieval/recipes.md` — explizite Aussage: „Die Weitergabe von claim_boundaries in Projektionen ist ein separater Folge-PR"
- `docs/architecture/artifact-inventory.md` — expliziter Hinweis: „Folgepunkte (außerhalb dieser PR-Stufe): Annotation für Runtime-Artefakte (Phase 4)"

---

## Tabelle: Ist-Zustand je Artefakttyp

| Feld | `query_trace` | `context_bundle` | `agent_query_session` | Schema-Ort | Store-Ort | Test-Ort |
|---|---|---|---|---|---|---|
| `artifact_type` | ✅ `query_trace` | ✅ `context_bundle` | ✅ `agent_query_session` | alle drei Lookup-Schemas | `query_artifact_store.py:99` | `test_artifact_lookup.py:127` |
| `created_at` | ✅ ISO-8601 | ✅ ISO-8601 | ✅ ISO-8601 | alle drei Lookup-Schemas | `query_artifact_store.py:103` | `test_trace_lookup.py:125` |
| `provenance.source_query` | ✅ | ✅ | ✅ | `artifact-lookup.v1` | `query_artifact_store.py:93` | `test_artifact_lookup.py:129` |
| `provenance.timestamp` | ✅ | ✅ | ✅ | `artifact-lookup.v1` | `query_artifact_store.py:93` | — |
| `provenance.index_id` | ✅ (optional) | ✅ (optional) | ✅ (optional) | `artifact-lookup.v1` | `app.py:728` | `test_artifact_lookup.py:234` |
| `provenance.run_id` | ✅ (optional) | ✅ (optional) | ✅ (optional) | `artifact-lookup.v1` | `query_artifact_store.py:94-95` | `test_artifact_lookup.py:136` |
| **`authority`** | ❌ absent | ❌ absent | ❌ absent | — | — | — |
| **`canonicality`** | ❌ absent | ❌ absent | ❌ absent | — | — | — |
| **`artifact_shape`** | ❌ absent | ❌ absent | ❌ absent | — | — | — |
| **`retention_policy`** | ❌ absent | ❌ absent | ❌ absent | — | — | — |
| **`claim_boundaries`** | ❌ absent | ❌ absent | ❌ absent | — | — | — |

---

## Kontrollfragen — Antworten

**Welche Metadaten speichert `query_artifact_store.py` tatsächlich?**
`id`, `artifact_type`, `data`, `provenance` (`source_query`, `timestamp`, `index_id`, `run_id`), `created_at`.

**Welche Metadaten geben die drei Lookup-Endpoints zurück?**
Dieselben. Keine Klassifizierungsfelder.

**Sind `created_at`, `provenance`, `run_id`, `index_id` konsistent?**
Ja — konsistent vorhanden und getestet.

**Gibt es bereits `authority=runtime_observation`?**
Nein — nur in `bundle-manifest.v1.schema.json` als erlaubter Wert, aber kein Runtime-Artefakt emittiert es.

**Gibt es bereits `canonicality=observation`?**
Nein — selbe Situation wie `authority`.

**Gibt es bereits `artifact_shape`?**
Nein. Der Store-Docstring dokumentiert: „No raw-vs-projected artifact distinction (context_bundle is stored in the projected API form, not the internal execute_query() form)." — aber dieses Wissen ist maschinenunlesbar.

**Gibt es bereits `retention_policy`?**
Nein. Der Store-Docstring dokumentiert: „No retention/GC policy: the store grows unbounded." — aber auch dies nur als Kommentar.

**Gibt es Runtime-Claim-Boundaries?**
Nein. `claim_boundaries` existiert in `query-result.v1.schema.json` (Zeile 251) und `retrieval-eval.v1.schema.json` (Zeile 260), aber nicht in den drei Artifact-Lookup-Schemas.

**Sind `query_trace`, `context_bundle`, `agent_query_session` gleichartig genug?**
Ja — alle drei werden durch `QueryArtifactStore.store()` mit identischer Schnittstelle abgelegt, alle teilen `authority=runtime_observation` und `canonicality=observation`. Sie unterscheiden sich nur in `artifact_shape`.

**Gibt es bestehende Tests für Type-Mismatch / fehlenden Store?**
Ja — `test_lookup_type_mismatch_returns_not_found`, `test_trace_lookup_type_mismatch_hides_non_trace_artifact`, `test_context_lookup_wrong_type_hides_non_bundle_artifact`. Kein Test prüft Klassifizierungsfelder.

---

## Entscheidung: Patch nötig

Die Lücke ist real und hat benannte Belege:

1. **`authority` / `canonicality`** — `artifact-inventory.md` benennt explizit „Folgepunkte: Annotation für Runtime-Artefakte (Phase 4)". Ein Consumer kann ohne Quelltextlektüre nicht erkennen, dass `query_trace` eine Beobachtung ist, keine kanonische Quelle.

2. **`artifact_shape`** — `query_artifact_store.py` Docstring: „No raw-vs-projected artifact distinction (context_bundle is stored in the projected API form, not the internal execute_query() form)." Dieses maschinenunlesbare Wissen betrifft jeden Consumer, der anhand des gespeicherten Artefakts rekonstruieren möchte, ob er die interne oder die API-Form erhält. Nur `artifact_shape: "projected"` macht dies eindeutig.

3. **`claim_boundaries`** — `docs/retrieval/recipes.md` (Zeile 151): „Die Weitergabe von `claim_boundaries` in Projektionen ist ein separater Folge-PR, damit das Context-Bundle-Schema nicht still erweitert wird." Dieser PR ist der angekündigte Folge-PR für die Lookup-Schemas.

4. **`retention_policy`** — Documenting a known limitation as machine-readable field: store docstring says "grows unbounded", but no consumer can read this from the API.

---

## Minimaler Patch

### Erlaubte Änderungen (alle additiv)

| Datei | Änderung |
|---|---|
| `merger/lenskit/service/query_artifact_store.py` | `_RUNTIME_ARTIFACT_METADATA` Konstante; Injektion in `store()` |
| `merger/lenskit/contracts/artifact-lookup.v1.schema.json` | Optionale Felder in `ArtifactPayload` |
| `merger/lenskit/contracts/trace-lookup.v1.schema.json` | Optionale Top-Level-Felder |
| `merger/lenskit/contracts/context-lookup.v1.schema.json` | Optionale Top-Level-Felder |
| `merger/lenskit/service/app.py` | Durchreichen der neuen Felder in allen drei Lookup-Endpoints |
| `merger/lenskit/tests/test_artifact_lookup.py` | Tests für Klassifizierungsfelder |
| `merger/lenskit/tests/test_trace_lookup.py` | Tests für Klassifizierungsfelder |
| `merger/lenskit/tests/test_context_lookup.py` | Tests für Klassifizierungsfelder |
| `docs/service-api.md` | Aktualisierung der Response-Beispiele |

### Nicht in diesem PR

- Retention/GC-Implementierung
- Agent Session v3
- Context-Bundle-Projection-Ausweitung
- neue Runtime-Governance-Datei
- MCP-/Tooling-Scope

---

## Artifact-Shape-Werte

| Artefakttyp | `artifact_shape` | Begründung |
|---|---|---|
| `query_trace` | `"raw"` | Internes `query_trace`-Feld aus `execute_query()`, unverändert |
| `context_bundle` | `"projected"` | Projizierte API-Form (nach Output-Profile-Filterung), nicht die interne Form |
| `agent_query_session` | `"wrapper"` | Wrapper-Objekt, aufgebaut aus dem projizierten Context Bundle |

---

## Risikoabschätzung

| Klasse | Bewertung |
|---|---|
| Nutzen | Hoch: Runtime-Artefakte sind maschinenlesbar als `runtime_observation / observation` klassifizierbar; `artifact_shape` macht den Projektion-Status explizit; `claim_boundaries` schließt den in `recipes.md` angekündigten Folge-PR |
| Risiko | Niedrig: alle Felder optional, kein Breaking Change, `additionalProperties: false` bleibt erhalten |
| Hauptfehler | Doppelmodellierung: `index_id` ist bereits in `provenance` — wird nicht nach oben dupliziert |
| Gegenmittel | Felder gehen in `ArtifactPayload` (artifact-lookup) bzw. als Top-Level-Felder (trace-/context-lookup) — konsistent mit der jeweiligen Schema-Struktur |

---

## Stop-Kriterium für Folge-PRs

Dieser PR ist vollständig, wenn:
1. Alle fünf Felder (`authority`, `canonicality`, `artifact_shape`, `retention_policy`, `claim_boundaries`) in Store-Einträgen vorhanden sind
2. Alle drei Lookup-Endpoints die Felder zurückgeben
3. Alle drei Lookup-Schemas die Felder als optional akzeptieren
4. Tests in `test_artifact_lookup.py`, `test_trace_lookup.py`, `test_context_lookup.py` grün laufen
5. Kein bestehender Test gebrochen ist

**Außerhalb dieses PR-Scopes bleiben:**
- Retention/GC-Implementierung (`retention_policy` dokumentiert nur den Ist-Zustand)
- Maschinelle Durchsetzung von `artifact_shape` beim Speichern
- `agent_query_session` Lookup-Endpoint (existiert nicht — nur `artifact_lookup` mit type=agent_query_session)

---

## Nachtrag (2026-06-02): Generator-Runtime-Provenance (eigenständiger Aspekt)

> Abgrenzung: Dieser Nachtrag betrifft **nicht** die oben behandelten Runtime-*Artefakte*
> (`query_trace`/`context_bundle`/`agent_query_session`), sondern die **Runtime des
> Generators**, der ein Bundle erzeugt.

**These:** Der Bundle-Manifest-Generator-Block trug nur `{name, version, config_sha256}`.

**Antithese:** Damit ist **Runtime-/Service-Drift nicht diagnostizierbar**. Lässt ein
Service-Dump still ein Artefakt (z. B. `claim_evidence_map_json`) weg, weil die laufende
Runtime ein veralteter Build ist, sieht man dem Dump nicht an, **welcher Build** ihn
erzeugte (Repo-Code vs. installierte Service-Runtime).

**Synthese:** `merger/lenskit/core/runtime_provenance.py` ergänzt einen optionalen
`generator.runtime`-Block (Contract-erweitert in `bundle-manifest.v1.schema.json`):

| Feld | Zweck |
| :--- | :--- |
| `module` | Dotted-Name des Kern-Generatormoduls (`merger.lenskit.core.merge`) |
| `module_file` | Absoluter Pfad der laufenden Datei (Repo-Checkout vs. site-packages) |
| `package_root` | Installations-Root des `merger`-Pakets |
| `python_executable` | Interpreter, der den Generator fuhr |
| `python_version` | Python-Version des Generators |
| `git_commit` | Commit des Generator-Working-Trees (oder `null`, z. B. Wheel-Install) |
| `git_dirty` | uncommittete Änderungen (oder `null`) |

**Drift-Diagnose:** `module_file`/`package_root`/`git_commit` zeigen unmittelbar, ob ein
Dump vom Repo-Code oder von einer abweichenden Service-Runtime stammt. **Redaction:** bei
`redact_secrets=True` werden die absoluten Pfadfelder auf `null` gesetzt; `git_commit`,
`module` und `python_version` bleiben als redaction-sichere Drift-Anker erhalten. Tests:
`test_runtime_provenance.py` (u. a.
`test_bundle_manifest_generator_runtime_provenance_present`,
`test_generator_runtime_provenance_redacts_absolute_paths_when_redaction_enabled`). Siehe
[real-dump-surface-self-check-proof.md](real-dump-surface-self-check-proof.md).
