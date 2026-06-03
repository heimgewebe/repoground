# Claim-Evidence-Map v1 Proof

> Erstellt am 2026-05-31.
> Scope: Lenskit F1a + F1b/F2 - referenz-only claim_evidence_map als Bundle-Artefakt mit Surface-/Preflight-Diagnostik.

## 1. Scope

Dieser Slice erzeugt ein neues abgeleitetes Artefakt `.claim_evidence_map.json`,
das deklarierte Claims aus `docs/doc-freshness-registry.yml` mit ihren
deklarierten Evidence-Refs verbindet.

## 2. Negative Finding (historisch)

Vor der Umsetzung war `claim_evidence_map` nicht produziert:

- `docs/doc-freshness-registry.yml` führte `agent-reading-pack-v2-claim-evidence-map` als `partial`.
- `merger/lenskit/core/agent_reading_pack.py` signalisierte die epistemische
  Leerstelle für fehlende Claim-Map.
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

**Registry-Pfad-Auflösung (Surface-Parity-Fix, 2026-06-01):**
Der Registry-Pfad wird aus dem **realen Quellrepo-Kontext** abgeleitet, nicht
aus dem Package-Installationspfad. Für Single-Repo-Bundles:

```
<repo_summaries[0]["root"]> / "docs" / "doc-freshness-registry.yml"
```

Das Validierungsschema (`doc-freshness-registry.v1.schema.json`) ist Teil des
lenskit-Pakets und wird aus dem Package-Pfad (`claim_evidence_map.py`) abgeleitet,
nicht aus dem gescannten Repo.

Multi-Repo-Aggregation ist explizit out of scope: bei mehreren Repos in einem
Bundle wird kein Claim-Evidence-Map erzeugt; die epistemische Leerstelle bleibt
sichtbar.

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

## 8. Post-Emit-/Forensic-Diagnostik (F1b/F2)

- `post_emit_health` prüft `claim_evidence_map_json` explizit auf
  Presence/Hash/Schema (`claim_evidence_map_present`,
  `claim_evidence_map_hash_ok`, `claim_evidence_map_schema_valid`).
- Fehlende Claim-Map bleibt im normalen Post-Emit-Flow sichtbar als
  diagnostischer Skip-Hinweis; `forensic_strict` wird dadurch nicht still
  hochgestuft.
- Neuer Governance-CLI-Check:
  `python3 -m merger.lenskit.cli.main governance forensic-preflight --manifest <bundle.manifest.json>`
  liefert `pass|warn|blocked|fail` für `forensic_strict`-Voraussetzungen.
- Preflight `pass` bedeutet ausschließlich: alle formalen Voraussetzungen sind
  erfüllt; es ist kein Wahrheitsurteil über Claims.

## 9. Non-Changes

- Keine freie Claim-Extraktion.
- Keine LLM-Bewertung.
- Keine Truth-/Support-Verdicts.
- Keine Runtime-Annotation.
- Keine Änderung an `canonical_md`.
- Keine CI-Promotion zu `forensic_strict`.
- Kein Ersatz für Citation Map.

## 10. Verification Commands

- `python3 -m pytest -q merger/lenskit/tests/test_claim_evidence_map.py`
- `python3 -m pytest -q merger/lenskit/tests/test_agent_reading_pack.py merger/lenskit/tests/test_bundle_manifest_schema.py merger/lenskit/tests/test_bundle_manifest_integration.py merger/lenskit/tests/test_post_emit_health.py merger/lenskit/tests/test_forensic_preflight.py merger/lenskit/tests/test_doc_freshness.py`
- `python3 -m merger.lenskit.cli.main governance forensic-preflight --manifest <bundle.manifest.json>`
- `python3 -m merger.lenskit.cli.main doc-freshness inspect`
- `python3 -m merger.lenskit.cli.main doc-freshness update --write`
- `python3 -m ruff check --select=F401,F811,F841,E711,E712 --exclude='**/fixtures/**' merger/lenskit/core merger/lenskit/tests`
- `git diff --check`

## 11. Results

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

## 12. Surface-Parity-Fix (2026-06-01)

**Diagnose:**
Producer und Contract existierten bereits. Aber der Registry-Pfad in
`merge.py` verwendete `Path(__file__).resolve().parents[3]`, was nur
beim Ausführen aus dem lenskit-Source-Tree funktioniert. Bei installierten
Paketen oder beim Scannen anderer Repos zeigte der Pfad auf das falsche
`docs/`-Verzeichnis oder fand gar keine Registry.

**Fix:**
- `merge.py`: Registry-Pfad wird aus `repo_summaries[0]["root"]` abgeleitet
  (Single-Repo-Bundles). Multi-Repo: explizit out of scope, Leerstelle
  bleibt sichtbar.
- `claim_evidence_map.py`: Validierungsschema wird aus dem Package-Pfad
  (`Path(__file__).parent.parent / "contracts"`) abgeleitet, nicht aus
  dem gescannten Repo.

**Beweis (Tests):**
- `test_claim_evidence_map_surface_single_repo_with_registry`: Single-Repo
  mit Registry → `claim_evidence_map_json` im Manifest, Schema-validiert.
- `test_claim_evidence_map_surface_agent_reading_pack_shows_summary`: Agent
  Reading Pack zeigt Summary statt EPISTEMIC_EMPTINESS.
- `test_claim_evidence_map_surface_no_registry_leaves_epistemic_gap`: Ohne
  Registry → keine Map, Leerstelle sichtbar.
- `test_claim_evidence_map_surface_invalid_registry_raises`: Ungültige
  Registry → RuntimeError (kein stilles Skippen).
- `test_claim_evidence_map_surface_uses_scan_repo_root`: echter Pfad
  `scan_repo → repo_summaries[0]["root"] → registry lookup → bundle emission`
  erzeugt `claim_evidence_map_json` im Manifest (End-to-End-Brückentest).

## 13. Next Slice

F2c ist umgesetzt: `docs/proofs/forensic-preflight-calibration-proof.md` und
`scripts/proofs/forensic_preflight_calibration.sh` kalibrieren
`governance forensic-preflight` gegen lokal erzeugte echte Bundles mit einem
Positivfall und negativen Fällen für fehlende Claim-Map, stale
`post_emit_health` und Hash-Drift.

Die optionale CI-Promotion von `forensic_strict` bleibt ein separater PR und
setzt weitere stabile Real-Bundle-Läufe voraus.

## 14. Real-Registry-Payload Surface Guard + Diagnosetaxonomie (2026-06-01)

Zusätzlich zur Minimal-/Fixture-Abdeckung wurde ein Real-Surface-Guard
ergänzt, der den repo-scan-basierten Single-Repo-Bundlepfad gegen eine echte Registry
absichert:

- `test_claim_evidence_map_surface_real_registry_payload_regression_guard` verwendet
  den realen Registry-Inhalt (`docs/doc-freshness-registry.yml`) im
  Single-Repo-Bundlepfad und prüft:
  - Manifest enthält `claim_evidence_map_json`.
  - Agent Reading Pack zeigt Summary statt EPISTEMIC_EMPTINESS.
  - `post_emit_health` bestätigt Presence/Hash/Schema für die Claim-Map.

Für fehlende Claim-Map wurde eine maschinenlesbare Abwesenheitsdiagnose
eingeführt (`links.claim_evidence_map_absence_reason` im Bundle-Manifest):

- `no_registry`
- `multi_repo_out_of_scope`
- `unexpected_missing_with_registry`

Diese Diagnose wird zusätzlich im Agent Reading Pack und in
`post_emit_health`/`forensic_preflight` sichtbar gemacht (Check-Details mit
`reason=<code>`), damit ein grünes `output_health` nicht als stilles
Forensic-Ready-Signal fehlinterpretiert wird.


### Manueller Smoke Test

Zusätzlich zum CI-Guard kann der Surface Guard manuell wie folgt validiert werden:

```bash
REPOLENS_HEADLESS=1 python3 -m merger.lenskit.frontends.pythonista.repolens . \
  --level max \
  --split-size 20MB \
  --meta-density full \
  --output-mode dual
```

Danach im Output-Manifest prüfen:
* `claim_evidence_map_json` ist als Artefakt vorhanden
* `links.claim_evidence_map_absence_reason` ist **nicht** gesetzt
* Das Agent Reading Pack zeigt eine Claim-Map-Summary an

Dieser Smoke Test ist rein informativ und ersetzt nicht die CI-Promotion von `forensic_strict`.

### Drei Surface-Ebenen (Abgrenzung)

Die Claim-Map-Garantie wird auf drei getrennten Ebenen geprüft — diese Trennung ist
bewusst und darf nicht vermischt werden:

1. **Unit-/Fixture-Surface** — synthetische Registry/Manifeste in
   `test_claim_evidence_map.py`, `test_bundle_manifest_integration.py`.
2. **Real-Registry-Payload Surface** — der Codepfad gegen die echte
   `docs/doc-freshness-registry.yml` (`test_claim_evidence_map_unexpected_missing_with_registry`).
3. **Real-Dump Surface Self-Check** — der **erzeugte** Dump prüft sich selbst:
   `bundle_surface_validate` läuft am Ende von `write_reports_v2`, persistiert
   `<stem>.bundle_surface_validation.json` und trägt `bundle_surface_validation_status`
   in die `links` ein. Ein Single-Repo-Dump mit Registry, dem die Claim-Map **ohne**
   Absenzgrund fehlt, bricht jetzt hart ab statt still durchzulaufen. Siehe
   [real-dump-surface-self-check-proof.md](real-dump-surface-self-check-proof.md).

Der historische Bruch war: Unit-/Surface-Test grün, **echter Dump** (Service-Runtime)
ohne Claim-Map — diagnostiziert als Runtime-Drift, da der aktuelle Code den Dump heute
korrekt mit Claim-Map erzeugt. Die `forensic_strict`-Promotion bleibt davon getrennt.
