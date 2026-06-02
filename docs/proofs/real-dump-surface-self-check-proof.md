# Real-Dump Surface Self-Check — Diagnosis & Implementation Proof

> Erstellt am 2026-06-02.
> Scope: Lenskit/rLens — der **reale Dump-Erzeugungspfad** (`write_reports_v2`)
> erhält eine Surface-Selbstprüfung, persistiertes `post_emit_health` und
> Generator-Runtime-Provenance, damit ein widersprüchlicher Bundle-Surface
> (Claim-Map fehlt, `output_health=pass`, Agent-Pack meldet „nicht erzeugt") nicht
> mehr still erzeugt werden kann und Runtime-Drift diagnostizierbar wird.

## 1. Ausgangsbefund (Report)

Ein frisch erzeugter echter Lenskit-Max-Dump zeigte:

- `generator.name=rlens`, `version=dev`, `platform=service` (Dump-Index),
  `source repo: lenskit`, `profile: max`, `output_mode: dual`, `coverage: 480/480`;
- Manifest **ohne** `claim_evidence_map_json`-Rolle und **ohne**
  `links.claim_evidence_map_absence_reason`;
- Agent Reading Pack meldet weiterhin `claim_evidence_map is not yet produced`;
- `output_health` trotzdem `verdict: pass`.

## 2. Diagnose vor Patch (Stop-Kriterium)

Die Diagnosepflicht verlangt, den Bruch vor jeder Implementierung zu lokalisieren.
Belegte Schritte:

1. **Registry vorhanden:** `docs/doc-freshness-registry.yml` existiert im Repo-Root.
2. **Entry Point identifiziert:** Der Dump stammt aus `merger/lenskit/service/runner.py`,
   das `generator_info = {"name": "rlens", "version": os.getenv("RLENS_VERSION","dev"),
   "platform": "service"}` setzt und `write_reports_v2(...)` aufruft. Exakt diese
   Provenance steht im Report-Dump.
3. **Codepfad korrekt:** `write_reports_v2` (`merge.py`) erzeugt `claim_evidence_map_json`
   für Single-Repo-Bundles, deren `repo_summaries[0]["root"]/docs/doc-freshness-registry.yml`
   existiert, und setzt sonst einen maschinenlesbaren Absenzgrund.
4. **Legacy-String nicht im Repo:** Der gemeldete Text
   `claim_evidence_map is not yet produced` existiert **nirgends** im aktuellen Baum
   (`grep -r` leer). Der aktuelle Pack-Code schreibt `CLAIM_EVIDENCE_MAP_SUMMARY` bzw.
   `_No verified \`claim_evidence_map_json\` artifact present._`.

### 2.1 Faithful-Reproduktion des Service-Pfads

Ein Reproduktionslauf, der die **exakte Service-Provenance** (`rlens`/`service`/`dev`,
kein vorab gesetztes `config_sha256`) gegen den realen Repo-Root mit echter Registry
fährt, ergab mit **dem aktuellen Repo-Code**:

```
roles: [..., 'claim_evidence_map_json', ...]      # vorhanden
links.claim_evidence_map_absence_reason: None      # korrekt nicht gesetzt
agent_reading_pack: '## CLAIM_EVIDENCE_MAP_SUMMARY' vorhanden, kein Legacy-Text
generator: {name: rlens, version: dev, config_sha256: ...}   # NUR diese drei Felder
post_emit_health persisted by dump path: False     # NICHT persistiert
output_health verdict: pass; prüft Claim-Map: False
```

### 2.2 Schlussfolgerung

Der gemeldete Widerspruch ist aus dem **aktuellen Repo-Code nicht reproduzierbar**.
Ursache ist damit **Runtime-/Entry-Point-Drift** (Stop-Kriterium #4): die Service-Runtime,
die den Report-Dump erzeugte, lief auf einem **älteren Build**, der die Claim-Map-Verdrahtung
noch nicht enthielt. Belege: (a) Legacy-String existiert nicht mehr im Code; (b) der
faithful Service-Pfad erzeugt heute Map + Summary; (c) der Generator-Block trägt **nur**
`{name, version, config_sha256}` — es gibt **keine Runtime-Provenance**, mit der man dem
Dump ansähe, **welcher Build** ihn erzeugte.

Die **repo-fixbaren** Lücken (unabhängig von der fremden Runtime):

| # | Lücke | Beleg |
| :-- | :--- | :--- |
| G1 | `post_emit_health` wird im realen Dump-Pfad **nicht** persistiert | `write_reports_v2` rief es nie auf; nur pre-emit `output_health` (grün) lag vor |
| G2 | Kein **Surface-Self-Check** am Ende des Dump-Pfads | nichts prüfte „Claim-Map vorhanden XOR Absenzgrund gesetzt" auf dem finalen Bundle |
| G3 | **Generator-Provenance** reicht nicht zur Drift-Diagnose | nur `{name, version, config_sha256}`, kein Modul/Pfad/Commit |
| G4 (Nebenbefund) | `produce_claim_evidence_map → validate_registry` importiert `jsonschema` hart | ohne `jsonschema` bricht der **gesamte** Dump ab (in der Service-Prod-Umgebung ist `jsonschema` vorhanden → nicht das Report-Symptom; dokumentiert, nicht gepatcht) |

## 3. Umsetzung (additiv)

1. **`merger/lenskit/core/bundle_surface_validate.py`** — `validate_bundle_surface(manifest, *, require_claim_evidence_map=False)`.
   Checks (Statusmodell `fail > blocked > warn > pass`):
   - `claim_evidence_map_surface` — vorhanden XOR maschinenlesbarer Absenzgrund;
   - `agent_reading_pack_consistency` — vorhandene Claim-Map **muss** im Pack als
     Summary mit `- artifact:`-Zeile sichtbar sein (fehlende Summary = `fail`),
     Legacy-`claim_evidence_map is not yet produced` = Drift = `fail`;
   - `post_emit_health_persisted` **und** `post_emit_health_status` — getrennt:
     Persistenz (liegt vor) **und** propagierter Verdikt; ein vorhandenes, aber
     `fail`/`blocked` `post_emit_health` zieht den Surface-Status mit nach unten
     (kein „pass nur weil die Datei existiert");
   - `surface_links_coherent` — die in `links` eingetragenen Sidecar-Pfade müssen
     auflösen (Dangling-Link = `fail`);
   - `output_health_not_forensic_ready` — macht explizit, dass `output_health` ein
     pre-emit-Signal ist;
   - `generator_provenance` — `name`/`version`/`config_sha256` vorhanden, `runtime`
     verfügbar (fehlend = `warn`).
   Rein, schreibt nicht. `write_bundle_surface_validation` persistiert
   `<stem>.bundle_surface_validation.json` (unregistriert — ein Self-Check verifiziert
   nie den eigenen Hash), Contract `bundle-surface-validation.v1.schema.json`.
2. **`merger/lenskit/cli/cmd_bundle_surface.py`** + Dispatch in `cli/main.py`:
   `lenskit bundle-surface validate --manifest <m> [--require claim-evidence-map] [--json] [--emit-artifact]`.
   Exit-Codes `0=pass/warn`, `1=fail`, `2=blocked` (konsistent mit `bundle-health`).
3. **`merger/lenskit/core/runtime_provenance.py`** — `build_runtime_provenance(redact=...)`:
   `module`, `module_file`, `package_root`, `python_executable`, `python_version`,
   `git_commit`, `git_dirty`. Bei `redact=True` werden absolute Pfade auf `null` gesetzt,
   `git_commit`/`module`/`python_version` als redaction-sichere Drift-Anker bleiben.
4. **`write_reports_v2`-Verdrahtung** (`merge.py`):
   - Generator-Block trägt jetzt `runtime`-Provenance (redaction-bewusst).
   - Nach finalem Manifest + Agent-Pack: `post_emit_health` wird als
     `<stem>.bundle_health.post.json` persistiert; danach läuft die Surface-Validierung
     und wird als `<stem>.bundle_surface_validation.json` persistiert.
   - `links` tragen maschinenlesbar `post_emit_health_path`,
     `bundle_surface_validation_path`, `bundle_surface_validation_status`.
   - **Hartes Gate (eng auf die Claim-Map-Invariante geschnitten):** Ist die
     Claim-Map-Surface gefordert (Single-Repo **und** Registry vorhanden) und ist
     ein **Claim-Map-Invariantencheck** (`claim_evidence_map_surface` oder
     `agent_reading_pack_consistency`) `fail` (stille Absenz / Widerspruch /
     Legacy-Pack / Pack ohne Summary), bricht der Lauf mit `RuntimeError`.
     Ein **deklarierter** Gap (`claim_evidence_map_surface=blocked`, z. B.
     `unexpected_missing_with_registry`) bricht **nicht**. Andere Surface-Befunde
     (z. B. `post_emit_health.status=fail`) werden **laut** über den persistierten
     Sidecar + `links.bundle_surface_validation_status` festgehalten, brechen aber
     nicht den ganzen Dump ab — das Gate bleibt auf seinem Auftrag (Claim-Map).
5. **Contracts**: neuer `bundle-surface-validation.v1.schema.json` für das Sidecar
   (`kind=lenskit.bundle_surface_validation`, `status`-Enum, `checks[].status`-Enum,
   `does_not_mean`, lint-konform als `diagnostic_signal`); `bundle-manifest.v1.schema.json`
   erweitert um optionales `generator.runtime` und die drei neuen `links`-Schlüssel.

### 3.1 Welche der drei Zielzustände gelten jetzt

Der reale Single-Repo-Dump mit Registry erfüllt nun verbindlich **einen** der drei
geforderten Zustände, statt still durchzulaufen:

1. `claim_evidence_map_json` erzeugt und sichtbar — **Normalfall** (heutiger Code), **oder**
2. maschinenlesbarer Absenzgrund in Manifest/Pack/Surface gesetzt (`status=blocked`), **oder**
3. **harter Lauf-Abbruch** bei verletzter Surface-Invariante (`status=fail`).

## 4. Proof: Surface nach dem Patch

Faithful Service-Pfad (`rlens`/`service`/`dev`) gegen Repo-Root, **mit Patch**:

```json
"generator": {
  "name": "rlens", "version": "dev", "config_sha256": "…",
  "runtime": {
    "module": "merger.lenskit.core.merge",
    "module_file": "/…/merger/lenskit/core/merge.py",
    "package_root": "/…",
    "python_executable": "/usr/local/bin/python3",
    "python_version": "3.11.15",
    "git_commit": "…", "git_dirty": true
  }
},
"links": {
  "canonical_dump_index_sha256": "…",
  "post_emit_health_path": "…_merge.bundle_health.post.json",
  "bundle_surface_validation_path": "…_merge.bundle_surface_validation.json",
  "bundle_surface_validation_status": "pass"
}
```

`post_emit_health` persistiert: **True**. CLI gegen das Manifest:
`lenskit bundle-surface validate --manifest <m> --require claim-evidence-map --json`
→ `status: pass`, Exit 0.

Drift-Gegenproben (synthetische Manifeste, `--require claim-evidence-map`):

| Surface | erwartet | Ergebnis |
| :--- | :--- | :--- |
| Claim-Map vorhanden | pass / Exit 0 | ✓ |
| Claim-Map fehlt, `absence_reason=no_registry` | blocked / Exit 2 (kein stiller Pass) | ✓ |
| Claim-Map fehlt, **kein** Grund | fail / Exit 1 | ✓ |
| Claim-Map vorhanden **und** `absence_reason` gesetzt | fail (Widerspruch) | ✓ |
| Claim-Map vorhanden, Pack **ohne** Summary | fail (Pack-Drift) | ✓ |
| Pack trägt Legacy `claim_evidence_map is not yet produced` | fail (Drift) | ✓ |
| `post_emit_health` vorhanden, aber `status=fail` | fail (Verdikt propagiert, kein „pass nur weil persistiert") | ✓ |
| `links` zeigt auf nicht vorhandenes Sidecar | fail (Dangling-Link) | ✓ |
| Generator ohne `runtime` | warn (Drift nicht diagnostizierbar) | ✓ |

## 5. Abgrenzung

- **Keine** CI-Promotion von `forensic_strict` — bleibt separater Entscheidungspunkt.
- `post_emit_health` und die Surface-Validierung werden als **Sidecars** persistiert und
  über `links` referenziert, **nicht** als Manifest-Artefakte registriert: ein Self-Check
  darf den eigenen Hash nicht verifizieren, und `post_emit_health` darf keine
  Manifest-Hash-Zirkularität erzeugen (bewusste Entscheidung, nicht „getrickst").
- `output_health=pass` ist und bleibt ein **pre-emit**-Signal; der Surface-Check macht
  explizit, dass es **nicht** Forensic-Ready bedeutet.
- Nebenbefund G4 (hart importiertes `jsonschema` in `validate_registry`) ist dokumentiert,
  aber bewusst **nicht** in diesem Slice gepatcht (kein Report-Symptom; eigener Scope).

## 6. Validierung

```
python3 -m pytest -q \
  merger/lenskit/tests/test_bundle_surface_validate.py \
  merger/lenskit/tests/test_cli_bundle_surface.py \
  merger/lenskit/tests/test_runtime_provenance.py        # 39 passed

python3 -m pytest -q merger/lenskit/tests/test_anti_hallucination_lint.py   # 33 passed
# governance lint (real tree): 41 contracts scanned, 0 errors, 0 deferred

python3 -m pytest -q --ignore=merger/lenskit/tests/test_webui_payload.py merger/lenskit/tests/
                                                          # 1751 passed, 1 skipped

python3 -m ruff check merger/lenskit/core/bundle_surface_validate.py \
  merger/lenskit/core/runtime_provenance.py merger/lenskit/cli/cmd_bundle_surface.py \
  merger/lenskit/tests/test_bundle_surface_validate.py \
  merger/lenskit/tests/test_cli_bundle_surface.py \
  merger/lenskit/tests/test_runtime_provenance.py         # All checks passed
```

`test_webui_payload.py` (Playwright) bleibt unabhängig von dieser PR ausgeschlossen.
