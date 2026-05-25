# C2.1 — Additive Authority / Risk-Class Self-Declaration (Proof)

**Status:** Implemented (Contract-only, additive). Proof for the lowest-risk slice of
the Governance-Track-C contract normalization.
**Datum:** 2026-05-24
**Beziehung:** setzt `docs/proofs/authority-contract-gap-audit.md` (C2a) §6.1/§6.2/§6.3
und §8 (Empfehlung C2.1) um.

---

## 1. Scope

C2.1 ergänzt **ausschließlich additive, optionale, const** Felder `authority` und
`risk_class` in genau drei bereits disclaimer-tragenden Diagnose-Contracts:

| Contract | Neues Feld `authority` | Neues Feld `risk_class` | Ebene |
| :--- | :--- | :--- | :--- |
| `post-emit-health.v1.schema.json` | const `diagnostic_signal` (optional) | const `diagnostic` (optional) | top-level |
| `agent-export-gate.v1.schema.json` | const `diagnostic_signal` (optional) | const `diagnostic` (optional) | top-level |
| `retrieval-eval.v1.schema.json` | const `diagnostic_signal` (optional) | const `diagnostic` (optional) | top-level |

Bei `retrieval-eval.v1` bleibt der bestehende verschachtelte
`miss_taxonomy`-Block (mit seinen eigenen `authority`/`risk_class`) **unverändert**.
Die neuen Felder sitzen auf dem Wurzelobjekt und tragen denselben const-Wert; sie sind
semantisch konsistent mit der Taxonomie und kollidieren nicht (verschiedene JSON-Scopes).

---

## 2. Explizite Eigenschaften dieses Patches

Dieser Patch ist bewusst minimal. Er enthält:

- **additive optional fields only** — keine bestehende Property entfernt oder geändert.
- **keine Pflichtfelder** — `authority`/`risk_class` sind in **keinem** der drei
  `required`-Arrays; Legacy-Objekte ohne die Felder bleiben valide.
- **keine Lockerung bestehender Constraints** — `additionalProperties: false` bleibt
  überall erhalten; alle bestehenden `required`/`const`/`contains`/`enum`-Constraints sind
  unverändert.
- **keine Lints** — keine neue CI-/Lint-Stufe (C3 bleibt offen).
- **keine Runtime-Annotation** — Producer (`core/post_emit_health.py`,
  `core/agent_export_gate.py`, `retrieval/eval_core.py`) und CLIs **unverändert**; sie
  emittieren die neuen Felder (noch) nicht. Das ist zulässig, weil die Felder optional sind.
- **keine Export-Gates** — kein Eingriff in Gate-Semantik; `authority`/`risk_class` gaten
  nichts und sind keine Wahrheits-/Safety-Verdicts.
- **keine Federation-Normierung** — Federation-Contracts unangetastet.
- **kein Eingriff in `output-health.v1`** — der konsumkritische Pre-Emit-Health-Contract
  (Parity-Gates, laufende `pre_emit_health`-Naming-Migration) wird **nicht** angefasst.
- **kein generisches `authority` neben `session_authority`** — `agent-query-session.v2`
  wird **nicht** verändert (Ambiguitätsverbot aus dem Audit §5.F/§7).
- **`miss_taxonomy` unverändert** — der vorhandene retrieval-eval Taxonomie-Block bleibt
  schema-semantisch unverändert; C2.1 ergänzt nur optionale top-level Felder im umgebenden `retrieval-eval.v1`-Schema.

Explizit **nicht** Teil dieses Patches (bleibt Folgearbeit):
`bundle-manifest.v1` (C2.2), `allowed_inference`/`forbidden_inference` (C2.3),
Lint-Regeln (C3/C2.4), Runtime-Annotation (C4), Export-Gate-Integration (C5),
neue Schemafamilien, neue Governance-Vokabulare.

---

## 3. Diagnose-Befund (vor dem Patch)

- `rg "authority|risk_class" merger/lenskit/contracts/` zeigte: top-level `authority`/
  `risk_class` fehlten in allen drei Contracts; `retrieval-eval.v1` trug die Felder nur im
  verschachtelten `miss_taxonomy`-Block.
- Producer-Scan (`grep -n "authority|risk_class"`): `post_emit_health.py` referenziert
  `authority` nur im Sub-Objekt `agent_pack.authority_declared`; `agent_export_gate.py` gar
  nicht; `eval_core.py:75-76` ausschließlich innerhalb `build_miss_taxonomy()`. → Kein
  Producer emittiert ein **top-level** `authority`/`risk_class`.
- Keine Testdatei assertet eine exakte Property-Key-Menge dieser Schemas.
  `test_role_completeness.py` prüft nur `bundle-manifest`/`range-ref`.
- Keine separaten JSON-Beispiel-/Fixture-Dateien für die drei Contracts; Instanzen werden
  in Tests vom Producer bzw. minimal konstruiert.
- Stop-Regeln (Audit-Anforderung) geprüft und **nicht** ausgelöst:
  1. Root-Felder brechen Validatoren/Fixtures? **Nein** (optional + `additionalProperties:false`
     + keine Key-Set-Asserts + Producer emittieren nichts).
  2. `authority`/`risk_class` doppeldeutig? **Nein** (keine Vorbelegung in post-emit/export-gate;
     in retrieval-eval identischer const-Wert wie nested).
  3. retrieval-eval top-level kollidiert mit `miss_taxonomy`? **Nein** (getrennte JSON-Scopes,
     identische Werte, semantisch konsistent).

→ **Entscheidung: SAFE_TO_PATCH.**

---

## 4. Geänderte Dateien

- `merger/lenskit/contracts/post-emit-health.v1.schema.json` (additive optionale Properties)
- `merger/lenskit/contracts/agent-export-gate.v1.schema.json` (additive optionale Properties)
- `merger/lenskit/contracts/retrieval-eval.v1.schema.json` (additive optionale top-level Properties)
- `merger/lenskit/tests/test_post_emit_health.py` (4 additive C2.1-Tests)
- `merger/lenskit/tests/test_agent_export_gate.py` (4 additive C2.1-Tests)
- `merger/lenskit/tests/test_retrieval_eval.py` (4 additive C2.1-Tests)
- `docs/proofs/authority-risk-class-c2-1-proof.md` (diese Datei)
- `docs/roadmap/lenskit-master-roadmap.md` (Governance-Track-C: C2.1 als umgesetzt markiert)

**Non-Changes (explizit unverändert):** alle Producer-/CLI-/Runtime-Module, `output-health.v1`,
`bundle-manifest.v1`, `diagnostics-lookup.v1`, `agent-query-session.v2`, alle Federation-Contracts,
der `miss_taxonomy`-Block in `retrieval-eval.v1`.

---

## 5. Test-Strategie

Pro Contract drei Eigenschaften additiv abgesichert:

1. **Legacy ohne neue Felder bleibt valide** — Objekt ohne `authority`/`risk_class` validiert.
2. **korrekte Werte valide** — `authority=diagnostic_signal`, `risk_class=diagnostic` validiert.
3. **falsche Werte invalid** — falsches `authority` bzw. `risk_class` löst `ValidationError` aus.

Bestehende Tests blieben unverändert; nur additive Testfunktionen kamen hinzu.

---

## 6. Testkommandos + Output

Baseline vor Patch:

```
$ python3 -m pytest merger/lenskit/tests/test_post_emit_health.py \
    merger/lenskit/tests/test_agent_export_gate.py \
    merger/lenskit/tests/test_retrieval_eval.py -q
74 passed, 1 warning
```

Nach Patch (drei Zielsuiten, +12 additive Tests):

```
$ python3 -m pytest merger/lenskit/tests/test_post_emit_health.py \
    merger/lenskit/tests/test_agent_export_gate.py \
    merger/lenskit/tests/test_retrieval_eval.py -q
86 passed, 1 warning
```

Regression (Consumer / verwandte Contracts):

```
$ python3 -m pytest merger/lenskit/tests/test_context_quality.py \
    merger/lenskit/tests/test_cli_context_quality.py \
    merger/lenskit/tests/test_cli_bundle_health.py \
    merger/lenskit/tests/test_bundle_manifest_integration.py \
    merger/lenskit/tests/test_role_completeness.py \
    merger/lenskit/tests/test_parity.py -q
75 passed, 1 warning
```

Lint:

```
$ ruff check --select=F401,F811 --exclude='**/fixtures/**' \
    merger/lenskit/tests/test_post_emit_health.py \
    merger/lenskit/tests/test_agent_export_gate.py \
    merger/lenskit/tests/test_retrieval_eval.py
All checks passed!
```

---

## 7. Verbleibende Risiken

- **Niedrig.** Die Felder sind optional und const; ohne Producer-Emission ist die einzige
  Wirkung, dass ein Objekt die Felder tragen *darf*. Falsche Werte werden abgewiesen.
- Producer emittieren die Felder noch nicht — eine spätere Runtime-Annotation (C4) ist
  bewusst getrennt und nicht Teil von C2.1.
- C2.2–C5 bleiben offen (siehe Roadmap); insbesondere `bundle-manifest.v1`-Normierung und
  `allowed_inference`/`forbidden_inference` sind ausdrücklich nicht enthalten.
