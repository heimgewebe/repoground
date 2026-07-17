---
doc_type: blueprint
status: active
initiative: REPOBRIEF-FRONTDOOR-GROUNDING-V1
---

# RepoGround Agent Frontdoor and Grounding Verifier v1

## 0. Dokumentrolle

Dieser Blueprint ist ein Planungsartefakt. Er beschreibt, wie RepoGround von einer
umfangreichen Bundle-/Artefaktfläche zu einer agententauglichen Frontdoor wird:

> Ein Agent stellt eine konkrete Repo-Frage, erhält ein kleines task-passendes Context
> Pack mit auflösbaren Belegen, und eine separate Prüfung kann nachträglich feststellen,
> ob die Antwort ihre angegebenen Citations und Ranges wirklich trägt.

Der Blueprint ist keine Implementierung, kein Runtime-Beweis, kein Review-Gate und keine
Merge-Freigabe. Er erzeugt keine neuen Wahrheitsansprüche über Repository-Inhalte.

## 1. Dialektische Ausgangslage

### These

RepoBriefs stärkstes Alleinstellungsmerkmal ist nicht, Repositories vollständig in Text zu
verwandeln. Der Hebel ist, Aussagen über Repositories überprüfbar zu machen: jede starke
Aussage muss auf `canonical_md`, Manifest-/Contract-Autorität oder andere ausdrücklich
benannte Authority-Flächen zurückführbar sein.

### Antithese

Ein reiner Citation-Verifier kann in eine falsche Richtung kippen. Er kann technisch prüfen,
ob eine Citation existiert, eine Range auflösbar ist und zitierter Text nicht driftet. Er kann
aber nicht allein beweisen, dass eine synthetische Schlussfolgerung semantisch wahr,
vollständig oder ausreichend ist. Ebenso kann eine komfortable `ask`-Frontdoor Antworten
schneller machen, ohne sie disziplinierter zu machen.

### Synthese

Die erste Produktachse muss beides koppeln:

1. **Agent Frontdoor**: `repobrief ask` / `lens ask` bündelt Query, Task-Profil,
   Required Reading, Tokenbudget, Context Pack, Freshness, Availability und Non-Claims.
2. **Grounding Verifier**: `repobrief verify-answer` prüft maschinell, ob deklarierte
   Citations/Ranges existieren, gegen die kanonische Quelle auflösbar sind und ob die
   Antwort unbelegte starke Claims sichtbar macht.

## 2. Alternative Sinnachse

Wenn Ziel = schnelle Nutzbarkeit, beginnt die Arbeit bei `ask` und einem einfachen
Context-Pack. Wenn Ziel = maximale Differenzierung gegenüber Repo-Dump-Tools, beginnt sie
beim Grounding-Verifier. Wenn Ziel = Distribution an andere Agenten, kommt MCP früh, aber
nur auf Basis stabiler read-only Access- und Verifier-Flächen.

Entscheidung: zuerst ein kleiner Grounding-Verifier-Vertrag plus `ask`-Frontdoor-Spezifik,
danach inkrementelle CLI/Core-Slices. MCP, Delta-Bundles und History Lens folgen erst,
wenn die lokale CLI- und Verifier-Semantik stabil ist.

## 3. Belegt, plausibel, spekulativ

### Belegt im RepoGround-Planungsstand

- RepoBrief/RepoGround führt bereits das Authority-Modell mit `canonical_md` als einziger
  Inhaltswahrheit und Sidecars als Navigation/Diagnose.
- Es existieren Profile, Health/Freshness/Availability, Required Reading, Query-/Context-
  Flächen, Citation Map, Range-Refs, Retrieval-Evaluation, Relation-/Graph-/Symbol-Slices
  und read-only Access/MCP-Roadmap-Slices.
- RepoGround Core soll keine Git-, PR-, Patch-, Shell-, Test- oder Merge-Autorität erhalten.

### Plausibel

- Eine Frontdoor senkt Time-to-first-answer stärker als weitere isolierte Sidecars.
- Ein Grounding-Verifier macht RepoBriefs Belegmodell für Multi-Agent-Review und externe
  LLM-Antworten produktiv.
- Gold Queries und Promotion Gates verhindern, dass neue Query-/Graph-/Symbolsignale nur
  gefühlt besser werden.

### Spekulativ

- Semantische Claim-Unterstützung kann teilweise automatisiert werden. Das braucht später
  eigene Claim-Klassen, Gegenbelegregeln und Messung.
- Citation-Stabilität über Commits hinweg ist nur für unveränderte oder gut gemappte
  Content-Spans robust. Verschobene, formatierte oder teilveränderte Stellen brauchen
  explizite Lineage-/Invalidation-Modelle.
- History Lens kann große Wirkung für Reviews haben, kann aber teuer, langsam und
  datenschutzsensibel werden.

## 4. Nicht-Ziele und harte Grenzen

Dieser Plan baut nicht:

- keinen Wahrheitsdetektor;
- keine automatische `supported/unsupported`-Claim-Bewertung im ersten Schritt;
- keine Patchanwendung in RepoGround Core;
- keine Shell-, Test-, CI- oder Merge-Autorität;
- keine automatische Snapshot-Erzeugung durch Lesezugriffe;
- kein LLM-Reranking als Kernpflicht;
- keine neue Package-/Repo-Umbenennung;
- keine History-/Blame-Vollindizierung als Startbedingung.

Jeder Output muss `does_not_establish` oder äquivalente Non-Claims tragen. Mindestens:

- `truth`
- `semantic_correctness`
- `completeness`
- `repo_understood`
- `test_sufficiency`
- `runtime_correctness`
- `merge_readiness`
- `security_correctness`

## 5. Zielarchitektur

```text
User / Agent Query
  -> ask-frontdoor
       - task_profile
       - token_budget
       - snapshot selection/freshness
       - required reading
       - query_existing_index / range_get / artifact_get
       - context_pack
       - answer obligations
  -> LLM answer outside RepoGround
  -> answer declaration
       - used citations
       - used ranges
       - explicit non-claims
       - uncertainty
  -> grounding verifier
       - citation exists?
       - range resolves?
       - cited text/hash matches?
       - required reading declared?
       - unsupported strong-claim markers?
       - freshness/availability caveats carried forward?
```

RepoGround erzeugt und prüft Belegbedingungen. Die Antwort selbst bleibt Agenten-/LLM-
Synthese außerhalb des deterministischen Kerns.

## 6. Artefakte und Begriffe

### 6.1 Ask Request

Mindestfelder:

- `query`
- `task_profile`
- `token_budget`
- `snapshot_policy`
- `freshness_policy`
- `required_reading_policy`
- `output_mode` (`context_pack`, `answer_scaffold`, `both`)

### 6.2 Ask Context Pack

Mindestfelder:

- `snapshot_ref`
- `provenance_status`
- `freshness`
- `availability`
- `required_reading`
- `retrieval_hits`
- `resolved_ranges`
- `artifact_roles_used`
- `answer_obligations`
- `does_not_establish`

### 6.3 Answer Declaration

Mindestfelder:

- `answer_id`
- `snapshot_ref`
- `question_hash`
- `answer_hash`
- `used_citations`
- `used_ranges`
- `strong_claims` optional im ersten Schritt, später strukturierter
- `declared_non_claims`
- `freshness_caveats`

### 6.4 Grounding Verdict

Statuswerte:

- `pass`: deklarierte Belege sind technisch auflösbar und konsistent; keine fehlenden
  Pflichtdeklarationen im geprüften Scope.
- `warn`: Belege lösen auf, aber Freshness, Availability, empfohlene Artefakte oder starke
  Claims sind lückenhaft.
- `fail`: Pflichtbeleg fehlt, Citation/Range löst nicht auf, Hash/Text driftet oder
  Required-Reading-Pflicht wurde verletzt.
- `not_applicable`: Prüfung für Task/Profil nicht einschlägig.
- `degraded`: Verifier konnte wegen Umgebung/fehlenden optionalen Dependencies nicht
  vollständig prüfen.

Wichtig: `pass` bedeutet nicht `answer_true`, sondern nur `grounding_contract_satisfied`.

## 7. Umsetzungsschnitte

### Slice 1 — Grounding Verifier Contract

Ziel: Schema- und Dokumentationsbasis für `answer_declaration` und `grounding_verdict`.

Akzeptanz:

- Contract beschreibt technische Prüfbarkeit statt semantischer Wahrheit.
- `does_not_establish` ist Pflicht.
- Verdict-Statuswerte sind festgelegt.
- Beispiele zeigen `pass`, `warn`, `fail`, `degraded`.

### Slice 2 — Minimaler Citation/Range Verifier

Ziel: deterministischer Core, der `used_citations` und `used_ranges` gegen vorhandene
Bundle-Artefakte prüft.

Prüft:

- Snapshot/Stem existiert.
- Citation Map existiert, wenn Profil sie verlangt.
- Citation-ID ist bekannt.
- Range löst gegen `canonical_md` oder ausdrücklich erlaubte Authority auf.
- Content-/Range-Hash stimmt, wenn verfügbar.
- Fehlende required Artefakte erzeugen `fail`; fehlende recommended Artefakte `warn`.

Nicht prüft:

- semantische Wahrheit;
- Vollständigkeit;
- ob das LLM die Stelle wirklich gelesen hat;
- Runtime-Verhalten.

### Slice 3 — Answer Compliance Integration

Ziel: bestehende Required-Reading-/Consumption-Trace-Flächen mit dem Grounding Verdict
verbinden.

Akzeptanz:

- Task-Profil bestimmt Pflichtartefakte.
- Antwortdeklaration zeigt verwendete Citations/Ranges.
- Consumption-Verletzungen werden als `fail` oder `warn` klassifiziert.
- Non-Claims werden in das Verdict gespiegelt.

### Slice 4 — Ask Frontdoor Contract

Ziel: maschinenlesbare und CLI-nahe Spezifikation für `repobrief ask` / `lens ask`.

Akzeptanz:

- Request, Context Pack und Answer Scaffold sind beschrieben.
- Tokenbudget wird als Begrenzung, nicht als Qualitätsbeweis geführt.
- Snapshot-Auswahl löst keinen impliziten Refresh aus.
- Jede Antwortpflicht nennt Authority und Non-Claims.

### Slice 5 — Minimaler `repobrief ask` CLI-Prototyp

Ziel: ein kalter Agent kann mit einem Befehl ein kleines, zitierbares Context Pack abrufen.

Beispiel:

```bash
repobrief ask "Wo wird Auth gehandhabt?" --repo /path/to/repo --task-profile basic_repo_question --budget 8000
```

Akzeptanz:

- nutzt nur read-only Access Layer und vorhandene Indizes;
- schreibt keine Snapshots;
- führt kein Git aus;
- gibt Freshness/Availability/Required-Reading mit aus;
- kann `--json` für Agenten liefern.

### Slice 6 — Gold Query Evaluation für Ask

Ziel: messen, ob Ask-Context-Packs die richtige Evidenz finden.

Metriken:

- Citation Coverage;
- Required Reading Coverage;
- Expected Path/Range Recall;
- MRR@10;
- Missing Evidence Taxonomy;
- Overbudget/Underbudget Rate;
- unsupported-claim-risk markers.

Promotion-Regel: keine Default-Promotion ohne Messvorteil und keine zentrale Query-Klasse
regressiert.

### Slice 7 — MCP Read-only Frontdoor

Ziel: dieselben Flächen als MCP Resources/Tools verfügbar machen.

Resources/Tools:

- `repobrief://snapshot/{stem}/ask-context/{request_id}`
- `ask_context_build`
- `answer_grounding_verify`
- bestehende `artifact_get`, `range_get`, `required_reading_resolve`, `query_existing_index`

Grenze: MCP-Lesezugriffe lösen keine Snapshot-Erzeugung aus. `snapshot_create` bleibt ein
separater expliziter Toolpfad mit eigenen Guards.

### Slice 8 — Delta/Freshness Invalidation v1

Ziel: nach Repo- oder Snapshot-Wechseln sichtbar machen, welche alten Citations noch
auflösbar, driftend oder ungültig sind.

Akzeptanz:

- `fresh`, `stale`, `unknown`, `not_comparable` bleiben erhalten.
- Verifier kann alte Answer Declarations gegen einen neuen Snapshot als `valid`, `drifted`,
  `missing`, `not_comparable` markieren.
- Kein automatischer Re-Dump durch Prüfung.

### Slice 9 — History Lens als derived Navigation

Ziel: Churn, Blame-Verdichtung, Commit-/PR-Provenance-Ketten als optionales Derived-Artefakt
für Reviews und Refactoring-Entscheidungen.

Akzeptanz:

- History Lens ist Navigation/Diagnose, keine Inhaltswahrheit.
- Datenschutz-/Export-Profil entscheidet, ob History enthalten sein darf.
- Keine Schuld- oder Ownership-Urteile.
- Kein Ersatz für GitHub/CI/PR-Livezustand.

## 8. Abhängigkeiten

Dieser Plan setzt voraus oder nutzt bevorzugt:

- Snapshot Profile und Export Safety;
- Health/Freshness/Availability;
- Read-only Access Layer;
- Required Reading und Agent Consumption Preflight;
- RepoGround CLI-Alias;
- Relation Guard Goldset, Graph Availability, Symbol Index und Retrieval-v2-Evaluation als
  Qualitätsflächen;
- MCP Boundary, bevor MCP-Tools produktiv werden.

## 9. Risiken und Gegenmaßnahmen

| Risiko | Folge | Gegenmaßnahme |
| --- | --- | --- |
| Verifier wird als Wahrheitsdetektor missverstanden | falsche Sicherheit | Name `Grounding Verifier`, Pflicht-Non-Claims, keine `true/false`-Claimverdicts |
| Ask erzeugt zu große Context Packs | Agent liest wieder linear | hartes Tokenbudget, Task-Profile, Gold Query Evaluation |
| MCP kommt vor stabiler Semantik | Client-Drift und falsche Distribution | MCP erst nach CLI/Core-Vertrag |
| Delta-Citations wirken stabiler als sie sind | alte Belege werden überdehnt | Invalidation statt stiller Migration; `not_comparable` zulassen |
| History Lens erzeugt Datenschutz-/Bias-Risiken | Personen-/Schulddeutung | Profil-Gate, Export Safety, keine Blame-Urteile |

## 10. Entscheidungsregel

Der Plan gilt, wenn RepoGround primär Agenten helfen soll, belegte Antworten schneller und
prüfbarer zu erzeugen.

Er gilt nicht, wenn kurzfristig nur menschliche Dokumentation, UI-Politur oder Patch-
Automation priorisiert wird.

Nächster sinnvoller Implementierungsschritt: Slice 1 als kleiner Contract-/Docs-/Fixture-PR,
danach Slice 2 als minimaler deterministischer Verifier-Core.
