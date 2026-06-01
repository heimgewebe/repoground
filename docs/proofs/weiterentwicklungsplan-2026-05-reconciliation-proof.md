# Weiterentwicklungsplan 2026-05 — Reconciliation Proof

> Aktualisiert am 2026-05-31.
> Scope: **diagnose-only** Abgleich eines extern erstellten „Plan für die
> Weiterentwicklung von Lenskit" gegen den tatsächlichen Branch-Stand.
> Dieses Dokument **implementiert keine** der dort gelisteten Großfeatures und
> ersetzt **keine** Fachblueprints. Es ordnet den externen Plan ein, korrigiert
> veraltete Annahmen mit Datei-Beleg und destilliert den echten Rest.

## 0. Kernbefund (TL;DR)

Der eingereichte Plan ist **als Selbstbeschreibung nützlich, als Lückenliste
aber überwiegend veraltet**: er beschreibt einen Snapshot, der dem aktuellen
Branch deutlich hinterherhinkt. Von den 12 in §2.1/§3.1 als „fehlend/offen"
markierten **Code**-Punkten sind nach Datei-Prüfung **8 vollständig umgesetzt
und getestet**, **3 partiell** (v1 fertig, deklarierter v2-/Hardening-Rest offen)
und **1 echt offen** (Schema-Caching im Range-Resolver — mit diesem PR erledigt).

Die in §2.2/§3.3 gelisteten **Dokumentations**-Lücken sind dagegen **real und
treffend**: `GETTING_STARTED`, `CONTRIBUTING`, `CHANGELOG`, Glossar und FAQ
fehlten tatsächlich. Genau diese werden mit diesem PR ergänzt — das ist der
hochwertige, risikoarme Teil des Plans.

**Konsequenz:** Die offene Roadmap blind „abzuarbeiten" hieße, vorhandene,
getestete Features neu zu bauen. Der angemessene Schritt ist Korrektur +
Doku-Schließung, nicht Re-Implementierung.

## 1. Prüfgrundlage

Geprüft im Branch `claude/great-lovelace-HB1yv` per `test -f`, `rg`/`grep` und
Test-Lauf (`pytest`). Belegzeilen sind first-hand verifiziert. Methode und
Sprache folgen `docs/roadmap/lenskit-master-roadmap.md` (Abschnitt
„Prüfgrundlage"). Statusmodell wie dort: `none | partial | done`.

## 2. Befund: Code-Lücken (§2.1 / §3.1)

| # | Plan-Behauptung („fehlt/offen") | Realer Status | Beleg (first-hand) |
| --- | --- | --- | --- |
| 1 | Super-Merger-Extras nicht implementiert; Coverage/Meta-Density fehlen | **done** | `core/merge.py:458` `class ExtrasConfig` (7 Flags), `:1169` `_build_extras_meta()`, `:3709` Emission ins `@meta`; Coverage `:3630`/`:3863`; Meta-Density-Header `:3538`; CLI `--json-sidecar` `frontends/pythonista/repolens.py:3383` |
| 2 | Range-Ref v2 + Schema nicht implementiert; v1 erzeugt Fehlzitate | **done** | `contracts/range-ref.v2.schema.json`; `core/range_resolver.py` Symbol `build_explicit_range_ref_v2` (aktuell `:71`), `build_derived_range_ref_v2` (aktuell `:131`), v2-Auflösungspfad inkl. v1-Legacy-Alias-Konsistenzprüfung (`_ensure_legacy_alias`, aktuell `:211 ff.`); Tests `test_range_resolver.py`, `test_range_ref_backwards_compat.py` |
| 3 | output_health.json unvollständig, keine CI-Durchsetzung | **done** (eigener Gate-Step bewusst nicht separat) | `core/output_health.py:255` `compute_output_health`, Checks `fts_content_non_empty` `:159`, `canonical_md_hash_ok` `:309`, `range_ref_resolution_ok`; `contracts/output-health.v1.schema.json`; `tests/test_output_health.py`. CI: `validate-merges.yml`, `contracts-validate.yml`; Parity-Gate prüft `output_health.verdict==pass` (s. Master-Roadmap „Paritaetsgates") |
| 4 | Meta-Density `auto` offen | **done** | `core/merge.py:2617` `_resolve_effective_meta_density` (`:2630` `auto` → `standard` bei aktivem Filter, sonst `full`); Default `auto` in `repolens.py:3384`; `tests/test_meta_density.py` |
| 5 | Range-Resolver-Caching fehlt (Manifest/Schema pro Chunk neu) | **offen → mit diesem PR erledigt (Schema)** | vorher `core/range_resolver.py:_load_schema` ohne Cache; jetzt `@lru_cache`. **Manifest**-Cache bewusst **nicht** (pro Bundle variabel, Invalidierung riskant am Citation-Fundament) |
| 6 | Semantic Re-Ranking nur konzeptionell | **done** | `retrieval/query_core.py` (Lexical-Kandidaten → Embedding-Rerank, local `all-MiniLM`); `contracts/embedding-policy.v1.schema.json` (`fallback_behavior`); Gold-Queries `docs/retrieval/queries.v1.json`; Tests `test_eval_semantic.py`, `test_graph_rerank.py`, `test_embedding_policy_schema.py` |
| 7 | Cross-Repo Federation nicht umgesetzt | **done; Hardening offen** | `core/federation.py`, `retrieval/federation_query.py`, `cli/cmd_federation.py`; Contracts `federation-index/cross-repo-links/federation-conflicts/federation-trace.v1`; viele `test_federation_*`. Roadmap **Phase 4**: Identity-/Conflict-Hardening bleibt offen |
| 8 | UI/Service-Track + rLens-CLI-Client offen | **done** | `service/app.py` (Jobs/Artifacts/Query/Atlas/Federation-Endpoints), `docs/service-api.md`; rLens-CLI-Client **umgesetzt** (Blueprint überholt): `cli/cmd_rlens_client.py` + `test_cli_rlens_client.py` |
| 9 | Graph Runtime / Retrieval-Graph fehlt | **done** | `architecture/graph_index.py`, `import_graph.py`, `entrypoints.py`; Contracts `architecture.graph.v1`, `architecture.graph_index.v1`; in `query_core.py` ins Reranking integriert; `test_graph_*` |
| 10 | Agent Reading Pack v2 (Arch-Summary, Entrypoints, Contract-Map, Drift, Claim-Evidence-Map) | **partial** | v1 vollständig (`core/agent_reading_pack.py`, `EPISTEMIC_EMPTINESS` `:536`); `architecture_summary`-Rolle `:376` vorhanden; `claim_evidence_map` **Surface-Parity-Fix 2026-06-01**: Producer und Contract existierten bereits; Registry-Pfad wurde aus Package-Installationspfad (`__file__`) abgeleitet statt aus dem gescannten Quellrepo → Single-Repo-Bundles mit Registry emittieren jetzt `claim_evidence_map_json`; Agent Reading Pack zeigt Summary statt epistemischer Leerstelle. Multi-Repo bleibt out of scope. v2-Rest (architecture_summary, contract-map) weiterhin offen. |
| 11 | Governance L1/L2/L4 + `forensic_strict` offen; `allowed/forbidden_inferences` fehlen | **partial** | L3/L5 contract-statisch **done+blockierend** (`core/anti_hallucination_lint.py`, CI `anti-hallucination-lint.yml`); L1/L2/L4 AST **marker-gated/experimentell/non-blocking** (`core/anti_hallucination_ast_lint.py`, Tracks C2.7–C2.9). `allowed/forbidden_inferences` **bereits** in 4 Contracts (`context-quality.v1`, `retrieval-eval.v1`, `post-emit-health.v1`, `agent-export-gate.v1`). `forensic_strict` in `docs/architecture/artifact-evidence-levels.md:15` definiert; Vorbedingung `claim_evidence_map` ist mit Surface-Parity-Fix (2026-06-01) für Single-Repo-Bundles erfüllt — CI-Promotion bleibt separater PR. |
| 12 | Atlas Snapshots/Deltas/History unimplemented | **partial** | Snapshots+Deltas **done** (`atlas/registry.py`, `atlas/diff.py` `compute_snapshot_delta`, Contracts `atlas-snapshot.v1`/`atlas-delta.v1`, viele `test_atlas_*`); History-Views/Cross-Machine-Aggregation + Hardening **partiell** (`docs/proofs/atlas-blueprint-audit.md`) |
| — | Parity-Guard erweitern + CI | **done** | `tools/parity_guard.py` (AST: Model/CLI/HTML/JS), CI `parity_check.yml` + `parity-gate.yml`, `tests/test_parity_guard.py`, `test_parity_compliance.py` |

## 3. Befund: Dokumentations-Lücken (§2.2 / §3.3)

| Plan-Punkt | Status vor PR | Maßnahme |
| --- | --- | --- |
| Getting-Started-Anleitung | **fehlte** | **neu:** `docs/GETTING_STARTED.md` |
| Contribution-Guidelines | **fehlte** | **neu:** `CONTRIBUTING.md` |
| Changelog/Release-Notes | **fehlte** | **neu:** `CHANGELOG.md` (Keep-a-Changelog, „Unreleased" + Baseline) |
| Glossar | **fehlte** | **neu:** `docs/glossary.md` |
| FAQ | **fehlte** | **neu:** `docs/FAQ.md` |
| Konsolidierte Master-Roadmap | **existiert bereits** | `docs/roadmap/lenskit-master-roadmap.md` — Plan-Punkt erledigt |
| Architektur-Überblick | **existiert bereits** | `docs/architecture/system-map.lenskit.md` (kompakte Systemkarte); aus den neuen Docs verlinkt |
| UI-Doku (rLens-Parameter) | **partiell** | `docs/service-api.md` + `docs/PARITY_GUARD.md` vorhanden; dedizierte Bedien-/Screenshot-Doku bleibt offen (nicht autonom erzeugbar) |
| Mehrsprachigkeit (EN) | offen (Backlog) | bewusst nicht in diesem PR; Repo ist primär deutsch |

## 4. Befund: „Inspiration" (§3.2)

Backlog-/Visionscharakter, kein akuter Mangel; teils bereits angelegt:
Embedding-Query-API ≈ vorhandene Semantic-Retrieval-Pipeline (§2 Zeile 6);
Dependency-Graphen ≈ `architecture/import_graph.py`; Ruff bereits CI-Gate
(mypy nicht). Interaktive Explorer-UI, Heatmap-Visualisierung, Plugin-API,
verteiltes Processing (Ray), Knowledge-Graph-Integration und i18n bleiben
große, separat zu beplanende Vorhaben — kein Bestandteil dieses PR.

## 5. Optimierter, repo-geerdeter Rest-Plan

Statt einer konkurrierenden Roadmap (die Master-Roadmap verbietet
„Blaupausen-Megafusion") wird der **echte** Rest auf bestehende Tracks gemappt:

| Rest-Aufgabe (real offen) | Track in Master-Roadmap | Priorität |
| --- | --- | --- |
| Range-Resolver Schema-Caching | (Perf, Phase 1-nah) | **erledigt (dieser PR)** |
| Agent Reading Pack v2 / `claim_evidence_map` (Arbeitspaket F) | Phase 5 (Agent Control Surface) | `claim_evidence_map` Surface-Parity **erledigt (2026-06-01)**; v2-Rest (architecture_summary, contract-map) weiterhin offen |
| `forensic_strict` scharf schalten (hängt an `claim_evidence_map`) | Track C / Phase 5 | Single-Repo-Vorbedingung erfüllt; CI-Promotion separater PR |
| Governance L1/L2/L4 inferenzbasiert (FP-Rate messen vor CI-Promotion) | Track C (C2.10+, C4) | mittel — bereits präzise getrackt |
| Federation Identity-/Conflict-Hardening | Phase 4 | mittel (erst nach lokaler Evidence-Stabilität) |
| Atlas History-Views + Hardening | Paralleltrack Atlas | niedrig–mittel |
| Manifest-Caching im Resolver (über Schema hinaus) | (Perf) | niedrig (Invalidierung am Citation-Fundament sorgfältig prüfen) |
| Kern-Docs EN / UI-Bedien-Doku | Doku-Backlog | niedrig |

Reihenfolge bleibt an die Master-Roadmap-Konfliktauflösung gebunden:
Range/Citation-Fundament vor Query/Agent/Federation/UI; Semantic/Reranking erst
nach Belegadressierung (bereits eingehalten).

## 6. Dokumentations-Drift-Befunde (Nebenprodukt)

Zwei interne Docs widersprechen dem Code und sollten korrigiert werden:

1. **`merger/lenskit/repoLens-spec.md` (v2.4):** Abschnitt
   „### TODO: Super-Merger / Extras" listet `ExtrasConfig` weiterhin als
   *umzusetzen*, obwohl `core/merge.py:458` es vollständig implementiert.
   Empfehlung: als „implementiert (2026-05)" markieren statt als TODO führen.
   *(In diesem PR nicht editiert — normative Spec-Änderung gehört in einen
   eigenen, fokussierten PR; hier nur als Drift dokumentiert.)*
2. **`docs/architecture/system-map.lenskit.md` (Abschnitt 3 „Bekannte Lücken"):**
   behauptete, Föderations-Module „existieren derzeit nicht im Quellbaum",
   obwohl `core/federation.py` u. a. vorhanden sind. **Mit diesem PR korrigiert**
   (minimaler, belegter Eintrag konsistent zur Master-Roadmap Phase 4).

## 7. Was dieser PR tut / bewusst nicht tut

**Tut:**
- diese Reconciliation (Diagnose + optimierter Rest-Plan);
- fünf reale Onboarding-Docs (`GETTING_STARTED`, `CONTRIBUTING`, `CHANGELOG`,
  `glossary`, `FAQ`) + README-Verlinkung;
- **eine** sichere Code-Optimierung: `@lru_cache` für `_load_schema` im
  Range-Resolver (verhaltensgleich; +2 Tests);
- minimaler Drift-Fix in `system-map.lenskit.md`.

**Tut bewusst nicht** (STOP):
- **keine** Re-Implementierung bereits fertiger Features;
- **keine** Großfeatures ohne eigene Diagnose/Proof (Pack v2, AST-L1/L2/L4-CI,
  Federation-Hardening, Atlas-History) — Repo-Kultur ist „erst diagnostizieren,
  dann ändern; keine Heuristik-Patches ohne Target-Proof";
- **keine** Spec-Mutation (nur Drift-Hinweis);
- **kein** Manifest-Cache am Citation-Fundament (Invalidierungsrisiko);
- **keine** EN-Übersetzung / UI-Screenshot-Doku in diesem PR.

## 8. Validierung

- `pytest merger/lenskit/tests/test_range_resolver.py` + range-ref-Suiten:
  **31 passed** (inkl. 2 neue Caching-Tests).
- Range-Resolver-Änderung verhaltensgleich: bestehende Resolver-/Backcompat-/
  Roundtrip-Tests unverändert grün.
- Neue Docs sind reine Markdown-Additionen (keine Runtime-/Schema-/CI-Berührung
  außer dem Caching-Patch).
