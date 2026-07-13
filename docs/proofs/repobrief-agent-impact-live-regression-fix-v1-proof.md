# RepoBrief Agent Impact – Live-Regression-Fix v1

## Ausgangsbefund

Die erste commitgebundene Live-Kalibrierung auf Lenskit, Grabowski und
Weltgewebe ergab:

- Baseline Target Recall: `1.0`
- Impact Target Recall: `0.6666666666666666`
- Delta: `-0.33333333333333337`
- `no_case_regression=false`
- `default_promoted=false`

Der Grabowski-Fall fragte nach
`src/grabowski_job_finalizer.py`. Die bestehende read-only Suche lieferte den
realen Test `tests/test_job_finalizer.py`; die Impact-Fläche erzeugte dagegen
nur konventionell geratene Pfade wie
`tests/test_grabowski_job_finalizer.py`.

Die Ausgangsevidenz liegt im Bureau unter:

- `docs/evidence/rcga-live-goldset-20260713.json`
- `docs/evidence/rcga-live-evaluation-20260713.json`
- `docs/evidence/rcga-live-calibration-receipt-20260713.md`

Bureau-Task: `RCGA-V1-T003`.

## Reparatur

### Resolved-query-Testevidenz

`agent_impact_refinement.py` liest ausschließlich die bereits aufgelöste
`source_citation_projection` des bestehenden read-only Query-Ergebnisses.
Testartige, sichere repository-relative Pfade werden als
`evidence_type=resolved_query` ergänzt.

Die Kandidaten behalten:

- `citation_id`
- `source_range`
- `range_status`
- `authority=resolved_navigation_evidence`
- `canonicality=derived`

Sie werden ausdrücklich nicht als Graphkante, Laufzeitabhängigkeit,
Testabdeckung oder Testhinlänglichkeit dargestellt.

Liegt mindestens ein aufgelöster Testpfad vor, werden bloß konventionell
geratene Testkandidaten unterdrückt. Ohne `resolved_query`-Treffer bleiben
Heuristiken als sichtbar schwächerer Fallback erhalten. Die Ausgabe dokumentiert
die Zahl der unterdrückten Heuristiken in `composition`.

### Pfadhygiene

Pfadsegmente werden vor jeder `PurePosixPath`-Normalisierung geprüft. Der
Evaluator und die Refinement-Schicht entfernen beziehungsweise verwerfen:

- leere Pfade;
- absolute Pfade;
- Backslash- oder Doppel-Slash-Mehrdeutigkeiten;
- rohe `.`-Segmente am Anfang, in der Mitte oder am Ende;
- `..`-Segmente.

Damit kann eine Pfadbibliothek verbotene Eingaben nicht unbemerkt in scheinbar
kanonische Pfade umwandeln.

### Kontextkompression

Zusätzlich zum Recall werden gemessen:

- Kontextpfade pro Fall;
- mittlere Baseline- und Impact-Kontextgröße;
- aggregierte Kontextpfadreduktion.

Nutzwert kann nur festgestellt werden, wenn kein Fall beim Recall regressiert
und entweder:

1. der registrierte Recall-Vorteil erreicht wird; oder
2. bei gleichem oder besserem Recall mindestens 20 Prozent Kontextpfade
   eingespart werden.

`default_promoted` bleibt unabhängig vom Ergebnis `false`.

## Kanonischer Regression-Replay

Der vorab fixierte Drei-Repository-Goldset wurde mit denselben Zielcommits und
denselben erwarteten Testpfaden erneut ausgeführt. Geändert wurde nur die zu
prüfende RepoBrief-Implementierung.

### Bindung

- Lenskit PR: `#996`
- PR-Quellhead beim Lauf: `38e779e1391d49655368766f86e02e4ceae30847`
- GitHub-PR-Merge-Ref beim Lauf: `1245b59313748088df6a7c18f159257d724a0a7d`
- Workflow-Run: `29234901905`
- Actions-Artefakt: `8273035636`
- Artefakt-Digest: `sha256:9cca7f74c3c46913f664bde5e069cb76bdac9f2e4e9cdca9d0f38ddd0945b7d4`
- Goldset SHA-256: `08bf2e0a508a033e6f6d0c038375860c0a1db5510dd4dab9f7965644185d8a3a`
- Rohbeobachtungen SHA-256: `8853366f1f09c167cb5708dc8075ba7b97b6fcdd0083016541c922eced261661`
- Evaluation SHA-256: `b5f081834138b1d838b2a72183c5c22fbd7f3e805af02e4e98f8a20f7e344e88`

Der GitHub-Merge-Ref ist der von Actions ausgecheckte, konfliktfrei aus
aktuellem `main` und PR-Head erzeugte Testbaum. Nach dem Lauf änderten sich nur
Messinstrumente und Evidenzdokumente. Ein Commitvergleich bis zum bereinigten
Produktkandidaten zeigte keine Änderung an Evaluator, Refinement oder Adapter.

### Zielrepositories

| Repository | Commit | Manifest SHA-256 | Run-ID | Canonical-Digest |
|---|---|---|---|---|
| `heimgewebe/lenskit` | `456d37bd142349bc0c04925d87934eefbbc546ac` | `adea5e5f7d1f1ec49285e5f4e36a80b8a601af1673c7db06340af1ba8c6210a3` | `lenskit-full-max-260713-0817` | `e1bd8223cb9121166a57d9a746c7e809c2cfea4e569e20587ce64ff5e321572b` |
| `heimgewebe/grabowski` | `f6eed48752fd2cf32f070dc69b2112e2498872cb` | `0b5bf85913d2f587617291689e5c4e8c88b6211d939c2f51d04b898111ee8a39` | `grabowski-full-max-260713-0818` | `34e99958fbad4eaeaf41034a3b28824a484fa66e6b85200467281c6cb42ecc29` |
| `heimgewebe/weltgewebe` | `e095903bb71c937d861fa64d7e8a6b593062ca6f` | `da6fc7d435fa73a4db9571bd2882577920a17972cd3a5597399937388d74d9d6` | `weltgewebe-full-max-260713-0818` | `1016cd7bd98c5bc6a6f3efb2b6f0b2ffb41802374cd3ce2e2b0401987cb6664a` |

Alle drei Bundles waren kohärent. Die Kernartefakte waren verfügbar. Zwei
Impact-Aufrufe je Fall waren bytegleich, und alle drei Zielrepositories blieben
nach Bundle-Erzeugung und Abfragen `git status --porcelain`-sauber.

## Ergebnis

| Fall | Recall Baseline → Impact | Pfade Baseline → Impact | Reduktion |
|---|---:|---:|---:|
| Lenskit | `1.0 → 1.0` | `11 → 6` | `45.45 %` |
| Grabowski | `1.0 → 1.0` | `11 → 5` | `54.55 %` |
| Weltgewebe | `1.0 → 1.0` | `10 → 5` | `50.00 %` |

Aggregiert:

- Baseline Target Recall: `1.0`
- Impact Target Recall: `1.0`
- `no_case_regression=true`
- mittlere Baseline-Kontextpfade: `10.666666666666666`
- mittlere Impact-Kontextpfade: `5.333333333333333`
- aggregierte Kontextpfadreduktion: `0.5`
- registrierte Mindestkompression: `0.2`
- Nutzenpfad: `fixed_goldset_compression_threshold_met_at_equal_or_better_recall`
- `navigation_utility_established_for_goldset=true`
- `default_promoted=false`

Der reale Grabowski-Test `tests/test_job_finalizer.py` erscheint wieder im
Impact-Kontext und ist ausdrücklich als `resolved_query` belegt. Damit ist die
konkrete Live-Regression geschlossen.

Dauerhafte Evidenz im Repository:

- `docs/retrieval/repobrief_agent_impact_live_goldset.rerun.v1.json`
- `docs/diagnostics/repobrief-agent-impact-live-rerun-v1.json`

Die vollständigen Rohbeobachtungen umfassen rund 190 KB und mehr als 5.000
Zeilen. Sie werden nicht in die Reviewfläche aufgenommen, sondern über den
oben gebundenen Actions-Artefakt-Digest und ihren eigenen SHA-256 verifiziert.

## Unabhängige Produktstand-Bestätigung

Ein zweiter, parallel erzeugter Lauf prüfte denselben Goldset mit dem neueren
Implementierungsstand `bc4afc2e4f4d826f0a8c4a764de8f6bf32275802` und einer
strengeren Projektion, die nur tatsächlich im Zielrepository vorhandene Pfade
zählte.

- Workflow-Run: `29234901915`
- Kalibrierungsjob: `rcga-live-calibration` — `success`
- Actions-Artefakt: `8273044862`
- Artefakt-Digest: `sha256:ab72636983fcfeffa1399d58485089fdb38cb7230d3a0219efe47f3af079a0cf`
- Recall: `1.0 → 1.0`
- `no_case_regression=true`
- Kontextpfadreduktion: `32 %`
- registrierte Schwelle: `20 %`
- `default_promoted=false`

Dieser Lauf ist eine unabhängige Robustheitsbestätigung. Seine abweichende
Kompressionszahl entsteht aus einer anderen, strengeren Pfadzählung. Er ersetzt
nicht den kanonischen Regression-Replay und erzeugt keine zweite
Dokumentationswahrheit.

## Tests

Der Slice testet:

- Übernahme des realen Grabowski-artigen Testpfads aus der Query-Projektion;
- Erhalt von Citation- und Range-Metadaten;
- getrennte Evidenzklassen und deterministische Reihenfolge;
- Adapterintegration ohne Write-Surface;
- Unterdrückung bloßer Heuristiken nur bei vorhandener stärkerer Testevidenz;
- Erhalt heuristischer Fallbacks ohne aufgelösten Testtreffer;
- Ablehnung roher Punkt- und Parentsegmente vor Normalisierung;
- Filterung leerer und unsicherer Pfade;
- Kompressionsnutzen bei recall-gleicher Ausgabe;
- Blockierung eines Nutzenurteils bei Recall-Regression trotz hoher
  Kompression;
- aktualisierten synthetischen Goldset- und Diagnosevertrag;
- den festen Drei-Repository-Livererun.

## Einordnung

**Belegt:** Auf diesem vorab fixierten Live-Goldset hält die Impact-Fläche den
vollständigen Recall und reduziert die gemessene Kontextpfadmenge je nach
strenger Zählmethode um `32 %` bis `50 %`. Die frühere Grabowski-Regression ist
behoben.

**Plausibel:** Die kompaktere, evidenzgetrennte Erstleseliste kann Agenten bei
der Navigation Zeit und Kontext sparen.

**Nicht belegt:** allgemeine Agentenverbesserung, Antwortkorrektheit,
vollständige Call- oder Testbeziehungen, Testhinlänglichkeit,
Reviewvollständigkeit, Merge-Reife oder Standardbeförderung. Die Fläche bleibt
opt-in; eine Standardentscheidung benötigt einen getrennten breiteren
Agenten-Benchmark.
