# Forensic Preflight CI Canary Proof

> Erstellt am 2026-06-03.
> Scope: kontrollierter GitHub-Actions-**Canary** für
> `governance forensic-preflight`.
> Nicht-Ziel: globale `forensic_strict`-Blockade, Claim-Wahrheitsurteil,
> Core-Bundle-Umbau.

## 1. Ausgangslage

F2c (`docs/proofs/forensic-preflight-calibration-proof.md`,
`scripts/proofs/forensic_preflight_calibration.sh`) kalibrierte
`governance forensic-preflight` lokal gegen echte, durch die Merge-Pipeline
erzeugte Bundles. Dieser Slice erzeugte **kein** CI-Gate und promotete
`forensic_strict` **nicht** zu einem blockierenden Workflow. Die Preflight-CLI
liefert `pass|warn|blocked|fail` für die formalen `forensic_strict`-Voraussetzungen.

## 2. Warum jetzt?

Der reale Service-Dump nach `TASK-BUNDLE-001` / `TASK-SERVICE-001` trägt stabil:

- `generator.runtime` (Modul/Pfad/Python-Version/Commit, `git_dirty=false`),
- `claim_evidence_map_json`,
- `links.post_emit_health_path`,
- `links.bundle_surface_validation_path`,
- `links.bundle_surface_validation_status = pass`.

`post_emit_health` ist `pass`, `bundle_surface_validation` ist `pass`
(`claim_evidence_map_surface`, `agent_reading_pack_consistency`,
`post_emit_health_status`, `surface_links_coherent`, `generator_provenance`).
Damit sind die Surface-Voraussetzungen stabil genug, um die Preflight-Signale in
CI **sichtbar** zu machen — als Frühwarnung, nicht als globale Policy.

## 3. Diagnose vor Patch (belegter Bug)

Vor dem Patch lief der vorhandene F2c-Harness lokal **rot**: der Positivfall
brach mit `positive real bundle missing required roles: ['claim_evidence_map_json']`
ab.

Ursache (belegt über `git log -L`): Commit `39f27873` verschob die
Claim-Map-Herkunft von der **Paket**-eigenen Registry
(`Path(__file__).resolve().parents[3] / "docs" / "doc-freshness-registry.yml"`,
also der lenskit-Repo-Registry) auf die **gescannte** Repo-Registry
(`Path(repo_summaries[0]["root"]) / "docs" / "doc-freshness-registry.yml"`,
core/merge.py). Das ist die korrekte Surface-Parity-Semantik: ein Single-Repo-
Dump muss seine Claim-Map aus *seiner eigenen* Registry ableiten. Nebenwirkung:
das F2c-Fixture-Repo enthielt keine `docs/doc-freshness-registry.yml`, erzeugte
also keine Claim-Map mehr.

Fix (Test-Harness, keine Core-Änderung): das Fixture in
`forensic_preflight_calibration.sh` liefert nun eine minimale, schema-valide
`docs/doc-freshness-registry.yml`. Damit produzieren beide Harnesses wieder
deterministisch `claim_evidence_map_json`.

## 4. Umsetzung

- `.github/workflows/forensic-preflight-canary.yml` — path-scoped Canary
  (PR + push auf `main`/`master`), `permissions: contents: read`, Python 3.12,
  installiert `merger/lenskit/requirements.txt` (liefert **jsonschema**) und
  `requirements-dev.txt`.
- `scripts/proofs/forensic_preflight_ci_canary.sh` — fokussierter Canary:
  baut über den Standard-Merge-Pfad (`scan_repo` + `write_reports_v2`,
  `max_bytes=100_000`) ein kleines, hermetisches, registry-tragendes
  Fixture-Bundle, schreibt `post_emit_health`, führt
  `governance forensic-preflight --manifest <manifest> --json` aus,
  persistiert den JSON-Report und erzwingt **strikt** `status=pass`.
- `scripts/proofs/forensic_preflight_calibration.sh` — Fixture-Fix (s. §3);
  die volle 4-Fall-Matrix (Positiv + drei Negativfälle) bleibt das lokale
  Diagnoseorchester. Der Canary fügt nur den strikten `pass`-Gate und das
  CI-Artefakt hinzu — die Preflight-Verdict-Logik bleibt
  `core/forensic_preflight.compute_forensic_preflight` als einzige Quelle.
- `merger/lenskit/tests/test_forensic_preflight.py` bleibt Unit-/Core-Abdeckung
  und läuft als blockierender CI-Schritt.

### Maschinenlesbares Artefakt

Der Canary persistiert
`.tmp/forensic-preflight-ci-canary/artifacts/forensic-preflight-canary.json`
(der vollständige Preflight-Report) und lädt ihn als Build-Artefakt
`forensic-preflight-canary` hoch (`if: always()`).

## 5. Was PASS bedeutet

PASS bedeutet:

- die formalen Bundle-Voraussetzungen für `forensic_strict` sind erfüllt
  (Manifest geladen; `canonical_md`/`chunk_index_jsonl`/`citation_map_jsonl`/
  `claim_evidence_map_json`-Hashes verifiziert; Claim-Map-Schema gültig;
  `post_emit_health` `pass` und an Manifest/`run_id` gebunden; `range_strict`-
  Evidence erreicht; keine Pflichtchecks übersprungen; Redaction-Policy
  explizit).

PASS bedeutet **nicht**:

- Claims sind wahr (`does_not_mean: claims_true`);
- das Repository wurde semantisch verstanden (`repo_understood`);
- ein Agent darf ohne Citation-/Range-Belege antworten
  (`answer_safe_without_citations`);
- die Claim-Evidence-Map ersetzt die Citation Map.

## 6. Verifikation

Lokal (Python 3.11, `jsonschema`/`pytest`/`PyYAML` installiert) ausgeführt:

| Befehl | Ergebnis |
| :--- | :--- |
| `pytest -q merger/lenskit/tests/test_forensic_preflight.py` | grün |
| `bash -n scripts/proofs/forensic_preflight_ci_canary.sh` | OK |
| `bash scripts/proofs/forensic_preflight_ci_canary.sh` | `status=pass`, 13/13 Checks `pass`, Artefakt geschrieben |
| `bash scripts/proofs/forensic_preflight_calibration.sh` | positive=`pass`, missing_claim_map=`blocked`, stale_post_emit_health=`fail`, hash_drift=`fail` |

Der Canary-Report trägt `does_not_mean = [claims_true, repo_understood,
answer_safe_without_citations]`.

## 7. Grenzen / Nicht-Ziele

- **Kein** globaler Required Check für alle PRs. Vollständige blockierende
  `forensic_strict`-Promotion bleibt ein Folge-PR, frühestens nach mehreren
  stabilen Canary-Läufen über unterschiedliche Bundle-Profile.
- **Kein** Umbau von `core/merge.py`, `core/bundle_surface_validate.py`,
  `core/runtime_provenance.py` oder `core/claim_evidence_map.py`.
- **Keine** neue Wahrheits-/Support-Bewertung von Claims.
- **Kein** Service-/systemd-Scope, kein `rlens.service`-Restart-Test, keine
  Bindung an `/home/alex`.
- **Kein** Retrieval-Ranking-Fix, kein `TASK-CTL-004`-Ratchet/Baseline-Scope.
- Das Fixture ist klein und hermetisch; CI braucht außer `checkout`/`pip install`
  kein Netzwerk.

## 8. Entscheidung / nächster Gate-Punkt

Der Kanarienvogel ist im Stollen: die `forensic_strict`-Voraussetzungen sind in
CI sichtbar und brechen bei formaler Drift früh. Die blockierende Promotion zum
Required Check bleibt bewusst offen, bis mehrere reale Canary-Läufe stabil grün
sind. Das Thermometer ist geeicht und jetzt in der Wand verbaut; es ist noch
kein Richter.
