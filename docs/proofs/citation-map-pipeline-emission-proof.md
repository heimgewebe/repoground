# Citation Map Pipeline Emission Proof

- Datum: 2026-05-15
- Repo HEAD: 36553b82b201c3b6803ab6cb30e7809425b1b7df
- Dump stem: lenskit-max-260515-0952_merge
- Manifest-Pfad: /home/alex/repos/merges/lenskit-max-260515-0952_merge.bundle.manifest.json

## Output Health

- Datei: /home/alex/repos/merges/lenskit-max-260515-0952_merge.output_health.json
- verdict: pass
- errors: []
- warnings: []
- range_ref_resolution_status: ok

## Manifest-Artefaktliste (Auszug)

- canonical_md: lenskit-max-260515-0952_merge.md
- chunk_index_jsonl: lenskit-max-260515-0952_merge.chunk_index.jsonl
- citation_map_jsonl: lenskit-max-260515-0952_merge.citation_map.jsonl
- dump_index_json: lenskit-max-260515-0952_merge.dump_index.json
- derived_manifest_json: lenskit-max-260515-0952_merge.derived_index.json
- index_sidecar_json: lenskit-max-260515-0952_merge.json
- retrieval_eval_json: lenskit-max-260515-0952_merge.retrieval_eval.json
- sqlite_index: lenskit-max-260515-0952_merge.chunk_index.index.sqlite
- output_health: lenskit-max-260515-0952_merge.output_health.json

## Citation Map Presence

- role == citation_map_jsonl im Manifest: true
- authority: navigation_index
- canonicality: derived
- regenerable: true
- staleness_sensitive: true

## Designnotiz: Zweiphasige Manifest-Erzeugung

Die Pipeline-Integration ist bewusst zweiphasig:

1. write_reports_v2 schreibt ein provisorisches Bundle-Manifest ohne citation_map_jsonl.
2. Der bestehende Producer produce_citation_map() liest dieses Manifest und erzeugt citation_map_jsonl.
3. write_reports_v2 ergänzt citation_map_jsonl als Artefakt und schreibt das finale Manifest erneut atomar.

Failure-Semantik:

- Schlägt der Producer fehl, bricht der Run mit Fehler ab.
- Ein eventuell bereits geschriebenes provisorisches Manifest gilt nicht als erfolgreicher finaler Bundle-Claim.
- Die Service-/Job-Schicht darf Artefakte erst nach erfolgreichem write_reports_v2-Return als erfolgreich registrieren.

## Kohärenz-Guard für pro-repo/multi-repo Szenarien (Codex-P1)

**Problem (Codex-P1):** In `mode='pro-repo'` mit `output_mode='dual'` kann das provisorische Manifest ein inkohärentes Paar enthalten:
- `final_canonical_md` = erstes Markdown aus `verified_md` (repoA)
- `final_chunk_index` = letzter chunk_index (repoB oder später)

Das Manifest paart dann repoA-Markdown mit repoB-Chunks, und der Producer schlägt mit "range.file_path does not match manifest canonical_md path" fehl.

**Lösung:** Gehärteter Kohärenz-Guard vor Producer-Aufruf

Die neue Funktion `check_manifest_coherence_for_citation_map()` in `merger/lenskit/core/citation_map.py`
liefert ein strukturiertes Ergebnis `CitationMapCoherence` mit:
- `coherent`
- `skip_allowed`
- `reason`

Sie prüft:
1. Manifest hat canonical_md und chunk_index_jsonl Artefakte
2. Beide Pfade sind sicher/normalisierbar
3. Alle Chunks referenzieren denselben normalisierten `canonical_range.file_path` wie das normalisierte `canonical_md.path`
4. Wenn chunk_index_jsonl leer ist, gilt das als kohärent (keine Chunks zum Matchen)

**Verhalten:**
- **Kohärent (`coherent=True`):** produce_citation_map() wird ausgeführt, citation_map_jsonl wird in Manifest eingetragen
- **Inkohärent aber erlaubt (`skip_allowed=True`, `reason=range_file_path_mismatch`):** produce_citation_map() wird bewusst übersprungen
- **Defekt (`skip_allowed=False`):** harter Fehler in write_reports_v2 (z. B. invalid JSONL, fehlende Artefakte, unsichere Pfade, unlesbare chunk_index)
- **Producer-Fehler bei kohärentem Manifest:** bleibt harter Fehler

Dies ermöglicht es:
- Gesamt/Dual Bundles können weiterhin automatisch citation_map_jsonl erzeugen
- Pro-repo Szenarien mit inkohärentem Manifest schlagen nicht fehl
- Per-repo Citation Maps sind ein Folgepunkt, nicht Teil dieses PRs

**Regressionstest (realer Codex-P1-Pfad):**
- `merger/lenskit/tests/test_per_repo_cohesion.py::TestPerRepoCohesion::test_pro_repo_multi_repo_skips_citation_map_for_incoherent_manifest`
- Führt tatsächlich `write_reports_v2(..., mode="pro-repo", output_mode="dual")` mit mehreren Repos aus
- Verifiziert: Run ohne Exception, inkohärenter Aggregate-Manifest-Fall wird als `range_file_path_mismatch` erkannt, `citation_map_jsonl` wird für das Aggregate-Manifest nicht emittiert

## Count-Konsistenz

- citation_map_row_count: 613
- chunk_index_row_count: 613
- Ergebnis: gleich

## SHA/Bytes-Proof (citation_map_jsonl)

- Datei: /home/alex/repos/merges/lenskit-max-260515-0952_merge.citation_map.jsonl
- manifest bytes: 358146
- actual bytes: 358146
- manifest sha256: 53e72777e00c3b2d03bec8aaa34882f623390a772a611289ba3b59e9bbc8cf33
- actual sha256: 53e72777e00c3b2d03bec8aaa34882f623390a772a611289ba3b59e9bbc8cf33
- Ergebnis: identisch

## Canonical MD SHA Link

- canonical_md manifest sha256: ab0d6aadf9421dd8b1e0fa6d4b5137ed04871d1ccdbcb8a40e0c40de962fff03
- citation snapshot canonical_md_sha256: ab0d6aadf9421dd8b1e0fa6d4b5137ed04871d1ccdbcb8a40e0c40de962fff03
- Ergebnis: identisch

## Validator-Ergebnis

Befehl:

```bash
python3 -m merger.lenskit.cli.main citation validate \
  /home/alex/repos/merges/lenskit-max-260515-0952_merge.bundle.manifest.json --json
```

Ergebnis:

- status: ok
- error_kind: ok
- citation_id_count: 613
- citation_id_duplicate_count: 0
- canonical_range_hash_ok_count: 613
- errors: []

## Schema-Validierung

Befehl: Zeilenweise JSON-Schema-Validierung gegen merger/lenskit/contracts/citation-map.v1.schema.json

Ergebnis:

- schema_validated_rows: 613
- Fehler: keine

## Runtime-Artefakt-Regression

- Prüfung: Kein strukturierter Pfad unter .claude/worktrees in Citation Map oder Manifest.
- Ergebnis: keine Treffer.

## Commit-Hygiene

- Es wurden keine Dateien aus /home/alex/repos/merges committed.
- Es wurden keine lokalen Runtime-Dateien wie .claude/settings.local.json oder .claude/worktrees committed.
