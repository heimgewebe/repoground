# C2.2 — Bundle-Manifest v1 Authority / Risk-Class Normalization (Proof)

**Status:** Implemented (Contract-only, additive). Proof for the manifest-tracing slice
of the Governance-Track-C contract normalization.
**Datum:** 2026-05-25
**Beziehung:** setzt `docs/proofs/authority-contract-gap-audit.md` (C2a) §6.5 und §8
(Empfehlung C2.2) um; baut auf C1 (`docs/blueprints/lenskit-authority-risk-matrix.md`)
und C2.1 (`docs/proofs/authority-risk-class-c2-1-proof.md`) auf.

---

## 1. Scope

C2.2 normiert **ausschließlich** das Contract-File
`merger/lenskit/contracts/bundle-manifest.v1.schema.json`:

1. **Optionales, per-Rolle wertbeschränktes `risk_class`-Feld** (additive Property,
   const pro Rolle), abgeleitet aus der bereits vorhandenen per-Rolle-`authority`.
2. **Neuer per-Rolle-`authority`/`canonicality`/`risk_class`-Zweig für die Rolle
   `output_health`**, die bisher als einzige manifest-getragene Diagnose-Rolle **keinen**
   `allOf`-Constraint hatte (Beleg: Gap-Audit §3, Tabellenzeile `bundle-manifest.v1`:
   „Rolle `output_health` hat **keinen** per-role authority-`allOf`-Zweig").

### Authority → risk_class Mapping (C1-belegt)

| authority (vorhanden) | risk_class (C1 §2.1 / §3) | C1-Beleg |
| :--- | :--- | :--- |
| `canonical_content` | `content` | §3.1 risk_class `content` |
| `navigation_index` | `navigation` | §3.3 risk_class `navigation` |
| `runtime_cache` | `cache` | §3.5 risk_class `cache` |
| `diagnostic_signal` | `diagnostic` | §3.2 risk_class `diagnostic` |
| `retrieval_index` | **(kein const — STOP, siehe §4)** | keine §3-Klasse, kein dokumentierter risk_class |

`runtime_observation` (→ `observation`) und `agent_context_projection` (→ `derived`)
kommen in **keiner** aktuellen manifest-getragenen Rolle vor; sie bleiben unberührt.

### Per-Rolle-Ergebnis im Manifest

| Rolle | authority | canonicality | risk_class (neu) |
| :--- | :--- | :--- | :--- |
| `canonical_md` | canonical_content | content_source | **content** |
| `index_sidecar_json` | navigation_index | index_only | **navigation** |
| `dump_index_json` | navigation_index | index_only | **navigation** |
| `derived_manifest_json` | navigation_index | derived | **navigation** |
| `citation_map_jsonl` | navigation_index | derived | **navigation** |
| `agent_reading_pack` | navigation_index | derived | **navigation** |
| `sqlite_index` | runtime_cache | cache | **cache** |
| `architecture_summary` | diagnostic_signal | diagnostic | **diagnostic** |
| `retrieval_eval_json` | diagnostic_signal | diagnostic | **diagnostic** |
| `delta_json` | diagnostic_signal | diagnostic | **diagnostic** |
| `output_health` | **diagnostic_signal (neu)** | **diagnostic (neu)** | **diagnostic (neu)** |
| `chunk_index_jsonl` | retrieval_index | derived | **— (STOP)** |
| `graph_index_json` | retrieval_index | derived | **— (STOP)** |

---

## 2. Explizite Eigenschaften dieses Patches

- **additive optional fields only** — keine bestehende Property entfernt oder geändert.
- **keine Pflichtfelder** — `risk_class` ist in **keinem** `required`-Array; auch der
  neue `output_health`-Zweig fügt **keine** `required`-Einträge hinzu. Bei
  `citation_map_jsonl`/`agent_reading_pack` wird `risk_class` nur additiv in
  `then.properties` aufgenommen, **nicht** in deren bestehende `required`-Listen.
- **additionalProperties nicht gelockert** — `additionalProperties: false` bleibt auf
  Manifest-Ebene und auf Artefakt-Item-Ebene erhalten.
- **per-Rolle const nur bei Anwesenheit** — wie die bestehenden `authority`/`canonicality`-
  Zweige greift `risk_class.const` nur, wenn das Feld **vorhanden** ist. Legacy-Bundles
  ohne `risk_class` validieren unverändert.
- **keine Runtime-/Producer-Emission** — `ARTIFACT_AUTHORITY_REGISTRY` in
  `merger/lenskit/core/merge.py` und alle CLIs bleiben **unverändert**; es wird **kein**
  `risk_class` in erzeugte Manifeste geschrieben. Der `output_health`-Zweig deckt sich mit
  der **bereits** emittierten `authority`/`canonicality`
  (`merge.py:267-272`: `diagnostic_signal`/`diagnostic`).
- **kein Lint** — keine neue CI-/Lint-Stufe (C2.4/C3 bleiben offen).
- **kein Export-Gate** — keine Gate-Semantik; `risk_class` gatet nichts.
- **kein Eingriff in `output-health.v1.schema.json`** — der konsumkritische
  Pre-Emit-Health-Contract (Parity-Gates, laufende `pre_emit_health`-Naming-Migration)
  wird **nicht** angefasst. C2.2 berührt ausschließlich die Manifest-**Rolle**
  `output_health`, nicht den gleichnamigen Contract.

Explizit **nicht** Teil dieses Patches (bleibt Folgearbeit): `allowed_inference`/
`forbidden_inference` (C2.3), Lint-Regeln (C2.4/C3), Runtime-Annotation (C4),
Export-Gate-Integration (C5), Federation-Contracts, neue Major-Manifest-Version mit
Pflichtfeldern.

---

## 3. Diagnose-Befund (vor dem Patch) — SAFE_TO_PATCH

1. **Per-Rolle-Mechanismus:** `bundle-manifest.v1` setzt authority/canonicality über
   `allOf`-`if role==X then properties.{authority,canonicality}.const`-Zweige; `authority`
   und `canonicality` sind optionale top-level Enums (const greift nur bei Anwesenheit).
2. **`output_health` ohne authority-Zweig:** Bestätigt — kein `const: "output_health"`-
   Zweig im `allOf`. Die Rolle ist im `role`-Enum registriert, aber unbeschränkt.
   Der Producer emittiert für sie bereits `authority: diagnostic_signal` /
   `canonicality: diagnostic` (`merge.py:267-272`), ohne dass das Schema es erzwingt.
3. **`risk_class` fehlt im Manifest:** Bestätigt — keine `risk_class`-Property im Schema;
   kein Producer/CLI emittiert `risk_class` in ein Bundle-Manifest (Producer-Scan:
   `risk_class` nur in `context_quality.py`, `agent_reading_pack.py` (Pack-Body-Text) und
   `cmd_context_quality.py` — **nicht** in `merge.py`/`AUTHORITY_REGISTRY`).
4. **Tests mit exakter Key-Menge / alte Fixtures:** Keine.
   - `test_role_completeness.py` prüft nur die **Rollen-Enum**-Synchronität, **keine**
     Property-Schlüsselmenge.
   - `test_bundle_manifest_integration.py` erzeugt Manifeste dynamisch und validiert sie
     per `jsonschema.validate`; es assertiert konkrete authority/canonicality-Werte, aber
     **keine** exakte Property-Key-Menge und **keine** `risk_class`-Abwesenheit.
   - Keine statischen JSON-Manifest-Fixtures mit fixierter Property-Menge.

**Stop-Regeln geprüft:**

| Stop-Regel | Ergebnis |
| :--- | :--- |
| risk_class würde alte Bundles invalidieren | **Nicht ausgelöst** — optional, const nur bei Anwesenheit, Producer emittiert nichts. |
| retrieval_index risk_class nicht eindeutig belegbar | **AUSGELÖST (scoped)** — siehe §4; risk_class für `chunk_index_jsonl`/`graph_index_json` wird **bewusst weggelassen**. |
| output_health-Canonicality folgt nicht sicher aus Inventory/Manifest | **Nicht ausgelöst** — `diagnostic` ist (a) bereits vom Producer emittiert, (b) C1 §3.2 listet `output_health` als `diagnostic_signal`, (c) Inventory §6: `diagnostic_signal`/`diagnostic` = „warnt, beweist nicht". |
| Tests mit exakter Property-Menge | **Nicht ausgelöst** — keine vorhanden. |

→ **Entscheidung: SAFE_TO_PATCH** (mit bewusster Auslassung von `retrieval_index`-risk_class).

---

## 4. STOP-Begründung: `retrieval_index` — aktives Schema-Verbot statt offener Tür

Die Rollen `chunk_index_jsonl` und `graph_index_json` tragen `authority: retrieval_index`,
`canonicality: derived`. Für `retrieval_index` gilt:

- **C1 §3 enthält keine eigene Authority-Klassensektion** für `retrieval_index` (die §3-
  Klassen sind `canonical_content`, `diagnostic_signal`, `navigation_index`,
  `derived_projection` (konzeptionell), `cache`, `runtime_observation`, `agent_generated`,
  `external_unverified`). Es gibt damit **keinen** dokumentierten risk_class-Wert.
- **Das risk_class-Vokabular** (`content`, `navigation`, `diagnostic`, `cache`,
  `observation`, `derived`, `external`; C1 §2.1) ordnet `retrieval_index` **nicht** zu.
- **Inventory §6** beschreibt `retrieval_index / derived` als „die Quelle für Retrieval,
  abgeleitet aus dem Inhalt" — das belegt die **canonicality** (`derived`), aber **keinen**
  risk_class.
- `derived` als risk_class stammt in C1 aus der **konzeptionellen** Klasse
  `derived_projection` (§3.4), die ausdrücklich **keine** bestehenden Artefakte
  umklassifiziert (chunk_index bleibt `retrieval_index`). Eine Ableitung `retrieval_index →
  derived` wäre daher **nicht eindeutig belegt**.

**Konsequenz:** Da `risk_class` als optionales globales Enum eingeführt wird, würde ein
blosses Weglassen des per-Rolle-Constraints diese Rollen für **jeden** Enum-Wert öffnen —
einschließlich semantisch gefährlicher Aufwertungen wie `content` oder `diagnostic`. Das
wäre genau die Art stiller Authority-Eskalation, die C1 §4 P4 und §3.9 verhindern soll.

Daher wird für `chunk_index_jsonl` und `graph_index_json` im `then`-Zweig **aktiv
verboten**, dass `risk_class` vorhanden ist:

```json
"not": { "required": ["risk_class"] }
```

Das bedeutet: Abwesenheit von `risk_class` validiert; jeder Wert aus dem Enum — inklusive
`derived` und `navigation` — wird abgewiesen. Das Schema ist damit ein echter Sperrriegel,
kein Hinweisschild. Test `test_c22_retrieval_index_roles_reject_any_risk_class_until_c1_defines_it`
belegt, dass alle 7 Enum-Werte bei diesen Rollen eine `ValidationError` auslösen.

Die Lücke kann nach expliziter C1-Erweiterung für `retrieval_index` in einer späteren PR
durch Ersetzen des `not`-Zweigs durch einen `const`-Zweig geschlossen werden.

---

## 5. Geänderte Dateien

- `merger/lenskit/contracts/bundle-manifest.v1.schema.json`
  - additive optionale `risk_class`-Property (Enum: vollständiges C1-Vokabular).
  - `risk_class`-const in den 10 nicht-`retrieval_index`-Rollenzweigen
    (1×content, 5×navigation, 1×cache, 3×diagnostic).
  - neuer `allOf`-Zweig für Rolle `output_health`
    (`diagnostic_signal`/`diagnostic`/`diagnostic`).
- `merger/lenskit/tests/test_bundle_manifest_integration.py` (6 additive C2.2-Tests).
- `docs/proofs/authority-risk-class-c2-2-manifest-proof.md` (diese Datei).
- `docs/roadmap/lenskit-master-roadmap.md` (Governance-Track-C: C2.2 als umgesetzt markiert).

**Non-Changes (explizit unverändert):** alle Producer-/CLI-/Runtime-Module inkl.
`merge.py`/`ARTIFACT_AUTHORITY_REGISTRY`, `output-health.v1.schema.json`, alle anderen
Contracts, `agent-query-session.v2`, Federation-Contracts; keine Lints, keine Export-Gates.

---

## 6. Test-Strategie

Sechs additive Tests in `test_bundle_manifest_integration.py`:

1. `test_c22_legacy_manifest_without_risk_class_stays_valid` — Backcompat.
2. `test_c22_correct_per_role_risk_class_is_valid` — korrekte Kombinationen.
3. `test_c22_wrong_per_role_risk_class_is_invalid` — falsche risk_class pro Rolle abgewiesen.
4. `test_c22_output_health_correct_authority_canonicality_is_valid` — neuer Zweig positiv.
5. `test_c22_output_health_wrong_authority_is_invalid` — neuer Zweig negativ.
6. `test_c22_retrieval_index_roles_reject_any_risk_class_until_c1_defines_it` — STOP-Beleg: alle 7 Enum-Werte werden abgewiesen; Abwesenheit validiert.

Bestehende Tests blieben unverändert; nur additive Testfunktionen kamen hinzu.

---

## 7. Testkommandos + Output

Schema-Wohlgeformtheit (Draft-7):

```
$ python3 -c "import json,jsonschema; from pathlib import Path; \
  s=json.loads(Path('merger/lenskit/contracts/bundle-manifest.v1.schema.json').read_text()); \
  jsonschema.Draft7Validator.check_schema(s); print('draft-7 OK')"
draft-7 OK
```

Zielsuite (Manifest + Rollen-Completeness, inkl. 6 neuer C2.2-Tests):

```
$ python3 -m pytest merger/lenskit/tests/test_bundle_manifest_integration.py \
    merger/lenskit/tests/test_role_completeness.py -q
30 passed, 1 warning
```

Regression (Consumer / verwandte Bundle-/Health-/Parity-Suiten):

```
$ python3 -m pytest \
    merger/lenskit/tests/test_bundle_manifest_integration.py \
    merger/lenskit/tests/test_role_completeness.py \
    merger/lenskit/tests/test_output_health.py \
    merger/lenskit/tests/test_post_emit_health.py \
    merger/lenskit/tests/test_cli_bundle_health.py \
    merger/lenskit/tests/test_context_quality.py \
    merger/lenskit/tests/test_parity.py \
    merger/lenskit/tests/test_parity_state.py \
    merger/lenskit/tests/test_agent_reading_pack.py -q
188 passed, 1 warning
```

Lint:

```
$ ruff check --select=F401,F811 --exclude='**/fixtures/**' \
    merger/lenskit/tests/test_bundle_manifest_integration.py
All checks passed!
```

---

## 8. Verbleibende Risiken

- **Niedrig.** `risk_class` ist optional und const; ohne Producer-Emission ist die einzige
  Wirkung, dass ein Manifest das Feld tragen *darf*. Falsche Werte werden pro Rolle
  abgewiesen.
- Der `output_health`-Zweig deckt sich exakt mit der bereits vom Producer emittierten
  authority/canonicality; reale Bundles validieren unverändert weiter.
- **Aktiver Sperrriegel:** `retrieval_index`-Rollen verbieten `risk_class` explizit per
  `not: {required: ["risk_class"]}` (§4). Freischaltung erst nach C1-Normierung des
  risk_class für `retrieval_index`; dann Ersetzen des `not`-Zweigs durch `const`.
- C2.3–C5 bleiben offen (siehe Roadmap); insbesondere `allowed_inference`/
  `forbidden_inference`, Lint und Export-Gate sind ausdrücklich nicht enthalten.
- Eine Pflicht-Anhebung von `risk_class`/`authority` im Manifest bleibt einer **neuen
  Major-Manifest-Version** vorbehalten (würde sonst Altbundles brechen).
