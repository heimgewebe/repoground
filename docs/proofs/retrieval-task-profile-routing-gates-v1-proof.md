# Retrieval task-profile routing gates v1 — proof

## Gegenstand

Bureau-Task `REPOGROUND-AGENT-UTILITY-V1-T013` verlangt eine gemeinsame,
revisionsgebundene Entscheidungsfläche für widersprüchlich wirkende
Retrievalwerte. Dieser Slice ändert keine Runtime-Route. Er führt vorhandene
Messungen mit expliziten Taskprofilen, Quellenbindungen, fehlenden Metriken und
fail-closed Entscheidungen zusammen.

## Warum 5 Prozent und 95 Prozent kein Widerspruch sind

Die Werte messen nicht denselben Systemzustand:

| Wert | Taskprofil / Route | Dataset | Commit | Bedeutung |
|---|---|---|---|---|
| `5 %` | Review-nahe Fragen über `default_lexical` | `review_queries.v1.json`, 20 Fragen | `8f24c2ab55a86a315b5066b4f399c3a1a9fd10f3` | Fragen-Recall@10 des damaligen kanonischen Standardretrievers; Einzelziel-Recall nur `1,666667 %`. |
| `95 %` | `review` über opt-in `review_intent_v1` | derselbe Goldstandard, anderer Snapshot und Router | `43d97b2b7cd26d7cc1d5ce2cc53df8a4f2eb8912` | Fragen-Recall@10 eines spezialisierten Kandidaten; Expected-Target-Recall `45 %`. |

Damit ist die Differenz real, aber nicht als zeitgleicher A/B-Vergleich des
aktuellen Defaults interpretierbar. Route, Repositorycommit, Bundle, Index und
Evaluator unterscheiden sich. Insbesondere beweist der 95-Prozent-Wert weder
Reviewvollständigkeit noch eine heutige Default-Eignung.

## Vertrag und Evaluator

- `retrieval-task-profile-routing.v1.schema.json` verlangt für jede Messung
  Dataset, Repositorycommit, Bundlemanifest, Index, Evaluator und
  Quellartefakt. Lokal vorhandene Artefakte sind bytegebunden; externe
  Artefakte können ausschließlich als `digest_bound` erscheinen.
- Alle acht Metrikfelder sind obligatorisch sichtbar: Recall@k, MRR,
  Expected-Target-Recall, Citation- und Range-Gesundheit, Miss-Taxonomie,
  Kontextbytes und Toolaufrufe. Nicht gemessene Werte stehen als `null`; sie
  dürfen nicht stillschweigend zu Erfolg umgedeutet werden.
- `task_profile_routing.py` entscheidet getrennt für
  `basic_repo_question`, `review`, `change_impact`, `find_relevant_tests` und
  `ground_claim`.
- Eine vollständig bestandene Profilmessung kann nur mit
  `promotion_authority=explicit_profile_decision` als `promote` erscheinen.
  Teilmessungen bleiben `keep_opt_in`; fehlende oder schwache Messungen werden
  `blocked`.
- Der globale Ausgang ist unveränderlich
  `no_global_promotion_by_aggregation`; die Auswertung besitzt keine
  Routing-Mutationsautorität.

## Revisionsgebundene Eingangsevidenz

Basiscommit dieses Slice:

```text
271076c8b5e625a079d68e8d92ce3489b9ef15ad
```

Gebundene Primärartefakte:

- kanonische 5-Prozent-Messung:
  `docs/diagnostics/repobrief-canonical-retrieval-measurement-20260711.json`,
  SHA-256 `7b84f339353e861f74c8498638359b2b16ee23eb190be63f8a90cd6bea5b7eca`;
- Review-Intent-Entscheidung mit 95 Prozent:
  `docs/diagnostics/retrieval-v2-default-promotion-decision-20260708T152502Z.json`,
  SHA-256 `3af0571fc2822cf09e6d879aa3ea9d0956c07c478287105dde7927084b9955ea`;
- Drei-Repository-Change-Impact-Rerun:
  `docs/diagnostics/repobrief-agent-impact-live-rerun-v1.json`,
  SHA-256 `7ae707404d0149d521284e28c31052b1f8689594f4a0ee022e19ecdb9847c222`;
- Multi-Repository-Agenten-Taskset:
  `docs/retrieval/repobrief_agent_benchmark_taskset.v1.json`,
  SHA-256 `2d8a4ca3c32f8f5ab592387b5f645db8e8527cb624238c20a1da64a5e7221887`;
- zusammengesetztes Taskprofil-Goldset:
  `docs/retrieval/task-profile-routing-goldset.v1.json`,
  SHA-256 `f732187ed172d8f0a5783db9e54b15e7dc92ae9c1e1cc3df6af94f163ea6b7c7`.

## Repräsentative Messabdeckung

Das zusammengesetzte Goldset bindet drei Repositories und alle fünf
Taskprofile. Es verschleiert nicht, dass einzelne Metriken aus verschiedenen,
revisionsgebundenen Teilmessungen stammen. Seine `measurement_coverage`
verweist jede Pflichtmetrik auf mindestens eine Messung mit einem tatsächlich
nichtleeren Wert. Unbekannte Messungs-IDs oder `null`-Werte werden vom
semantischen Validator abgewiesen.

| Pflichtmetrik | Gebundene Messung | Wert / Ableitung |
|---|---|---|
| Recall@k | kanonische Reviewmessung, Review-Intent, Change-Impact | `0,05`, `0,95`, `1,0` |
| MRR | kanonische Reviewmessung, Review-Intent | `0,05`, `0,375119…` |
| Expected-Target-Recall | kanonische Reviewmessung, Review-Intent, Change-Impact | `0,016667`, `0,45`, `1,0` |
| Citation-Gesundheit | Review-Intent | `1,0` als normalisierter Passindikator des kombinierten Gates `range_citation_health_ok_if_supplied`, kein unabhängiger kontinuierlicher Score |
| Range-Gesundheit | Review-Intent | `1,0` als derselbe normalisierte Passindikator, kein unabhängiger kontinuierlicher Score |
| Miss-Taxonomie | alle drei gemessenen Slices | explizite Zähler beziehungsweise leeres Mapping bei null Misses |
| Kontextbytes | Change-Impact | `711` Bytes: kompakte UTF-8-JSON-Projektion der drei emittierten Impact-Pfadlisten |
| Toolaufrufe | Change-Impact | `6`: zwei deterministische Impact-Aufrufe für jeden der drei Fälle |

Diese Abdeckung beweist keine gleichmäßige Messvollständigkeit pro Profil. Sie
belegt, dass der gemeinsame Vertrag jede geforderte Metrik tatsächlich trägt
und fehlende profilbezogene Werte sichtbar lässt.

## Profilentscheidungen

| Taskprofil | Kandidat | Ergebnis | Grund |
|---|---|---|---|
| `basic_repo_question` | `default_lexical` | `blocked` | Recall-, MRR- und Einzelzielgate werden verfehlt. |
| `review` | `review_intent_v1` | `keep_opt_in` | Qualitätskern bestanden; Kontextbytes und Toolaufrufe fehlen, keine explizite Profilpromotion. |
| `change_impact` | `agent_impact_context_v1` | `keep_opt_in` | Drei-Repository-Recall `1.0`, `711` projektierte Kontextbytes und sechs deterministische Toolaufrufe belegt; MRR sowie Citation-/Range-Gesundheit fehlen für dieses Profil. |
| `find_relevant_tests` | `agent_impact_context_v1` | `keep_opt_in` | Relevante Testpfade im fixierten Goldset vollständig gefunden; keine Testhinlänglichkeit, MRR oder Citation-/Range-Messung für dieses Profil. |
| `ground_claim` | `agent_benchmark_grounding` | `blocked` | Taskset vorhanden, aber keine kostenfrei committed Run-Receipts und daher keine Messwerte. |

## Tests

Der fokussierte Testvertrag prüft:

- Draft-2020-12-Schemavalidität und semantische Profilvollständigkeit;
- Bytegleichheit aller lokal gebundenen Datasets, Evaluatoren, Quellartefakte und des zusammengesetzten Goldsets;
- vollständige Metrikabdeckung über bekannte, nichtleere Messungswerte;
- fail-closed Verhalten bei fehlendem Profil, Metrikfeld, unbekannter Coverage-ID oder `null`-Coverage;
- Verbot von `status=measured` bei `null`-Metriken;
- `keep_opt_in` für partielle Spezialrouten;
- Promotion nur bei vollständiger Evidenz und expliziter Profilautorität;
- unveränderlich fehlende globale Default-Promotion.

## Grenzen

**Belegt:** Die vorhandenen Messungen werden ohne Mittelwertverschleierung an
Taskprofil, Route, Dataset, Commit und verfügbare Bundle-/Index-/Evaluatorbelege
gebunden. Fehlende Messwerte bleiben sichtbar und blockieren stärkere Aussagen.

**Nicht belegt:** allgemeine Agentenverbesserung, Antwortkorrektheit,
Reviewvollständigkeit, vollständiger Blast Radius, Testhinlänglichkeit,
Claim-Wahrheit, heutige Runtimequalität oder Merge-Reife.

Die Entscheidungsfläche ist diagnostisch. Sie ändert keine Routingkonfiguration,
führt keine kostenpflichtigen Agentenläufe aus und autorisiert weder Deployment
noch Default-Promotion.
