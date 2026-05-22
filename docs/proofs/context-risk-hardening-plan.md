# Context Risk Hardening Plan (Diagnose + Design)

Status: Diagnose-/Design-Notiz (diagnose-first, docs-first).
Scope: Phase-B-Härtung — Context Risk & Agent-facing Output Safety.
Revision: rev2 — Scope nach Review präzisiert auf **strikte Surface-Lokalität** (kein
globaler Epistemik-Layer, keine Cross-Artifact-Normalisierung, kein Shared-`$ref`/-
Registry, kein agent-safe-Verdikt, kein Scoring). Siehe §6a.
Diese Notiz beschreibt die **minimale additive** Härtung; die Phase-2-Umsetzung erfolgt
in diesem PR als kleiner B3-Schritt entlang dieser Notiz.

Beziehung zu bestehenden Docs (ersetzt nichts):
- Reihenfolge/Gates: `docs/roadmap/lenskit-master-roadmap.md`
- Reconciled Roadmap (PR B3): `docs/blueprints/lenskit-anti-hallucination-output-architecture.md`
- Befund/Falsifikation: `docs/proofs/anti-hallucination-capability-audit.md`
- Runtime-Boundary-Befund: `docs/proofs/runtime-artifact-metadata-gap-audit.md`
- Transfer-Boundary: `docs/proofs/vibe-lab-transfer-falsification.md`
- Profile/Evidence/Health: `docs/blueprints/lenskit-artifact-output-control-plane.md`

---

## 0. Auftrag in einem Satz

Agent-facing Output Safety **operationalisieren**, ohne eine neue Wahrheits- oder
Governance-Schicht zu bauen: Agenten sollen am **Bundle selbst** erkennen, dass es eine
Retrieval-/Projektions-Fläche ist (kein vollständiger Repo-Kontext, keine
Inhaltswahrheit) — als deterministische Risk-Hints, **nicht** als Wahrheitsampel.

Leitsatz: Lenskit erzeugt Bedingungen für bessere Interpretation. Lenskit entscheidet
nicht Wahrheit.

## 1. Methode

`git status`/`rg`/`test -f` plus vollständiges Lesen der Kern-Contracts, Producer,
Consumer und Tests im aktuellen Branch-Stand (`claude/nifty-albattani-QKFo0`,
Stand 2026-05-22). Kein Planpunkt wurde ohne Code-/Contract-/Test-Beleg übernommen.
Baseline der direkt betroffenen Testfläche grün (`133 passed`, siehe §9).

Leitbefund (wie im Auftrag erwartet): Der lokale Contract-/Teststand ist **weiter** als
der Bundle-Eindruck. Mehrere im Auftrag genannte „Zielideen" (Runtime-Observation-Warnung,
`cache_not_truth`, `non_canonical_surface`, `artifact_shape`) sind bereits **umgesetzt** —
am Lookup-/Envelope-Layer. Genau **eine** Fläche bleibt ungehärtet: das
`query-context-bundle.v1` selbst.

---

## 2. Belegter Ist-Zustand — was bereits existiert

### 2.1 Runtime-Lookup-Artefakte klassifizieren sich bereits (Gap geschlossen)

Der `runtime-artifact-metadata-gap-audit.md` (Branch `claude/audit-runtime-metadata`,
2026-05-01) beschrieb fehlende Klassifizierung. **Dieser Patch ist gelandet.** Die drei
Lookup-Contracts tragen heute alle Klassifizierungsfelder:

- `merger/lenskit/contracts/artifact-lookup.v1.schema.json:50,64-103` — `ArtifactPayload`
  required: `authority` (const `runtime_observation`), `canonicality` (const
  `observation`), `artifact_shape` (`raw|projected|wrapper`), `retention_policy`
  (const `unbounded_currently`), `lifecycle_status` (const `active`), `expires_at`,
  `claim_boundaries.does_not_prove`.
- `merger/lenskit/contracts/context-lookup.v1.schema.json:23-104` — `if status==ok then
  required [authority, canonicality, artifact_shape (const projected), retention_policy,
  lifecycle_status, expires_at, claim_boundaries]`.
- `merger/lenskit/contracts/trace-lookup.v1.schema.json:23-104` — analog, `artifact_shape`
  const `raw`.

→ **Konsequenz:** Focus B („Beobachtung ≠ Wahrheit", `runtime_observation_warning`,
`cache_not_truth`, `non_canonical_surface`, `artifact_shape`) ist am **Lookup-Layer
bereits operationalisiert**. Hier ist **nichts** neu zu bauen.

### 2.2 `query-result.v1` hat Claim-Boundaries

`merger/lenskit/contracts/query-result.v1.schema.json:251-298` definiert `claim_boundaries`
(`proves`, `does_not_prove`, `evidence_basis`, `requires_live_check`). Producer:
`merger/lenskit/retrieval/query_core.py:564-576` setzt sie deterministisch auf das
**Query-Result** (u. a. „Absence of a hit does not prove absence in the repository.",
„Ranking does not prove semantic importance.", „Snapshot query does not prove live
repository state.").

### 2.3 `agent-query-session.v2` hat Authority + Claim-Boundaries

`merger/lenskit/contracts/agent-query-session.v2.schema.json:57-61` — `session_authority`
const `agent_context_projection` („not canonical repository content"); `:91-110`
`claim_boundaries.{proves,does_not_prove}` (beide required, `minItems:1`). Producer:
`merger/lenskit/retrieval/session.py:127-149` (`build_agent_query_session_v2`) emittiert
sie deterministisch.

### 2.4 Agent Reading Pack ist begriffsgehärtet (PR A1, #688)

`TOP_FILES → TOP_CHUNK_SPANS` + maschinenlesbarer Governance-Block (`risk_class:
navigation`, `may_cite: false`, `must_resolve_to: role_specific_authority`,
`does_not_prove: [...]`). Beleg: Audit §2.2; Roadmap A1.

### 2.5 Per-Hit-`epistemics` im Bundle existieren

`merger/lenskit/retrieval/query_core.py:729-745` (`build_context_bundle`) setzt je Hit
einen `epistemics`-Block (`provenance_type`, `bundle_origin`, `resolver_status`,
`graph_status`, `semantic_status`, `federation_status`, `uncertainty`, `interpolation`);
Schema `query-context-bundle.v1.schema.json:81-140`. Strenge Grammatik-Tests:
`test_api_query.py:530-576`.

### Vokabular bereits im Repo (keine Erfindung nötig)

| Begriff | Bereits vorhanden in |
|---|---|
| `authority: runtime_observation` / `canonicality: observation` | artifact-/context-/trace-lookup, bundle-manifest |
| `artifact_shape` (raw/projected/wrapper) | artifact-/context-/trace-lookup |
| `claim_boundaries` / `does_not_prove` | query-result, agent-query-session, lookups |
| `session_authority: agent_context_projection` | agent-query-session.v2 |
| `risk_class` / `must_resolve_to` / `may_cite` | Agent-Reading-Pack-Governance (A1) |
| per-Hit `resolver_status` / `uncertainty` / `interpolation` | query-context-bundle.v1 |

→ Eine `context_risk`-Härtung **wiederverwendet** dieses Vokabular; sie führt keine neue
Meta-Sprache ein.

---

## 3. Die eine reale, repo-belegte Lücke

### 3.1 Das Bundle selbst trägt keine Top-Level-Risk-/Claim-Fläche

`merger/lenskit/contracts/query-context-bundle.v1.schema.json:6-12` —
`additionalProperties: false`, `required: [query, hits]`. **Kein** `context_risk`,
**keine** `claim_boundaries` auf Bundle-Ebene. Producer
`query_core.py:686-779` gibt `{"query": ..., "hits": [...]}` zurück — sonst nichts.
(Deckt sich mit Audit-Zeile 14 und Audit §4 Punkt 4: additive Erweiterbarkeit „noch
nicht durch einen Consumer-Test belegt".)

### 3.2 Konkreter, code-belegter Schaden: die Projektion verliert die Claim-Boundaries

`merger/lenskit/retrieval/output_projection.py:31-86`: Bei gesetztem `output_profile`
(z. B. `agent_minimal`, `ui_navigation`) und ohne Wrapper-Trigger gibt `project_output`
**das nackte Bundle** zurück (`return bundle`, Zeile 86). Die auf dem Query-Result
gesetzten `claim_boundaries` (§2.2) liegen in `res`, werden aber **nicht** ins Bundle
kopiert; der Wrapper-Pfad (`:60-84`) hängt nur `federation_trace`/`query_trace`/
`federation_conflicts`/`cross_repo_links`/`warnings` an — **nicht** `claim_boundaries`.

Ergebnis: Ein Agent, der mit `output_profile=agent_minimal` arbeitet, erhält
`hits[].resolved_code_snippet` **ohne jede** Bundle-Boundary. Nichts im Bundle sagt:
„dies ist eine Retrieval-Teilmenge", „Belege auflösen gegen `canonical_md`", „Abwesenheit
eines Treffers beweist keine Abwesenheit im Repo". Das ist genau die Stelle, an der ein
Agent Query-Hits mit Repo-Wahrheit verwechseln kann.

### 3.3 Warum die Per-Hit-`epistemics` das nicht abdecken

Die `epistemics` (§2.5) beschreiben **die Auflösung des einzelnen Treffers**
(resolver_status, interpolation). Sie sagen **nichts** über die **Vollständigkeit der
TrefferMENGE**: Das Bundle ist eine `results[:k]`-Scheibe
(`query_core.py:605-613`) — ein gefiltertes Top-k-Subset. „Was fehlt" ist per
Konstruktion nicht in den Hits sichtbar. Die fehlende Aussage ist eine **Mengen-/
Projektions-Eigenschaft**, kein Per-Hit-Attribut.

---

## 4. Fehlklassen-Abgleich (Auftrag „Zielideen" vs. Belege)

Nur dump-/repo-belegte Fehlklassen adressieren; nicht alles bauen.

| Zielidee (Auftrag) | Status | Beleg / Begründung | Aktion |
|---|---|---|---|
| `context_risk` (Bundle-Ebene) | **GAP** | §3.1, Audit #14/#4, B3 | **ADRESSIEREN** |
| `retrieval_based_subset` / `retrieval_incompleteness` | **GAP** | Bundle = `results[:k]`, `query_core.py:605-613` | **ADRESSIEREN** (Teil von `context_risk`) |
| `may_answer_from_this_directly:false` + Resolve-Map | **GAP** | §3.2 (Projektion verliert Boundaries) | **ADRESSIEREN** (Teil von `context_risk`) |
| stärkere `does_not_prove` (Bundle) | **GAP** | Bundle hat keine; Vokabular existiert §2.2 | **ADRESSIEREN** (in `context_risk`, Vokabular wiederverwenden) |
| `runtime_observation_warning` / `cache_not_truth` / `non_canonical_surface` | **DONE** | §2.1 (Lookup-Layer) | **NICHT bauen** (referenzieren) |
| `artifact_shape` | **DONE** | §2.1 | **NICHT bauen** |
| `coverage_hints` (numerischer Score) | **NICHT bauen** | Score-Risiko = „Verstehensampel"; verboten | **NICHT bauen** |
| `citation_resolution_gap` (Bundle-Aggregat aus per-Hit `resolver_status`) | **OPTIONAL/DEFER** | wäre deterministische Projektion bestehender per-Hit-Daten; erhöht aber Fläche | **NICHT in Erst-PR** (separat erwägen) |

---

## 5. Minimale additive Härtung (Design)

Entspricht exakt **PR B3** der reconciled Roadmap („Context Bundle Resolve Discipline").
Ein einziger neuer additiver Block in **einem** bestehenden Contract + dessen Producer +
Tests.

### 5.1 Schema (additiv, optional)

In `query-context-bundle.v1.schema.json` ein **optionales** Top-Level-`context_risk`
ergänzen (zu `properties`, **nicht** zu `required`):

```jsonc
"context_risk": {
  "type": "object",
  "additionalProperties": false,
  "required": [
    "retrieval_based_subset",
    "missing_relevant_context_possible",
    "may_answer_from_this_directly",
    "claims_resolve_to",
    "does_not_prove"
  ],
  "properties": {
    "retrieval_based_subset":          { "type": "boolean" },
    "missing_relevant_context_possible": { "type": "boolean" },
    "may_answer_from_this_directly":   { "type": "boolean" },
    "claims_resolve_to": {
      "type": "object",
      "additionalProperties": false,
      "required": ["content", "metadata", "schema", "runtime"],
      "properties": {
        "content":  { "const": "canonical_md" },
        "metadata": { "const": "bundle_manifest" },
        "schema":   { "const": "schema" },
        "runtime":  { "const": "query_trace" }
      }
    },
    "does_not_prove": { "type": "array", "items": { "type": "string" } }
  }
}
```

`additionalProperties: false` am Bundle bleibt erhalten; durch die Aufnahme in
`properties` validieren **sowohl** neue Bundles (mit Feld) **als auch** alte Bundles
(ohne Feld). Kein Pflichtfeld-Bruch.

Der `context_risk`-Block wird **inline** in genau diesem Contract definiert — **kein**
`$ref` auf ein geteiltes Definitions-Dokument, **keine** wiederverwendbare
`definitions/context_risk`-Abstraktion, die andere Contracts importieren könnten (siehe
§6a). `context_risk` ist die **lokale Risk-Hint-Fläche des Context-Bundles**:
Retrieval-/Projektions-/Incompleteness-Hinweise plus surface-lokale Resolve-Pointer und
surface-lokale `does_not_prove`-Aussagen — **kein** generalisierter Epistemik-Container.

### 5.2 Producer (deterministische Konstante)

In `build_context_bundle()` (`query_core.py:691-779`) am Bundle-Top-Level einen
**konstanten** Block emittieren (kein Inhalts-/Heuristik-Bezug → deterministisch):

```python
bundle["context_risk"] = {
    "retrieval_based_subset": True,
    "missing_relevant_context_possible": True,
    "may_answer_from_this_directly": False,
    "claims_resolve_to": {
        "content": "canonical_md",
        "metadata": "bundle_manifest",
        "schema": "schema",
        "runtime": "query_trace",
    },
    "does_not_prove": [
        "Absence of a hit does not prove absence in the repository.",
        "These retrieved snippets do not prove complete or sufficient context.",
        "Ranking does not prove semantic importance.",
        "This bundle is an agent context projection, not canonical repository content.",
    ],
}
```

**Surface-Lokalität (verbindlich, siehe §6a):** Die `does_not_prove`-Strings werden
**lokal in `build_context_bundle` inline** definiert. Sie dürfen Formulierungen aus
`query_core.py:564-576` / `session.py:139-149` **wörtlich wiederholen**, aber es entsteht
**keine** geteilte Konstante, **kein** exportiertes Modul-Symbol und **kein** Shared-`$ref`.
Eigentum bleibt bei dieser Surface. Gleiche Phrase ≠ geteiltes Vokabular.

### 5.3 Determinismus + Migration

- **Deterministisch:** Der Block ist eine Konstante; identisch bei jedem Lauf,
  unabhängig von Hits/Query. Bricht keine Determinismus-/Byte-Identität-Belege.
- **Projektions-überlebend:** `project_output` strippt nur **Hit-Felder**
  (`explain`/`graph_context`/`surrounding_context`, `output_projection.py:35-49`); ein
  Top-Level-`context_risk` bleibt in **allen** Profilen erhalten — genau dort, wo der
  Schaden aus §3.2 entsteht.
- **Lookup unberührt:** `context-lookup.v1` speichert das Bundle als
  `context_bundle` mit `additionalProperties: true` (`:41-46`) — das Zusatzfeld wird
  ohne Schema-Änderung akzeptiert. **Kein** Eingriff in die Lookup-Contracts nötig.
- **Alte Bundles:** bleiben gültig (Feld optional). Ein Consumer liest „Feld fehlt" =
  Legacy/unbekannt, nicht „kein Risk".

### 5.4 Optional-im-Schema, immer-emittiert

Die Roadmap-Zielgröße `runtime_outputs_with_context_risk: 100%` wird dadurch erfüllt,
dass der **Producer das Feld immer emittiert**, während das **Schema es optional** lässt
(Backcompat). Das Feld später `required` zu machen wäre ein **separater, breaking-naher**
Schritt (würde Alt-Bundles abweisen) → **defer**, konsistent mit „keine Breaking Schema
Changes ohne Migrationspfad".

---

## 6. Warum keine neue Governance nötig ist

- Das gesamte Vokabular existiert bereits (§2-Tabelle). `context_risk` **leitet ab/
  projiziert**, es bewertet nicht.
- Kein neues Top-Level-Artefakt, keine neue Schema-Datei, kein neuer CLI-Command, keine
  neue Control-Plane, keine Wahrheitsmaschine.
- Genau **ein** Contract wird additiv erweitert; sein Producer emittiert eine Konstante.
- Die bestehende Pre/Post-Health-Trennung, die Parity-Gate-Semantik und die
  Authority-Registry bleiben unangetastet.

## 6a. Surface-Lokalität — keine globale Epistemik-Schicht

Verbindliche Leitplanke (Review-Vorgabe): `context_risk`/`does_not_prove` bleiben
**artefakt-lokal, contract-lokal, additiv, nicht-autoritativ, nicht-aggregiert,
nicht-scorend**. Sie werden **nicht** zu einem globalen Epistemik-Layer, einer
Truth-Engine oder einer normierten Risk-Ontologie ausgebaut.

### 6a.1 `does_not_prove` je Surface — Eigentum bleibt lokal

Jede Surface besitzt ihre **eigene, inline definierte** Boundary. Es gibt **keine**
geteilte Definition, die mehrere Contracts importieren.

| Surface | Boundary-Feld (lokal definiert) | Eigentümer-Contract |
|---|---|---|
| Query Result | `claim_boundaries` (proves/does_not_prove/evidence_basis/requires_live_check) | `query-result.v1` |
| Agent Query Session | `session_authority` + `claim_boundaries` (Projektions-Semantik) | `agent-query-session.v2` |
| **Context Bundle** | **`context_risk` (Retrieval/Projektion/Incompleteness + Resolve-Pointer + lokale `does_not_prove`)** | **`query-context-bundle.v1`** ← diese Härtung |
| Runtime Lookup (artifact/context/trace) | `authority`/`canonicality`/`artifact_shape` + lokales `claim_boundaries.does_not_prove` | `artifact-/context-/trace-lookup.v1` |
| Output Health | lokale Integritäts-/Diagnose-Limits (verdict, checks) | `output-health.v1` |

### 6a.2 Warum `does_not_prove` surface-owned bleibt

Beweisgrenzen sind **kontextabhängig**: Was ein Query-Result nicht beweist, ist nicht
deckungsgleich mit dem, was ein Context-Bundle (gefiltertes Top-k-Subset) oder ein
Runtime-Trace (Beobachtung) nicht beweist. Eine generische, geteilte Liste würde diese
Unterschiede verwischen und müsste zwangsläufig in eine **Ontologie erlaubter Aussagen**
wachsen — genau der zu vermeidende Drift. Lokale Eigentümerschaft hält jede Aussage
**präzise an ihrer Surface** und vermeidet eine zweite Buchhaltung.

### 6a.3 Warum `context_risk` **kein** generalisiertes Register ist

`context_risk` ist die lokale Risk-Hint-Fläche **nur** des Context-Bundles. Es ist
**kein** Container für allgemeine Epistemik-Semantik, der nach und nach von einem
„Risk-Hint-Surface" zu einer versteckten globalen Interpretationsschicht aufstiege.
Konkrete technische Selbstbindung:
- **kein** `$ref` / keine `definitions/*`, die andere Contracts referenzieren;
- **keine** exportierte Producer-Konstante, die mehrere Producer teilen;
- **kein** Enum/Vokabular „erlaubter" `does_not_prove`-Strings;
- **keine** Aggregation über Artefakte; **keine** numerischen Scores.

Gleiche **Phrase** darf mehrfach auftauchen (z. B. „Absence of a hit does not prove
absence in the repository."); geteilt wird die **Phrase**, nie die **Definition** oder
die **Autorität**.

### 6a.4 Warum Symmetrie bewusst **partiell** bleibt

Es wird **kein** normiertes Top-Level-`claim_boundaries` nur um der Symmetrie willen
über alle Artefakte gezogen. Jede Surface formuliert ihre Grenzen in **ihrer eigenen
Form** (Query-Result: `claim_boundaries`; Session: `session_authority`+`claim_boundaries`;
Bundle: `context_risk`; Lookups: `claim_boundaries.does_not_prove`; Health: Integritäts-
Limits). Diese gewollte **Asymmetrie** ist die Schutzmaßnahme gegen „eine Ontologie für
alle epistemischen Grenzen".

### 6a.5 Migrations-/Kompatibilitätswirkung

- **Schema:** additiv, optional → alte Bundles **ohne** `context_risk` bleiben gültig;
  neue Bundles validieren ebenso (§5.1, §5.3). Kein Bruch von `additionalProperties:
  false`.
- **Andere Contracts:** **unverändert.** `context-lookup.v1` akzeptiert das Bundle bereits
  via `additionalProperties: true` (§5.3); query-result/session/lookups/health werden
  **nicht** angefasst.
- **Consumer:** lesen „Feld fehlt" als Legacy/unbekannt, nicht als „kein Risk". Per-Hit-
  `epistemics` bleiben unverändert.
- **Determinismus:** konstanter Block (§5.3) → keine Golden-/Byte-Identitäts-Regression.

### 6a.6 Expliziter Nicht-Ziel: keine agent-safe-Verdikt-Schicht

`context_risk` liefert **Hinweise**, **kein Urteil**. Es entsteht **kein**
`agent_safe`/`safe`/`unsafe`-Feld, kein `output_health=pass ⇒ agent-safe`-Schluss und
keine Verdikt-Aggregation. Agent-Safe bleibt ausschließlich Sache des separaten Gates
(A4/A5 `post_emit_health`), nicht dieser Surface.

## 7. Harte Nicht-Ziele (repo-spezifisch bekräftigt)

Nicht gebaut wird: automatische Claim-Wahrheitsbewertung; `supported/unsupported/true/
false/proven`; Truth-/Confidence-Score; globale Verstehens-/Risk-Ampel; numerische
`coverage`-Scores; neue globale Meta-Artefakte; zweites Generated-Artifact-Register;
Promotion-Readiness-Control-Plane; Agent-Command-Chain; `write_change`/`validate_change`;
generisches Handoff-System; Vibe-Lab-Replik. (Konsistent mit
`vibe-lab-transfer-falsification.md` und Anti-Hallucination-Blueprint §6.)

Zusätzlich (Review-rev2, siehe §6a): **kein** Cross-Artifact-Normalisierungs-Layer;
**kein** geteilter `$ref`/`definitions`-Block für `context_risk`/`does_not_prove`;
**kein** universelles Epistemik-Metadatenmodell; **keine** Cross-Artifact-Authority;
**keine** Aggregation; **keine** agent-safe-Verdikt-Schicht.

## 8. Blast Radius (unter Abbruchschwelle ~10 Dateien)

| Datei | Änderung |
|---|---|
| `merger/lenskit/contracts/query-context-bundle.v1.schema.json` | additiv optionales `context_risk` |
| `merger/lenskit/retrieval/query_core.py` | konstanten Block in `build_context_bundle` emittieren |
| `merger/lenskit/tests/test_context_bundle.py` | neue Tests (declares / backwards-compat / deterministisch / projektion-überlebt) |
| `docs/proofs/context-risk-hardening-plan.md` | diese Notiz (Phase 1) |
| (optional) `docs/contracts/contracts-matrix.md` / `docs/architecture/artifact-inventory.md` | Doku-Sync-Notiz |

→ 2 Code-/Contract-Dateien + 1 Testdatei + Doku. Keine globalen Umbenennungen.

## 9. Validierung (Plan; Baseline bereits grün)

- Baseline (Stand jetzt, `python3.11 -m pytest`): `test_context_bundle.py`,
  `test_agent_session_builder.py`, `test_agent_session_schema.py`, `test_context_lookup.py`,
  `test_trace_lookup.py`, `test_artifact_lookup.py`, `test_api_query.py` → **133 passed**.
- Neue Tests (entsprechen B3-Namen):
  - `test_context_bundle_declares_context_risk` — Producer emittiert Block mit exakter
    deterministischer Form + Resolve-Map.
  - `test_context_bundle_v1_backwards_compatible` — Bundle **ohne** `context_risk`
    validiert weiter (Beleg für additive Sicherheit; schließt Audit-§4-Punkt-4).
  - `test_context_risk_block_is_deterministic` — zwei Läufe → identischer Block.
  - `test_context_risk_survives_agent_minimal_projection` — Block überlebt
    `project_output(..., "agent_minimal")` (Beleg gegen §3.2-Schaden).
- Bestehende Schema-Validierung in `test_context_bundle.py:54-70` muss grün bleiben
  (Bundle **und** Query-Result gegen Schemas, via Registry).
- Pflicht vor Merge: vollständiges `pytest` grün; keine Determinismus-Regression.

## 10. Risiken / Unsicherheit

- **Hauptrisiko:** Scope-Drift zur „Universal-Risk-Engine". Gegenmittel: §7-Nicht-Ziele,
  ein konstanter Block, ein Contract.
- **Entschieden (rev2, Review):** `does_not_prove` lebt **surface-lokal** im
  `context_risk`-Block des Bundles, **inline** definiert, **nicht** als geteiltes/
  normiertes `claim_boundaries`. Keine Cross-Artifact-Symmetrie erzwungen (§6a.4).
- **Zu prüfender Einzelpunkt (rev2):** Die `claims_resolve_to`-Map ist ein
  **surface-lokaler Resolve-/Navigations-Pointer**, der die bestehende Reading-Policy
  (Invariante 10) wiederholt — **kein** neues Authority-Modell, **nicht** geteilt. Falls
  der Review selbst das als zu nah an einem Authority-Modell bewertet, ist es trivial
  entfernbar (die drei Booleans + lokales `does_not_prove` tragen den Kern allein).
- **Unsicherheit ~0,2:** Ob ein Consumer außerhalb des gelesenen Surfaces das Bundle
  strikt re-validiert; mitigiert durch Optional-Feld + Backcompat-Test.

## 11. Nächster Schritt

rev1 wurde reviewt; Scope auf strikte Surface-Lokalität präzisiert (rev2, §6a). Die
additive Phase-2-Umsetzung (§5, §8) ist in diesem PR als kleiner, gezielter B3-Schritt
entlang dieser Notiz enthalten: optionales `context_risk` im Bundle-Schema + konstanter,
inline definierter Block im Producer + die vier benannten Tests (§9). Keine anderen
Contracts werden angefasst.
