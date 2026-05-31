# Doc-Freshness Registry v0 — Proof

> Erstellt am 2026-05-31.
> Scope: **diagnostischer** Mechanismus, der Dokumentations-Aussagen (TODOs,
> Roadmap-/Spec-Behauptungen) maschinell gegen Code-/Test-/Proof-**Belege**
> koppelt und Drift sichtbar macht. Diagnose-first nach der Rollout-Regel der
> Artifact-Drift-Matrix: **keine** neue blockierende CI-Stufe.

## 0. Kernbefund (TL;DR)

Lenskit hatte **Drift-Bewusstsein** (Artifact-Drift-Matrix, Two-Layer-Pattern,
Proof-Pflicht, C2.x-Lints), aber **keine maschinenlesbare Statuskopplung**
zwischen einer Doku-Aussage und dem Beleg, der sie stützt oder widerlegt. Genau
diese Lücke war im gemergten Reconciliation-PR sichtbar: `repoLens-spec.md`
führte einen `### TODO: Super-Merger / Extras`-Block, obwohl `ExtrasConfig` seit
2026-05 in `core/merge.py:458` implementiert ist (Beleg:
`weiterentwicklungsplan-2026-05-reconciliation-proof.md` §6.1, dort bewusst „für
einen eigenen, fokussierten PR" zurückgestellt).

**Dieser PR ist dieser fokussierte PR.** Er schließt den konkreten Drift **und**
liefert den fehlenden Mechanismus als kleinsten, selbst-beweisenden Slice.

## 1. Negativbefund (vor Implementierung verifiziert)

Vor diesem PR existierte kein Doc-Freshness-Mechanismus:

- `rg` über `docs/**`, `*.md` ergab **genau einen** echten stale `TODO:`-Marker
  in einer Doku (`merger/lenskit/repoLens-spec.md:53`) — ein reiner
  „TODO:-Scanner" hätte fast nichts zu prüfen und die eigentliche Driftklasse
  (semantische Prosa wie „existieren derzeit nicht im Quellbaum") verfehlt.
- `docs/architecture/artifact-drift-matrix.md` modelliert **Artefakt**-Drift,
  nicht „Doku behauptet alten Implementierungsstand".
- `docs/architecture/inconsistencies.md` ist eine **handgepflegte** Audit-Liste,
  nicht maschinell verifiziert.
- Kein CLI-Kommando, kein CI-Workflow, kein Schema zu `doc-freshness`,
  `roadmap-lint`, `last_verified` o. ä. (`ls .github/workflows/`,
  `cli/`-Scan).

**Schlussfolgerung:** Die richtige Primitive ist **nicht** ein TODO-Text-Scanner,
sondern eine **Beleg-Bindung** (claim → verifizierbares Artefakt → Status) mit
einem Verifier — analog zur C2.9-Authority-Upgrade-Registry (Detektion bleibt an,
deklarierte Fälle werden **sichtbar** gemacht, nicht stumm unterdrückt).

## 2. Was dieser PR hinzufügt

| Datei | Rolle |
| --- | --- |
| `merger/lenskit/contracts/doc-freshness-registry.v1.schema.json` | Schema (Draft-7, `additionalProperties:false`) für die Registry |
| `docs/doc-freshness-registry.yml` | Hand-gepflegte Source-of-Truth: claim → status → evidence |
| `merger/lenskit/core/doc_freshness.py` | Reiner Verifier (Beleg-Auflösung via `ast`/Text/Datei, Klassifikation, Report, Render, Restamp) |
| `merger/lenskit/cli/cmd_doc_freshness.py` | `lenskit doc-freshness inspect` / `update` |
| `docs/_generated/doc-freshness.md` | **Generierte** Statusansicht (aus der Registry regeneriert, nicht handgepflegt) |
| `.github/workflows/doc-freshness.yml` | **Nicht-blockierender** Diagnose-Gate + Test-Suite |
| `merger/lenskit/tests/test_doc_freshness.py` | 27 Tests (synthetische Fixtures + reale Registry) |

### Evidence-Arten (mechanisch prüfbar)

`symbol` (`relpath::Name`, AST-Definition in `.py`, sonst Substring), `file`,
`text` (`relpath::needle` vorhanden), `absent_text` (needle **abwesend**),
`proof`, `test`. `symbol`/`test`/`proof` implizieren standardmäßig „done".

### Klassifikation (Drift-Logik)

Pro Eintrag wird `declared status` gegen die verifizierten Belege gestellt:

- `consistent` / `partial_ok` / `historical` — kein Finding.
- `understated` (warn) — Doc sagt `none`, aber Completion-Beleg existiert (die
  Kern-Driftklasse „Doku hinkt dem Code hinterher").
- `stale_marker_present` (warn) — Doc sagt `done`, enthält aber noch den
  TODO-/Alttext (der „Vorher"-Zustand des Piloten).
- `stale_confirmed` (tracked, **kein** Finding ohne `--strict`) — bewusst
  deklarierte, reproduzierbare Drift (wie C2.9 `declared_upgrades`).
- `stale_resolved` (warn) — deklariertes `stale`, aber der Marker ist weg →
  Registry-Eintrag auf `done` heben.
- `regressed` / `dangling` (error) — zitierter Beleg fehlt / `done` ohne Beleg.

## 3. Pilot: `repoLens-spec.md` Super-Merger / Extras

**Aktion (der fokussierte Spec-Fix):** Der `### TODO: Super-Merger / Extras`-Block
wurde zu `### Super-Merger / Extras — implementiert (2026-05)` umgeschrieben, mit
Status-/Beleghinweis (kein TODO mehr). Inhalt (Extras-Contract) bleibt als
Dokumentation erhalten.

**Registry-Eintrag** `repolens-spec-super-merger-extras` (`status: done`,
`normative: true`):

- `symbol merger/lenskit/core/merge.py::ExtrasConfig` → vorhanden,
- `proof …/weiterentwicklungsplan-2026-05-reconciliation-proof.md` → vorhanden,
- `absent_text merger/lenskit/repoLens-spec.md::### TODO: Super-Merger / Extras`
  → erfüllt (Heading ist weg; der Guard verhindert sein stilles Wiederkehren).

**Vorher/Nachher maschinell bewiesen** (`test_verify_pilot_before_and_after`):
mit TODO-Heading → `stale_marker_present` (warn); ohne → `consistent` (pass).

Zwei weitere reale Einträge belegen das Spektrum ohne False-Positives:
`system-map-federation-exists` (`done`; früher-realer, bereits korrigierter
Drift, jetzt gegen Rückfall gesichert) und
`agent-reading-pack-v2-claim-evidence-map` (`partial`; echt offen — `claim_evidence_map`
ist laut `agent_reading_pack.py:859` „not yet produced" — wird **nicht**
fälschlich als done geflaggt).

## 4. „Automatisierte Aktualisierung" — was real automatisiert ist

Das Ziel war eine automatisierte Aktualisierung der Dokumente. Ehrliche
Zerlegung dessen, was sicher automatisierbar ist:

- **Detektion** des Widerspruchs Status ↔ Beleg: vollautomatisch (✓ umgesetzt).
- **Verifikation**, dass Belege existieren (Symbol/Datei/Test/Proof): ✓ umgesetzt.
- **`last_verified`-Stamping** + **Regeneration der `docs/_generated/doc-freshness.md`**
  aus der verifizierten Registry: ✓ umgesetzt (`update --write`). Die generierte
  Ansicht ist damit ein **automatisch synchron gehaltenes Dokument**;
  `generated_at` wird deterministisch aus den Daten abgeleitet (max
  `last_verified`), damit Regeneration eine reine Funktion der Eingaben ist.
- **Prosa automatisch umschreiben** (normative Spec-Texte): **bewusst NICHT**.
  Ohne Mensch/LLM-in-the-loop nicht zuverlässig; die eine reale Prosa-Korrektur
  (Pilot) wurde manuell und belegt durchgeführt.

## 5. Validierung

- `python -m merger.lenskit.cli.main doc-freshness inspect` → **PASS**
  (3 Einträge, 0 Findings, exit 0).
- `… doc-freshness inspect --strict` → **PASS** (kein ungelöster normativer
  stale-Drift).
- `… doc-freshness update` → idempotent (zweiter Lauf: „up to date"; 0
  last_verified-Änderungen).
- `pytest -q merger/lenskit/tests/test_doc_freshness.py` → **27 passed**.
- `ruff check --select=F401,F811,F841,E711,E712` → sauber.
- Bestehende CLI unberührt: `governance lint` → exit 0.

## 6. STOP / bewusst nicht enthalten

- **Keine** blockierende CI (diagnostisch; Promotion pro Eintrag wie die
  Drift-Matrix). `--strict` ist der vorbereitete Enforcement-Pfad, aber im
  Workflow nicht scharf geschaltet.
- **Keine** automatische Prosa-Umschreibung normativer Dokumente.
- **Keine** Semantik-/LLM-Prüfung „TODO X ist erledigt" — nur deklarierte,
  mechanisch prüfbare Belege.
- **Keine** Vollabdeckung aller Docs — v0 verfolgt 3 belegte Einträge; die
  Registry wächst additiv.
- **Keine** stumme Suppression: `stale` ist sichtbar (`stale_confirmed`).

## 7. Promotionspfad (spätere Slices)

1. **Diagnose** (dieser PR): Verifier + Registry + generierte Ansicht, warnend.
2. **Enforcement normativer Specs:** `doc-freshness inspect --strict` im CI
   blockierend schalten, sobald die Registry stabil läuft (per-Eintrag, nicht
   global — Blueprints bleiben `historical` und werden nie blockiert).
3. **Generierte-Ansicht-Staleness als Guard:** `update` + `git diff --exit-code`
   blockierend, sobald etabliert.
4. **Breitere Abdeckung:** weitere normative Specs / Master-Roadmap-Aussagen
   additiv in die Registry aufnehmen.

## 8. Belegt / plausibel / spekulativ

- **Belegt:** Kein Doc-Freshness-Mechanismus existierte; der `repoLens-spec.md`-Drift
  war real; der Verifier erkennt ihn maschinell (Tests) und der Pilot ist
  geschlossen (live Registry PASS).
- **Plausibel:** Beleg-Bindung schlägt einen TODO-Text-Scanner (richtige
  Primitive, niedrige False-Positive-Fläche, passt zu C2.9/Drift-Matrix).
- **Spekulativ:** Vollautomatische Semantikprüfung „Feature erledigt" ohne
  deklarative Evidence-Mapping-Schicht bleibt unzuverlässig — daher nicht gebaut.
