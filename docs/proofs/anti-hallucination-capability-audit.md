# Anti-Hallucination Capability Audit (Plan vs. Repo)

Status: Diagnose-Befund (diagnose-first).
Methode: `rg`/`test -f` plus vollständiges Lesen der Kernmodule und Contracts im
Branch-Stand. Kein Planpunkt wurde als Repo-Fakt übernommen, ohne Beleg im Code,
in einem Contract oder in einer bestehenden Doku.

Zweck: Den vorgeschlagenen "Anti-Hallucination / Output-Architecture"-Plan gegen den
tatsächlichen Repo-Stand falsifizieren, Drift sichtbar machen und entscheiden, was
**reuse**, **harden**, **defer** oder **resolve** (Widerspruch auflösen) ist.

Leitbefund: Der Plan unterschätzt den Reifegrad des Repos erheblich. Ein großer Teil
seiner "Milestone A" ist bereits implementiert oder als Arbeitspaket geplant
(`docs/blueprints/lenskit-output-optimierung-v1.md`, Arbeitspakete A–H). Mehrere
"neue" Konzepte (`does_not_prove`, Authority/Canonicality, Profile, Evidence-Level,
zweistufige Health, Range-Ref v2) existieren bereits als Code, Schema oder Blueprint.
Genuin neu und wertvoll sind: **Anti-Hallucination-Lint**, **`.lenskit/` repo-declared
context**, **Retrieval-Miss-Taxonomie** und die **epistemische Korrektur**, dass
Lenskit Claims niemals automatisch als `supported/unsupported` bewerten darf.

---

## 1. Repo-Abgleich (Übersicht)

Status-Token: `DONE` = implementiert · `PARTIAL` = teilweise · `MISSING` = fehlt ·
`DRIFT` = Widerspruch/Doppelung · `UNCLEAR` = unbelegt.
Entscheidung: `reuse` · `harden` · `defer` · `resolve` · `delete`.

| # | Planpunkt | Status | Repo-Beleg (Datei:Zeile) | Halluzinationsrisiko | Entscheidung | Folge-PR |
|---|---|---|---|---|---|---|
| 1 | Reading Policy: `canonical_md` = Wahrheit, JSON = Navigation | DONE | `merger/lenskit/core/agent_reading_pack.py:13-16,411-416`; `docs/blueprints/lenskit-artifact-output-control-plane.md` §2.1; `docs/architecture/artifact-inventory.md` | niedrig | reuse | — |
| 2 | Agent Reading Pack, `authority=navigation_index`/`derived` | DONE | `merger/lenskit/core/agent_reading_pack.py:381-394`; `merger/lenskit/core/constants.py:22`; `docs/blueprints/lenskit-output-optimierung-v1.md` AP D | niedrig | reuse | — |
| 3 | `TOP_FILES`-Heading vorhanden | DONE | `merger/lenskit/core/agent_reading_pack.py:489` | mittel (Begriff "TOP" impliziert Wichtigkeit) | harden | A1 |
| 4 | `TOP_FILES` als "wichtig" beschrieben | DRIFT | **README.md:35** "die wichtigsten Quelldateien"; Pack selbst sagt "by chunk coverage" (`merger/lenskit/core/agent_reading_pack.py:489-494`) | mittel | resolve (README jetzt; Heading-Rename A1) | A1 |
| 5 | Cache/Tooling-Dirs in canonical/chunk/sqlite | DONE (exkludiert) | `merger/lenskit/core/merge.py:297-314` (`SKIP_DIRS`), Walk-Filter `merger/lenskit/core/merge.py:2277` (#681–#683) | **Plan-Beleg STALE** | reuse + harden | A2 |
| 6 | Reading Lenses markieren Cache als `core` | PARTIAL (latent) | `merger/lenskit/core/lenses.py:87` (Ultimate-Fallback `core`, keine Exclusion) — Caches erreichen Lens aber nicht (Upstream-Skip) | niedrig-latent | harden (Guard-Test) | A2 |
| 7 | `output_health=pass` trotz `redact_secrets=false` / `agent_pack=skipped` | DONE (bestätigt) | `merger/lenskit/core/output_health.py:468-469` (Redaction nur protokolliert), `:461-466` (skip = keine Warnung), `:486-491` (Verdict nur aus errors/warnings) | **hoch** (Schein-Agentensicherheit) | harden via separates Gate, **nicht** Health umbiegen | A4/A5 |
| 8 | Post-hoc Agent Bundle Validator | PARTIAL (geplant) | `merger/lenskit/core/output_health.py:424-466` (Pfad in-pipeline unset); `docs/blueprints/lenskit-artifact-output-control-plane.md` §2.4 `post_emit_health`; `docs/blueprints/lenskit-output-optimierung-v1.md` AP H; `docs/architecture/artifact-evidence-levels.md` `post_emit_validation_available` | hoch | reuse Design (`post_emit_health`), **kein** paralleles "agent-ready" | A4 |
| 9 | Safe Output Profiles / agent-safe | DRIFT (doppelt) | `docs/blueprints/lenskit-output-optimierung-v1.md` AP E (`max-private/agent-safe/public-review/ci-diagnostic`) **vs** `docs/blueprints/lenskit-artifact-output-control-plane.md` §7 (`lean-readable/agent-portable/local-search/debug-full/forensic-strict`) | mittel (Namens-Drift) | resolve (control-plane kanonisch; Plan-Namen als Intent/Alias) | A5 |
| 10 | Range-Ref v2 (Source/Artifact-Achsen trennen) | PARTIAL (Design-only) | `docs/blueprints/range-ref-v2-semantic-boundary-split-preimage.md`; `docs/architecture/range-semantics.md`; nur `merger/lenskit/contracts/range-ref.v1.schema.json`; `docs/blueprints/lenskit-output-optimierung-v1.md` AP B `[ ]` | mittel | reuse Blueprint, Feldnamen angleichen, Schema bauen | A3 |
| 11 | Authority/Canonicality-Felder | DONE | `docs/architecture/artifact-inventory.md` (Authority/Canonicality-Spalten); `merger/lenskit/contracts/bundle-manifest.v1.schema.json`; `AUTHORITY_REGISTRY` in `merger/lenskit/core/merge.py` | niedrig | reuse/normieren (nicht neu erfinden) | C1 |
| 12 | Risk Classes als explizites Feld | PARTIAL | Authority existiert; `risk_class` als Feld fehlt | niedrig | additiv aus Authority ableiten | C1 |
| 13 | Claim Boundaries / `does_not_prove` | DONE | `merger/lenskit/contracts/query-result.v1.schema.json:251-293`; `merger/lenskit/contracts/agent-query-session.v2.schema.json:57-110` (`session_authority`, `claim_boundaries.proves/does_not_prove`) | niedrig | reuse; Muster auf Pack/Context-Bundle ausweiten | A1/B3 |
| 14 | Context Bundle / Agent Session Risk-Felder | PARTIAL | `merger/lenskit/contracts/agent-query-session.v2.schema.json` DONE (`session_authority`, `context_source`, `claim_boundaries`); `merger/lenskit/contracts/query-context-bundle.v1.schema.json` hat `resolver_status`, **kein** `context_risk`/`claim_boundaries` | mittel | harden (`context_risk` in context-bundle) | B3 |
| 15 | Redaction/Profile-Mechanik | PARTIAL | `merger/lenskit/core/redactor.py` (heuristischer Redactor); `capabilities.redaction` im Manifest; **keine** Profil-Engine, die Redaction an agent-safe koppelt | mittel | reuse Redactor; Profil-Gate bauen | A5 |
| 16 | Claim-Evidence-Map mit `supported/unsupported` | DRIFT (**Widerspruch**) | `docs/blueprints/lenskit-output-optimierung-v1.md` AP F:244 ("supported/unsupported"); `docs/blueprints/lenskit-artifact-output-control-plane.md` §4 (`evidence_index`, "beweisnah"); `docs/architecture/artifact-evidence-levels.md` `forensic_strict` | **hoch** (Auto-Claim-Bewertung = Scheinsicherheit) | **resolve** (AP F umschreiben: nur Referenz, kein Verdikt) | F1–F3 |
| 17 | Anti-Hallucination Lint | MISSING (neu) | kein `anti_hallucination`/Lint-Producer im Repo | — (Schutzfehlen) | build (Kernhebel) | C2 |
| 18 | `.lenskit/` repo-declared context | MISSING (neu) | kein `.lenskit/`-Verzeichnis | — | defer hinter A–C | D1–D3 |
| 19 | Structural `repo_map.v1` | MISSING (neu) | `architecture_summary` existiert (Prosa/Diagnose), kein mechanischer `repo_map` | niedrig | defer | E1 |
| 20 | Context Quality Signals (Artefakt) | MISSING (überlappt) | überlappt `docs/architecture/artifact-evidence-levels.md`; kein `context_quality.json` | mittel (globale "Verstehens"-Ampel wäre gefährlich) | defer + scope (Projektion, keine neue Wahrheit) | B1 |
| 21 | Retrieval Miss Taxonomy | MISSING (neu) | `merger/lenskit/retrieval/eval_core.py` + `merger/lenskit/contracts/retrieval-eval.v1.schema.json`; keine Miss-Taxonomie | mittel | build über bestehendem Eval | B2 |
| 22 | Structural Architecture Signals | PARTIAL (überlappt) | `docs/blueprints/lenskit-output-optimierung-v1.md` AP G; `architecture_summary` | niedrig | in AP G falten, kein Parallelartefakt | E3 |
| 23 | `excluded_noise` als Diagnose | MISSING | Exclusion ist heute **stumm** (`SKIP_DIRS`) | niedrig | optionales Diagnose-Artefakt | A2 |
| 24 | `is_noise_file` vs `SKIP_DIRS` Listendrift | DRIFT | `merger/lenskit/core/merge.py:297-314` (hat `.ruff_cache/.pytest_cache/.mypy_cache`) vs `merger/lenskit/core/merge.py:1772-1780` (`noisy_dirs` ohne diese) | niedrig-latent | reconcile | A2 |
| 25 | Retrieval `recall@10 = 13.33` (Plan-Beleg) | UNCLEAR | im Branch **kein** committetes Eval mit dieser Zahl gefunden | — | epistemische Lücke | — |

---

## 2. Detailbefunde (mit Beleg)

### 2.1 Belegt: Reading Policy & Pack-Governance sind solide
`merger/lenskit/core/agent_reading_pack.py` markiert den Pack deterministisch als
`authority=navigation_index`, `canonicality=derived` und rendert das Banner
"**NAVIGATION, NOT TRUTH**" (`:381-394`). Die READING_POLICY ordnet Autoritäten
(`:411-416`). Der Pack erzeugt **keine** freie Architekturprosa und **keine**
Modulzweck-Behauptungen — er hat keinen `TOP_LEVEL_ARCHITECTURE`-Abschnitt.
→ Diese Substanz muss **gehärtet**, nicht neu gebaut werden.

### 2.2 Bestätigt: `TOP_FILES` ist Begriffsrisiko, vor allem in der README
Der Pack-Producer beschreibt die Tabelle korrekt als "top N **by chunk coverage**"
(`:489`) und als "Canonical spans … to read or cite a file's content precisely"
(`:491-494`) — **keine** Wichtigkeitsaussage. Risiko ist der Heading-Begriff "TOP"
plus die **README**, die explizit "die **wichtigsten** Quelldateien" sagt
(`README.md:35`). Das ist die einzige aktive, repo-belegte Importance-Behauptung.
→ README jetzt korrigieren; Heading-Rename `TOP_FILES → TOP_CHUNK_SPANS` als A1.

### 2.3 STALE: `.ruff_cache` im Output ist bereits behoben
Der Plan-Beleg (".ruff_cache landet in canonical/chunk/sqlite", "Lenses als core")
stammt aus dem Snapshot `lenskit-max-260502-1126_*` **vor** der Cache-Hygiene
(#681–#683). Aktuell exkludiert `SKIP_DIRS` (`merger/lenskit/core/merge.py:297-314`):
`.git, .idea, node_modules, .svelte-kit, .next, dist, build, target, .venv, venv,
__pycache__, .pytest_cache, .DS_Store, .mypy_cache, .ruff_cache, coverage`, und der
Walk-Filter wendet sie an (`merger/lenskit/core/merge.py:2277`).
→ Hard-Exclusion = `reuse`. Offene Härtung: (a) Guard-Regressionstest, (b)
`is_noise_file`-Liste mit `SKIP_DIRS` versöhnen (`merger/lenskit/core/merge.py:1772-1780` fehlen
`.ruff_cache/.pytest_cache/.mypy_cache`), (c) optionales `excluded_noise`-Diagnostikum.
Latentes Restrisiko: `merger/lenskit/core/lenses.py:87` fällt im Zweifel auf `core` zurück — nur relevant,
falls je eine Cache-Datei den Upstream-Skip umgeht.

### 2.4 Bestätigt: `output_health=pass` ist nicht agent-safe
`compute_output_health` bildet das Verdict ausschließlich aus `errors`/`warnings`
(`:486-491`). `redact_secrets_enabled` wird nur als Check **protokolliert**
(`:468-469`), fließt nicht ins Verdict. `agent_pack_present` ist `skipped`, wenn der
Pfad in-pipeline nicht gesetzt ist (`:461-466`), ohne Warnung. `sample_query_content_hit`
ist immer `skipped` (`:418-422`).
→ Konsequenz wie im Plan: **Health ≠ agent_ready**. Aber die richtige Schicht ist ein
separates Gate (`post_emit_health` / Profil agent-safe), **nicht** das Umbiegen von
`output_health` selbst — sonst bricht die dokumentierte Pre/Post-Health-Trennung
(`docs/blueprints/lenskit-artifact-output-control-plane.md` §2.4) und die
Parity-Gate-Semantik (`docs/roadmap/lenskit-master-roadmap.md` "Paritaetsgates").

### 2.5 Bereits vorhanden: Claim Boundaries & "does_not_prove"
Der Plan behandelt `does_not_prove` als neu. Es existiert:
- `merger/lenskit/contracts/query-result.v1.schema.json:251-293` — `claim_boundaries` mit `does_not_prove`,
  `evidence_basis`, `requires_live_check`.
- `merger/lenskit/contracts/agent-query-session.v2.schema.json:57-110` — `session_authority =
  "agent_context_projection"` ("not canonical repository content") plus
  `claim_boundaries.{proves,does_not_prove}` (beide required, `minItems:1`).
→ Das epistemische Vokabular ist da. A1/B3 weiten es **maschinenlesbar** auf den
Agent Reading Pack und das `query-context-bundle.v1` aus, statt es neu zu erfinden.

### 2.6 Widerspruch: Auto-Claim-Bewertung
`docs/blueprints/lenskit-output-optimierung-v1.md` Arbeitspaket F (`:238-247`) verlangt, pro Claim
`supported / unsupported` auszuweisen; `docs/blueprints/lenskit-artifact-output-control-plane.md` §4 listet
`claim_evidence_map` als `evidence_index`/"beweisnah"; `docs/architecture/artifact-evidence-levels.md`
macht es zur Bedingung für `forensic_strict`. Der vorgelegte Plan verbietet genau das
(Invariante 3; F3 verbietet `supported/unsupported/true/false/proven`).
→ **Auflösung zugunsten des Plans.** Lenskit darf Belege **adressieren**, nicht
**bewerten**. `supported/unsupported` ist eine LLM-/Review-Aufgabe, kein Lenskit-Output.
Arbeitspaket F wird umgeschrieben: `claim_evidence_map`/`claim_evidence_references`
liefert nur `claim → evidence_refs` plus `does_not_establish`, niemals ein Verdikt.
Das ist konsistent mit "navigation, not truth" und mit `does_not_prove` aus 2.5.

### 2.7 Bereits vorhanden: Profile, Evidence-Level, zweistufige Health
`docs/blueprints/lenskit-artifact-output-control-plane.md` definiert Profile
(`agent-portable`, `local-search`, `debug-full`, `forensic-strict`, …),
Evidence-Level (`readable`→`forensic_strict`), Capability-Matrix und das
Pre/Post-Health-Modell. `docs/architecture/artifact-evidence-levels.md` liefert die
Level→Roles→Health→agent-wording-Matrix. **Zwei** Profilnamensschemata koexistieren
(AP E vs. control-plane) — bestehende Drift, die A5 auflöst.

### 2.8 Design-only: Range-Ref v2
Es gibt `docs/blueprints/range-ref-v2-semantic-boundary-split-preimage.md` und
`docs/architecture/range-semantics.md` (canonical/source/chunk/semantic getrennt), aber nur
`merger/lenskit/contracts/range-ref.v1.schema.json`. Die Feldnamen des Plans (z. B.
`artifact_line_start`, `source_line_start`) sind nahe an Arbeitspaket B (`:140-145`);
A3 vereinheitlicht und implementiert das Schema v1-kompatibel.

---

## 3. Entscheidungslogik (was wird nicht gebaut)

- **Kein** Umbiegen von `output_health` auf Redaction-Pflicht → eigenes Gate (A4/A5).
- **Kein** paralleles "agent-ready"-Artefakt → `post_emit_health` (vorhandenes Design).
- **Kein** zweites Profil-Namensschema → control-plane-Namen kanonisch.
- **Kein** `supported/unsupported` → Referenz-only Claim-Evidence (Widerspruch gelöst).
- **Kein** globaler "understanding"-Verdict in Context-Quality → nur Signalprojektion.
- **Kein** Parallelartefakt zu `architecture_summary` → Structural Signals in AP G falten.
- **Keine** neuen Agentenintegrationen (MCP/Task Pack/Dashboard) vor C2 (Lint) + A4/A5.

---

## 4. Offene epistemische Lücken

1. `recall@10 = 13.33` ist im Branch nicht als committetes Eval auffindbar (Plan-extern).
2. Live-Branch-Diffs nach allen Merges vs. lokale Snapshots fehlen (wie in
   `docs/blueprints/lenskit-output-optimierung-v1.md` "Epistemische Leere" notiert).
3. Konsumentenstatus einiger Legacy-Rollen (`index_sidecar_json`, `dump_index_json`)
   ist noch nicht vollständig in `artifact-consumer-matrix.md` belegt → blockiert
   Deprecations.
4. Ob `query-context-bundle.v1` additiv um `context_risk` erweitert werden darf, ohne
   bestehende Consumer zu brechen, ist noch nicht durch einen Consumer-Test belegt.

---

## 5. Verweise

- Optimierte, reconciled Roadmap: `docs/blueprints/lenskit-anti-hallucination-output-architecture.md`
- Bestehende Roadmap (Arbeitspakete A–H): `docs/blueprints/lenskit-output-optimierung-v1.md`
- Master-Reihenfolge: `docs/roadmap/lenskit-master-roadmap.md`
- Profile/Evidence/Health: `docs/blueprints/lenskit-artifact-output-control-plane.md`,
  `docs/architecture/artifact-evidence-levels.md`
- Range: `docs/architecture/range-semantics.md`,
  `docs/blueprints/range-ref-v2-semantic-boundary-split-preimage.md`
