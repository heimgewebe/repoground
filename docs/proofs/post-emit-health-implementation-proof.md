# Post-emit Bundle Health (`post_emit_health`) — Implementation Proof

Status: Implementation note for roadmap **PR A4** (Post-hoc Bundle Validator).
Belegbasis: `docs/blueprints/lenskit-anti-hallucination-output-architecture.md` §3 (PR A4),
`docs/blueprints/lenskit-artifact-output-control-plane.md` §2.4 / §12,
`docs/architecture/artifact-evidence-levels.md`.

## 1. Diagnose: warum pre-emit `output_health` die Lücke nicht schließt

`output_health` wird **vor** der Finalisierung des Bundles geschrieben und gegen den
`dump_index` verankert, nicht gegen das finale `bundle_manifest`:

- `merger/lenskit/core/merge.py:5988-6028` — `write_output_health(..., primary_manifest_path=final_dump_index, ...)`
  läuft, **bevor** das Bundle-Manifest finalisiert wird.
- `merger/lenskit/core/merge.py:6098-6123` — der `agent_reading_pack` wird **zuletzt**
  erzeugt und erst danach ins Manifest eingetragen.
- `merger/lenskit/core/output_health.py:424-466` — der In-Pipeline-Aufruf kennt den Pack
  nicht (`agent_pack_present.status = "skipped"`), weil der Pack zu diesem Zeitpunkt noch
  nicht existiert.

Folge: pre-emit Health kann die **finale Bundle-Oberfläche** (inkl. `agent_reading_pack`,
`citation_map`, finale Manifest-Hashes) strukturell nicht prüfen. Genau diese Lücke
schließt `post_emit_health` post-hoc.

Bestätigung „keine bestehenden post-emit-Hooks": `grep -rn "post_emit_health|bundle_health|bundle-health"`
fand vor dieser PR ausschließlich Doku-Verweise, keinen Code/CLI.

## 2. Was gebaut wurde (additiv, lokal)

- `merger/lenskit/core/post_emit_health.py` — Validator (`compute_post_emit_health`, rein;
  `write_post_emit_health`, optional persistierend).
- `merger/lenskit/contracts/post-emit-health.v1.schema.json` — neuer, lokaler Contract.
- `merger/lenskit/cli/cmd_bundle_health.py` + Dispatch in `cli/main.py` —
  `lenskit bundle-health post <manifest> [--json] [--emit-artifact] [--output P] [--no-require-agent-pack]`.
- Datei-Artefakt (nur bei `--emit-artifact`): `<stem>.bundle_health.post.json`.

Geprüft werden: Manifest-Präsenz + Schema, Artefakt-Pfade, Artefakt-Hashes,
`agent_reading_pack` Präsenz/Hash, Self-Role (Pack nicht als canonical/content deklariert),
Range-Ref-Resolution (wo relevant), Redaction-Status (nur Bericht), Noise-Hygiene (falls
vorhanden), erreichter Evidence-Level (bestehendes Vokabular), `does_not_mean`.

## 3. Statusmodell

Präzedenz `blocked` > `fail` > `warn` > `pass`:

- `blocked` — Zertifizierung **nicht abschließbar**: erforderliche Oberfläche fehlt
  (Manifest unlesbar / kein `repolens.bundle.manifest` / keine `artifacts`-Liste, oder eine
  Pflichtrolle wie `canonical_md` / `agent_reading_pack` ist **nicht deklariert**).
- `fail` — Zertifizierung abgeschlossen, aber **Defekt** gefunden: deklariertes Artefakt
  fehlt auf Platte, Hash-Mismatch, Schema-Verstoß, Range-Ref-Resolution-Fehler, Pack als
  canonical/content fehldeklariert.
- `warn` — nutzbar, aber degradiert (z. B. `jsonschema` nicht verfügbar).
- `pass` — alle Pflicht-Checks erfüllt.

## 4. Harte Grenzen (eingehalten)

- **Unabhängigkeit:** `output_health.verdict` ist reine **Beobachtung**
  (`output_health_verdict`) und geht **nie** in die Statusberechnung ein. Explizit als
  `independence_note` ausgewiesen: *„output_health.verdict=pass does not imply
  post_emit_health.status=pass"*. Negativtest: `test_post_emit_health_independent_of_pre_health`.
- **Kein Redaction-Enforcement:** `redaction_status.enforced` ist immer `false`;
  `redact_secrets=false` führt nicht zu `fail` (Test:
  `test_post_emit_health_reports_redaction_without_enforcing`). Enforcement bleibt PR A5.
- **Kein A5/Profil/Export, kein MCP/Task-Pack/Dashboard/Monitor.**
- **Kein `agent_ready`/`agent_safe`-Artefakt, kein Parallelvokabular** neben
  `post_emit_health`.
- **Keine Claim-Bewertung,** keine Verdikte `supported/unsupported/true/false/proven`.
- **Keine globale Verstehens-Ampel:** `evidence_level` nutzt nur das bestehende
  control-plane-Vokabular; `does_not_mean` enthält mindestens `repo_understood` und
  `answer_safe_without_citations`.
- **`output_health` unverändert:** keine Redefinition; Modul nur als Helper importiert
  (`_is_jsonschema_unavailable_error`).
- **Bundle-Erzeugung unverändert:** kein Eingriff in `merge.py`, kein Manifest-Schema-Bruch.

## 5. Persistenz ist explizit (keine versteckten Seiteneffekte)

Validierung, Emission und Registrierung bleiben getrennt:

- Default: `bundle-health post <manifest>` validiert + druckt + Exit-Code, **ohne** Datei.
- `--emit-artifact` (oder `--output`): schreibt `<stem>.bundle_health.post.json`.
- Das persistierte Artefakt ist **unregistriert** — das Bundle-Manifest wird **nicht**
  mutiert (kein Self-Hash, keine Manifest-Wahrheitsänderung). Test:
  `test_write_post_emit_health_persists_unregistered_artifact`,
  `test_bundle_health_post_cli_emit_artifact`.
- `--register-artifact` (Manifest-Mutation) ist bewusst **nicht** implementiert und bleibt
  späteren, explizit registrierenden Schritten vorbehalten.

### 5.1 Persistenz im realen Dump-Pfad (Nachtrag 2026-06-02)

Ursprünglich wurde `post_emit_health` **nur** auf CLI-Anforderung (`--emit-artifact`)
geschrieben; der reale Dump-Pfad (`write_reports_v2`) persistierte es **nicht** — nur das
pre-emit `output_health` lag vor, was ein grünes, aber nicht forensic-ready Bundle
nahelegte.

`write_reports_v2` ruft jetzt nach finalem Manifest + Agent-Pack automatisch
`write_post_emit_health(...)` auf und persistiert `<stem>.bundle_health.post.json`. Der
Pfad wird maschinenlesbar über `links.post_emit_health_path` referenziert. Das Artefakt
bleibt **unregistriert** (kein Self-Hash, keine Manifest-Hash-Zirkularität) — die
Invariante aus §5 gilt unverändert; persistiert wird der Sidecar, nicht eine
Manifest-Rolle. Abgrenzung zu `output_health` (pre-emit, beobachtend) bleibt explizit
und wird durch den Surface-Self-Check (`output_health_not_forensic_ready`) sichtbar
gemacht. Siehe [real-dump-surface-self-check-proof.md](real-dump-surface-self-check-proof.md).

## 6. Validierung

```
python3.11 -m pytest merger/lenskit/tests/test_post_emit_health.py merger/lenskit/tests/test_cli_bundle_health.py   # 22 passed
python3.11 -m pytest merger/lenskit/tests/test_output_health.py merger/lenskit/tests/test_bundle_manifest_integration.py  # 68 passed (keine Regression)
python3.11 -m pytest --ignore=merger/lenskit/tests/test_webui_payload.py  # 1335 passed, 1 skipped
```

Voller `pytest`-Lauf ist nur durch die Browser-Tests in `test_webui_payload.py`
(pytest-playwright `page`-Fixture, kein Headless-Runtime hier; `browser`-Marker in
`pytest.ini`) blockiert — unabhängig von dieser PR.
