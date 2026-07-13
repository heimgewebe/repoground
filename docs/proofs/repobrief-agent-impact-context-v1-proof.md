# RepoBrief Agent Impact Context v1 – Implementierungsnachweis

## Bindung

- Bureau-Initiative: `REPOBRIEF-CODEGRAPH-ADOPTION-V1`
- Bureau-Task: `RCGA-V1-T001`
- Vorgänger: `RBAE-V1-T003`
- Lenskit-Basis: `80374ccbd1af8e86dab3f3d173ce2a585962b195`
- Referenzidee: `codegraph-ai/CodeGraph`
- Übernahmeart: selektive Lenskit-native Mechanismen; kein CodeGraph-Dienst

## Implementierter Slice

Der Slice ergänzt eine read-only Agentenfläche für:

1. gerichtete eingehende und ausgehende Beziehungen;
2. verwandte Tests mit getrennten Evidenztypen;
3. relevante Verträge, Dokumentation und Einstiegspunkte;
4. einen begrenzten Edit Context vor Änderungen;
5. Quellstatus, Bundle-Kohärenz, Lücken und Kürzungen;
6. eine protokollneutrale Adapteraktion und eine opt-in CLI;
7. einen festen, reproduzierbaren Goldset-Evaluator.

Die Implementierung nutzt bestehende Lenskit-Formate und den bestehenden
integritätsgeprüften RepoBrief-Adapter. Sie erzeugt keinen zweiten Index und
übernimmt weder Memory noch Reviewautorität aus CodeGraph.

## Sicherheits- und Wahrheitsgrenzen

- Pfade müssen kanonisch repository-relativ sein.
- `max_items` ist auf `1..200` begrenzt.
- Kernartefakte mit abweichendem `run_id` oder Digest blockieren.
- Integritätsseitig blockierte Kernartefakte blockieren die Gesamtausgabe.
- Graphkanten behalten Richtung, Typ, Evidenzniveau und Ursprungsbeleg.
- Heuristische Testpfade sind als `heuristic` gekennzeichnet.
- Keine Git-, Patch-, Shell-, Test-, PR-, Snapshot- oder Memory-Mutation.
- Kein Reviewverdikt, Risikoscore, Coverageversprechen oder Mergefreigabe.

## Tests

Die Tests decken ab:

- Schema- und Determinismusprüfung;
- Richtung und Evidenz der Graphkanten;
- Trennung von Graph-, Symbolpfad- und Heuristik-Testkandidaten;
- Edit-Context-Erstleseliste;
- Verträge, Dokumentation und Einstiegspunkte;
- inkohärente Bundle-Identitäten;
- ungültige Pfade, Modi und Budgets;
- fehlende Ziele;
- integritätsgeprüfte Adapterreads ohne Seiteneffekte;
- manipulierte Kernartefakte;
- Adapterdispatch und opt-in CLI;
- festen Goldset-Vergleich ohne Standardbeförderung.

## Begrenzte Messung

Goldset:
`docs/retrieval/repobrief_agent_impact_goldset.v1.json`

SHA-256:
`b243b8827eb5afe575f519f3cba53e55acd0151bd406dd208af0bfd23f1270f7`

Committed Diagnose:
`docs/diagnostics/repobrief-agent-impact-context-fixture-eval-v1.json`

Die synthetische Contract-Fixture ergibt:

- Baseline Target Recall: `0.29166666666666663`
- Impact Target Recall: `1.0`
- Vorteil: `0.7083333333333334`
- keine Fallregression: `true`
- Mindestvorteil: `0.2`
- Standardbeförderung: `false`

## Einordnung

**Belegt:** Der neue Producer kann auf dem festen Fixture zusätzliche erwartete
Pfade strukturiert und deterministisch sichtbar machen, ohne die read-only
Grenze zu verlassen.

**Plausibel:** Derselbe Mechanismus kann reale Edit- und Reviewnavigation
verbessern, sofern die zugrunde liegenden Bundle-Artefakte die relevanten
Beziehungen enthalten.

**Nicht belegt:** reale Repositorywirkung, vollständige Call Chains,
vollständiger Blast Radius, Testabdeckung, Antwortkorrektheit,
Reviewvollständigkeit, Securitykorrektheit oder Merge-Reife.

Die Aktion bleibt daher opt-in. Eine Live-Bundle-Kalibrierung ist eine
eigenständige Beförderungsentscheidung und keine Voraussetzung dafür, den
begrenzten read-only Mechanismus bereitzustellen.
