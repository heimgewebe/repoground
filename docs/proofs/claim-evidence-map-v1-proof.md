# Claim-Evidence-Map v1 Proof

> Erstellt am 2026-05-31.
> Scope: Lenskit F1a - referenz-only claim_evidence_map als Bundle-Artefakt.

## 1. Scope

Dieser Slice erzeugt ein neues abgeleitetes Artefakt `.claim_evidence_map.json`,
das deklarierte Claims aus `docs/doc-freshness-registry.yml` mit ihren
deklarierten Evidence-Refs verbindet.

## 2. Negative Finding (vorher)

Vor der Umsetzung war `claim_evidence_map` nicht produziert:

- `docs/doc-freshness-registry.yml` führte `agent-reading-pack-v2-claim-evidence-map` als `partial`.
- `merger/lenskit/core/agent_reading_pack.py` enthielt die Absent-Note
  `` `claim_evidence_map` is not yet produced ... ``.
- Im Bundle-Manifest gab es keine Rolle für die Claim-Evidence-Map.

## 3. Warum referenz-only, kein Verdict

Die Map ist ein Navigation-/Evidence-Index. Sie macht ausschließlich Aussagen
über Referenzen (Claim -> Evidence-Ref) und enthält keine Wahrheitsurteile.

## 4. Contract-Felder

Neuer Contract: `merger/lenskit/contracts/claim-evidence-map.v1.schema.json`

Kernfelder:

- `kind: lenskit.claim_evidence_map`
- `authority: navigation_index`
- `canonicality: derived`
- `risk_class: evidence_index`
- `source.registry_path`, `source.registry_sha256`, `source.generated_at`
- `does_not_establish`
- `claims[*].evidence_refs`
- `claims[*].relation = declared_evidence_ref`

## 5. Producer-Integration

Neuer Producer: `merger/lenskit/core/claim_evidence_map.py`

- `build_claim_evidence_map(...)` ist pure und testbar.
- `produce_claim_evidence_map(...)` lädt/validiert die Registry via bestehender
  `doc_freshness`-Logik, berechnet `registry_sha256` und schreibt deterministisch
  (`indent=2`, `sort_keys=True`, abschließendes Newline).
- `source.generated_at` ist deterministisch aus der Registry abgeleitet
  (`max(last_verified) + T00:00:00Z`) wenn nicht explizit übergeben.

## 6. Bundle-/Manifest-Integration

Die Merge-Pipeline erzeugt optional `.claim_evidence_map.json` aus der Registry
und trägt es als `claim_evidence_map_json` ins Bundle-Manifest ein.

Wenn die Registry vorhanden ist und der Producer fehlschlägt, bricht die
Pipeline mit Fehler ab (kein stilles Wegfallen nur per Log-Warnung).

Manifest-Metadaten:

- contract: `claim-evidence-map` / `v1`
- authority: `navigation_index`
- canonicality: `derived`
- regenerable: `true`
- staleness_sensitive: `true`

## 7. Agent-Reading-Pack-Verhalten

Wenn `claim_evidence_map_json` vorhanden und verifizierbar:

- Rolle erscheint im Pack.
- Summary wird angezeigt (`claims`, `evidence_refs`, `requires_live_check`).
- Klarstellung: navigation/evidence index, not truth.
- `does_not_establish` wird explizit genannt.

Wenn `claim_evidence_map_json` fehlt oder nicht verifizierbar:

- epistemische Leerstelle bleibt sichtbar.

## 8. Non-Changes

- Keine freie Claim-Extraktion.
- Keine LLM-Bewertung.
- Keine Truth-/Support-Verdicts.
- Keine Runtime-Annotation.
- Keine Änderung an `canonical_md`.
- Keine CI-Promotion zu `forensic_strict`.
- Kein Ersatz für Citation Map.

## 9. Verification Commands

- `python3 -m pytest -q merger/lenskit/tests/test_claim_evidence_map.py`
- `python3 -m pytest -q merger/lenskit/tests/test_agent_reading_pack.py merger/lenskit/tests/test_bundle_manifest_schema.py merger/lenskit/tests/test_bundle_manifest_integration.py merger/lenskit/tests/test_doc_freshness.py`
- `python3 -m merger.lenskit.cli.main doc-freshness inspect`
- `python3 -m merger.lenskit.cli.main doc-freshness update --write`
- `python3 -m ruff check --select=F401,F811,F841,E711,E712 --exclude='**/fixtures/**' merger/lenskit/core merger/lenskit/tests`
- `git diff --check`

## 10. Results

- `python -m pytest -q merger/lenskit/tests/test_claim_evidence_map.py merger/lenskit/tests/test_agent_reading_pack.py merger/lenskit/tests/test_bundle_manifest_schema.py merger/lenskit/tests/test_bundle_manifest_integration.py merger/lenskit/tests/test_doc_freshness.py`
  - Ergebnis: `157 passed`
- `python -m pytest -q merger/lenskit/tests/test_role_completeness.py`
  - Ergebnis: `1 passed`
- `python -m merger.lenskit.cli.main doc-freshness inspect`
  - Ergebnis: `PASS`
- `python -m merger.lenskit.cli.main doc-freshness update --write`
  - Ergebnis: generated view aktualisiert, Registry konsistent
- `python -m ruff check --select=F401,F811,F841,E711,E712 --exclude='**/fixtures/**' merger/lenskit/core merger/lenskit/tests`
  - Ergebnis: `All checks passed`
- `git diff --check`
  - Ergebnis: keine Whitespace-/Patch-Fehler

## 11. Next Slice

Nächster sinnvoller Slice ist die Nutzung der Claim-Evidence-Map in
forensischen Diagnose-Workflows (ohne Wahrheitsschicht), inklusive
Policy-Anbindung für `forensic_strict` sobald die Capability freigeschaltet wird.
