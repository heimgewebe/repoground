# C1 — Authority / Canonicality / Risk-Class Matrix

**Status:** Blueprint (docs-first, governance-first, nicht runtime-getrieben).  
**Branch:** feature/c1-authority-risk-matrix  
**Datum:** 2026-05-24

Beziehung zu bestehenden Docs:
- Bestehende Authority-/Canonicality-Terme: `docs/architecture/artifact-inventory.md` §6
- Bestehende Contracts: `merger/lenskit/contracts/`
- Bestehende Evidence-Levels: `docs/architecture/artifact-evidence-levels.md`
- Retrieval-Miss-Scope: `docs/proofs/retrieval-miss-taxonomy-proof.md`
- Context-Quality-Scope: `docs/proofs/context-quality-signals-proof.md`
- Post-Emit-Health-Scope: `docs/proofs/post-emit-health-implementation-proof.md`
- Anti-Hallucination-Architektur: `docs/blueprints/lenskit-anti-hallucination-output-architecture.md`
- Globale Reihenfolge: `docs/roadmap/lenskit-master-roadmap.md`

**Diese Datei ersetzt nichts.** Sie normiert Inferenzgrenzen, die in bestehenden
Artefakten und Contracts partiell bereits angelegt sind, aber noch nicht als explizite
Governance-Schicht existieren.

---

## Vorbefund: Was bereits existiert

Vor jeder Architekturnormierung ist zu prüfen, welche Authority-/Risk-Konzepte
bereits vorhanden sind.

### Vorhandene Authority-Terme (in Contracts und Inventar)

| Begriff | Fundstelle | Bedeutung |
| :--- | :--- | :--- |
| `canonical_content` | `artifact-inventory.md` §6, `bundle-manifest.v1` | Inhalt selbst |
| `navigation_index` | `artifact-inventory.md` §6, `bundle-manifest.v1` | zeigt, beweist nicht |
| `retrieval_index` | `artifact-inventory.md` §6 | Quelle für Retrieval, abgeleitet |
| `runtime_cache` | `artifact-inventory.md` §6 | beschleunigt Suche, kein Ursprung |
| `diagnostic_signal` | `artifact-inventory.md` §6, `context-quality.v1`, `retrieval-eval.v1` | warnt, beweist nicht |
| `runtime_observation` | `artifact-inventory.md` §6, `context-lookup.v1`, `trace-lookup.v1`, `artifact-lookup.v1` | Spur eines Laufs |
| `agent_context_projection` | `agent-query-session.v2` | Session-Autorität const |

### Vorhandene Canonicality-Terme

| Begriff | Fundstelle |
| :--- | :--- |
| `content_source` | `bundle-manifest.v1`, `artifact-inventory.md` |
| `derived` | `bundle-manifest.v1`, `artifact-inventory.md` |
| `index_only` | `bundle-manifest.v1`, `artifact-inventory.md` |
| `cache` | `bundle-manifest.v1`, `artifact-inventory.md` |
| `diagnostic` | `bundle-manifest.v1`, `artifact-inventory.md`, `context-quality.v1`, `retrieval-eval.v1` |
| `observation` | `context-lookup.v1`, `trace-lookup.v1`, `artifact-lookup.v1` |

### Vorhandene Risk-Class-Terme

`risk_class: "diagnostic"` existiert bereits in `retrieval-eval.v1.schema.json`
(für `miss_taxonomy`) und in `context-quality.v1.schema.json`.  
Kein systemweites `risk_class`-Vokabular ist bisher normiert.

### Vorhandene Claim-Boundary-Konzepte

`does_not_prove` ist in mehreren Contracts als required-Array implementiert:
- `retrieval-eval.v1` (B2 miss_taxonomy)
- `agent-query-session.v2` (`claim_boundaries.proves`, `claim_boundaries.does_not_prove`)
- `context-quality.v1` (`does_not_mean`)
- `post-emit-health.v1` (`does_not_mean`)

### Bewertung: Was fehlt

Die o.g. Terme sind verteilt, partiell, rollengebunden. Was noch nicht existiert:

1. **Kein systemweites Vokabular** für alle Klassen (Artefakte, Runtime-Payloads,
   abgeleitete Projektionen, Agent-Outputs).
2. **Keine explizite Verbotsliste** semantischer Upgradings (z.B.
   `diagnostic → truth escalation`).
3. **Keine normative Matrix** mit allowed/forbidden inferences pro Klasse.
4. **Keine Lint-Ebene** für authority escalation detection.
5. **Kein Trust-Surface-Begriff** (was darf ein Consumer als vertrauenswürdig behandeln).

C1 schließt diese Lücken auf Governance-Ebene — ohne neue Runtime-Artefakte.

---

## 1. Problemdefinition

### 1.1 Das additive Wachstumsproblem

Lenskit erzeugt inzwischen Artefakte unterschiedlicher epistemischer Stärke:

- `canonical_md` — der Repo-Inhalt selbst
- `chunk_index_jsonl` — mechanische Zerlegung des Inhalts
- `sqlite_index` — beschleunigter Zugriff auf Zerlegungen
- `retrieval_eval_json` — Beobachtung von Retrieval-Ergebnissen
- `output_health` / `post_emit_health` — diagnostische Bundleprüfungen
- `context_quality` — Projektion vorhandener Signale
- `agent_reading_pack` — Navigationseinstieg für Agents
- `citation_map_jsonl` — Belegadressen
- `agent_query_session` — Spur einer Agent-Query
- `miss_taxonomy` (in retrieval_eval) — Fehlerklassifikation

Jedes dieser Artefakte hat einen wohldefinierten eigenen Scope. Das Problem entsteht
nicht innerhalb eines Artefakts, sondern **an den Grenzen zwischen ihnen**: wenn ein
Konsument (Mensch, Agent, CI-Schritt) von einem Artefakt auf ein anderes schließt,
ohne dass diese Schlussfolgerung explizit erlaubt ist.

### 1.2 Warum `does_not_prove` lokal nicht ausreicht

`does_not_prove` ist bereits in mehreren Contracts implementiert und wirkt als
lokale Schutzbehauptung: "Dieses Artefakt beweist X nicht." Das ist notwendig,
aber nicht hinreichend, weil:

- Konsumenten die Felder übersehen oder ignorieren können.
- Kein systemweites Vokabular festlegt, welche Inferenzen für welche Artefaktklasse
  generell verboten sind.
- Ein Artefakt, das lokal korrekt deklariert ist, trotzdem in einer Pipeline
  falsch verwendet werden kann (z.B. diagnostic_signal als Input für eine
  authority-tragende Entscheidung).
- Lint-Regeln, die solche Übergänge erkennen, nicht existieren.

**`does_not_prove` ist ein Artefakt-lokales Disclaimer-Instrument. C1 ist ein
systemweites Governance-Instrument.**

### 1.3 Semantische Drift-Risiken

Folgende stille Übergänge sind ohne explizite Normierung möglich:

| Drift-Typ | Beschreibung |
| :--- | :--- |
| Navigation → Bedeutung | `agent_reading_pack` TOP_CHUNK_SPANS werden als semantisch wichtig interpretiert |
| Diagnostik → Wahrheit | `context_quality.projection_status = "complete"` wird als Beweis gelesen |
| Retrieval-Miss → Abwesenheit | kein FTS-Treffer wird als "Datei existiert nicht" gedeutet |
| Cache → Evidenz | SQLite-Ergebnis wird als kanonische Quelle behandelt |
| Agent-Output → Authority | Ausgabe eines Agents erbt die Autorität der Inputs |
| Export → Wahrheit | exportiertes Bundle gilt als verified truth |
| Derivat → Original | abgeleitetes Artefakt wird wie kanonischer Inhalt behandelt |
| Eval-Metrik → Vollständigkeit | `recall@k = 1.0` wird als Vollständigkeitsbeweis gelesen |

### 1.4 Warum epistemische Grenzen erstklassige Architekturartefakte werden müssen

Bisher werden epistemische Grenzen entweder in einzelnen `does_not_prove`-Arrays
oder in Prosakommentaren innerhalb von Proofs und Blueprints beschrieben. Das ist
nicht ausreichend, weil:

- Prosa ist nicht maschinenlesbar.
- Pro-Artefakt-Disclaimers werden nicht konsumenten-seitig aggregiert.
- Kein Governance-Layer kann Lint-Regeln aus Prosa ableiten.
- Bestehende Constraints sind nicht vollständig auf alle Artefaktklassen angewandt.

**Kernprinzip:**

> Beobachtung ≠ Diagnose ≠ Interpretation ≠ Wahrheit

Dieses Prinzip ist in Lenskit bereits partiell implementiert (durch Artefaktrollen,
`does_not_prove`, Authority-Felder). C1 macht es zur expliziten Governance-Norm,
nicht zur impliziten Konvention.

---

## 2. Zielmodell

### 2.1 Begriffsdefinitionen

Die folgenden Begriffe werden für C1 normiert. Sie bauen auf bestehenden
Artefakt-Inventory-Termen auf und erweitern diese um explizite
Inferenzgrenzen.

**`authority`**  
Wer oder was ist die Quelle einer Aussage? Authority beschreibt die Ursprungsklasse
eines Artefakts, nicht seine Qualität oder Korrektheit.  
Werte (inventory-belegt): `canonical_content`, `navigation_index`, `retrieval_index`,
`runtime_cache`, `diagnostic_signal`, `runtime_observation`, `agent_context_projection`  
Werte (neu in C1 normiert): `external_unverified`, `derived_projection`, `agent_generated`  
*Inventory-belegte Terme aus `artifact-inventory.md` §6; C1-Erweiterungen werden hier
neu normiert und widersprechen keinem bestehenden Contract.*

**`canonicality`**  
In welchem Verhältnis steht ein Artefakt zum Repo-Inhalt? Canonicality beschreibt
den Ableitungsgrad, nicht die Korrektheit.  
Werte (inventory-belegt): `content_source`, `derived`, `index_only`, `cache`,
`diagnostic`, `observation`  
*Inventory-belegte Terme aus `artifact-inventory.md` §6. Agent-Ausgaben werden in C1
nicht als separater Canonicality-Wert geführt — sie werden modelliert als
`authority: agent_generated` + `canonicality: derived`.*

**`risk_class`**  
Welches epistemische Missbrauchsrisiko trägt das Artefakt? Risk-Class ist
eine Governance-Einschätzung, kein Quality-Score.  
Werte: `content` (hohes Vertrauen, direkte Quelle), `navigation` (zeigt, beweist nicht),
`diagnostic` (warnt, kein Beweis), `cache` (beschleunigt, kein Ursprung),
`observation` (Spur, kein Beleg), `derived` (abgeleitet, nicht autoritativ by default),
`external` (außerhalb des Kontrollbereichs)

**`allowed_inference`**  
Explizite Liste der Schlussfolgerungen, die ein Konsument aus einem Artefakt
ziehen darf. Leer bedeutet: keine Inferenz erlaubt außer direkter Ablesung.

**`forbidden_inference`**  
Explizite Liste der Schlussfolgerungen, die für diese Artefaktklasse verboten sind,
unabhängig vom Inhalt des einzelnen Artefakts.

**`derivation_scope`**  
Was ist die Basis dieses Artefakts? Beschreibt, aus welchen Artefakten oder
Prozessen ein Derivat entstammt. Beispiel: `sqlite_index` → `derivation_scope:
chunk_index_jsonl`.

**`trust_surface`**  
Was darf ein Consumer als vertrauenswürdig behandeln? Trust-Surface ist
die explizit erlaubte Nutzungsgrenze für einen Artefakttyp. Kein trust_surface
bedeutet: konsumentenseitig muss Vorsicht als Default gelten.

**`exportability`**  
Unter welchen Bedingungen darf ein Artefakt den internen Kontext verlassen?
Exportability ist keine Qualitätsaussage, sondern eine Governance-Grenze.
Werte: `internal_only`, `conditional` (Bedingungen explizit), `open` (keine
Einschränkung), `never` (strukturell nicht exportierbar, z.B. runtime state).

---

## 3. Normative Matrix

Die folgende Matrix normiert Inferenzgrenzen pro Artefaktklasse. Sie ist
operationalisierbar: jede Zeile kann in einen CI-Check oder Lint-Kommentar
übersetzt werden.

**Pflichtlektüre für Produzenten:** Diese Matrix enthält bestehende Artefaktklassen
und C1-neu normierte bzw. konzeptionelle Klassen. Bestehende Artefakte werden dadurch
nicht umklassifiziert; die Matrix normiert Inferenzgrenzen explizit.

---

### 3.1 `canonical_content`

| Feld | Wert |
| :--- | :--- |
| **Definition** | Der Repo-Inhalt selbst. Einzige Inhaltquelle. In Lenskit: `canonical_md`. |
| **allowed_inference** | Inhalt lesen, zitieren (mit Range-Ref), als Baseline für Ableitungen verwenden. |
| **forbidden_inference** | Vollständigkeit des Repos behaupten; Abwesenheit einer Sektion als "nicht vorhanden" deuten ohne Scope-Prüfung; Bedeutung oder Wichtigkeit von Abschnitten ableiten. |
| **valid_consumers** | Mensch, LLM (direkt), Bundle-Manifest, Citation-Map-Producer, Range-Resolver. |
| **export_constraints** | Exportierbar; bei sensiblen Repos Redaction erforderlich (Profil-Gate A5). |
| **required_disclaimers** | Keiner für normalen Gebrauch; bei Agent-Export: Scope-Begrenzung (welcher Teil des Repos ist enthalten). |
| **risk_class** | `content` |
| **typical_producers** | `core.merge` |
| **typical_consumers** | Alle höheren Artefaktklassen nutzen `canonical_md` als Basis. |
| **possible_ci_rules** | Warnung wenn andere Artefaktklasse als `canonical_content` als Inhaltquelle verwendet wird. |

---

### 3.2 `diagnostic_signal`

| Feld | Wert |
| :--- | :--- |
| **Definition** | Artefakt, das Beobachtungen über den Zustand des Systems oder Bundles aggregiert. Warnt, beweist nicht. In Lenskit: `output_health`, `post_emit_health`, `context_quality`, `miss_taxonomy` (innerhalb `retrieval_eval`). |
| **allowed_inference** | Zustand des Systems zum Zeitpunkt der Prüfung lesen; Warnungen als Hinweise behandeln; CI-Entscheidungen auf Basis von `verdict/status` treffen (fail/pass). |
| **forbidden_inference** | `verdict=pass` als Beweis für Repo-Korrektheit; `verdict=pass` als Beweis für Antwortsicherheit; diagnostics als Wahrheit über den Inhalt; `projection_status=complete` als Vollständigkeitsbeweis. |
| **valid_consumers** | CI-Pipelines, Entwickler, Debug-Tools. Nicht: LLM-Agents als primäre Wissensquelle. |
| **export_constraints** | Conditional: nur mit explizitem Disclaimer (`authority: diagnostic_signal`). Nie als primäre Wissensquelle exportieren. |
| **required_disclaimers** | Rolle-spezifisches `does_not_prove` oder `does_not_mean`. C1 fordert nicht ein identisches Disclaimer-Set für alle Diagnostic-Artefakte; bestehende Contracts behalten ihre spezialisierten Grenzen. Mindestprinzip: Diagnostik darf keine Repo-Verstandenheit, Retrieval-Vollständigkeit, Antwortsicherheit, Claim-Wahrheit oder Abwesenheitsbeweise implizieren. |
| **risk_class** | `diagnostic` |
| **typical_producers** | `core.output_health`, `core.post_emit_health`, `core.context_quality`, `retrieval.eval_core`. |
| **typical_consumers** | CI, Entwickler, parity_guard. |
| **possible_ci_rules** | Fehler wenn `diagnostic_signal`-Artefakt als `canonical_content` oder `retrieval_index` behandelt wird; Fehler wenn `does_not_prove`/`does_not_mean`-Array fehlt. |

---

### 3.3 `navigation_index`

| Feld | Wert |
| :--- | :--- |
| **Definition** | Artefakt, das zeigt, wo etwas ist — nicht was es bedeutet. In Lenskit: `agent_reading_pack`, `dump_index_json`, `index_sidecar_json`, `citation_map_jsonl`, `derived_manifest_json`. |
| **allowed_inference** | Pfade zu Artefakten auflösen; als Einstiegspunkt für weitere Lookup-Operationen nutzen; Navigation innerhalb des Bundles. |
| **forbidden_inference** | Semantische Wichtigkeit aus Position oder Ranking ableiten; Navigation als Wahrheit über Inhalt behandeln; Abwesenheit in einem Index als Abwesenheit im Repo deuten. |
| **valid_consumers** | Agents (als Einstiegspunkt), CLI, WebUI. Immer mit Resolve-Pflicht (`must_resolve_to: role_specific_authority`). |
| **export_constraints** | Conditional: nur wenn die verknüpften Artefakte ebenfalls exportiert werden. Standalone-Export ohne Bezugsartefakt nicht sinnvoll. |
| **required_disclaimers** | `may_cite: false` (für agent_reading_pack); `must_resolve_to: role_specific_authority`; `does_not_prove: [semantic_importance, architecture_truth, complete_context]`. |
| **risk_class** | `navigation` |
| **typical_producers** | `core.merge`, `core.agent_reading_pack`, `core.citation_map`. |
| **typical_consumers** | LLM-Agents (Navigation), Range-Resolver, Query-Core (für Chunk-Lookup). |
| **possible_ci_rules** | Warnung wenn Navigation-Artefakt als Evidenz zitiert wird; Fehler wenn `agent_reading_pack` ohne `does_not_prove`-Block exportiert wird. |

---

### 3.4 `derived_projection`

> **Konzeptionelle Klasse (C1):** `derived_projection` ist eine konzeptionelle Governance-Klasse
> für zukünftige, nicht-diagnostische Projektionen. Bestehende Artefakte werden durch C1 **nicht
> umklassifiziert**: `context_quality` bleibt `diagnostic_signal`; `derived_manifest_json` bleibt
> `navigation_index`.

| Feld | Wert |
| :--- | :--- |
| **Definition** | Konzeptionelle Klasse für Artefakte, die aus vorhandenen Artefakten projiziert werden, ohne neue Informationen hinzuzufügen und ohne diagnostischen Charakter. Kein bestehender Lenskit-Artefakttyp wird durch C1 in diese Klasse umklassifiziert. |
| **allowed_inference** | Den projizierten Zustand zum Projektionszeitpunkt lesen; als Zusammenfassung vorhandener Signale verwenden. |
| **forbidden_inference** | Als autoritative Aussage über Repo-Inhalt; als Beweis für irgendeine Property der zugrundeliegenden Artefakte; `projection_status=complete` als Vollständigkeitsbeweis. |
| **valid_consumers** | Entwickler, CI (als Übersicht), Debug-Tools. |
| **export_constraints** | Conditional: nur mit vollständiger Angabe der Projektionsbasis. |
| **required_disclaimers** | Projektionsbasis explizit auflisten; `authority: derived_projection`; keine Wahrheitsaussagen. |
| **risk_class** | `derived` |
| **typical_producers** | Zukünftige Projektions-Komponenten (nicht Teil von C1). |
| **typical_consumers** | Entwickler, CI. |
| **possible_ci_rules** | Fehler wenn `derived_projection` als primäre Signalquelle für eine authority-tragende Entscheidung verwendet wird. |

---

### 3.5 `cache`

| Feld | Wert |
| :--- | :--- |
| **Definition** | Artefakt, das nur zur Beschleunigung existiert. Enthält keine Informationen, die nicht in der Quelle vorhanden wären. In Lenskit: `sqlite_index`. |
| **allowed_inference** | Schnellerer Zugriff auf Informationen aus der Quellartefakt; SQLite-Ergebnis als approximativen Hinweis auf Chunk-Inhalt lesen. |
| **forbidden_inference** | SQLite-Ergebnis als Beweis für Repo-Inhalt; Abwesenheit im Index als Abwesenheit im Repo; SQLite-Ranking als Beweis für Relevanz oder Wichtigkeit. |
| **valid_consumers** | `retrieval.query_core`, `retrieval.eval_core`. Immer mit Fallback auf `canonical_md`/`chunk_index_jsonl`. |
| **export_constraints** | `internal_only` by default; Export nur als Debug-Artefakt mit explizitem Disclaimer. |
| **required_disclaimers** | `does_not_prove: [retrieval_completeness, semantic_importance, canonical_presence]`. |
| **risk_class** | `cache` |
| **typical_producers** | `retrieval.index_db`. |
| **typical_consumers** | `retrieval.query_core`, `retrieval.eval_core`. |
| **possible_ci_rules** | Fehler wenn `sqlite_index` ohne Fallback-Referenz auf Quellartefakt verwendet wird. |

---

### 3.6 `runtime_observation`

| Feld | Wert |
| :--- | :--- |
| **Definition** | Spur eines einzelnen Laufzeitvorgangs. Beschreibt, was zu einem bestimmten Zeitpunkt passiert ist — nicht den Repo-Zustand. In Lenskit: `agent_query_session`, `query_trace`, `query_context_bundle`, `federation_trace`. |
| **allowed_inference** | Den Ablauf einer einzelnen Query rekonstruieren; Provenienz eines Query-Ergebnisses nachvollziehen; Debug-Informationen lesen. |
| **forbidden_inference** | Laufzeitbeobachtung als Beweis für Repo-Inhalt; Session-Ergebnis als autoritativen Kontext; Query-Trace als Vollständigkeitsbeweis für Retrieval. |
| **valid_consumers** | Debug-Tools, CI (für Trace-Analyse), Entwickler. Nicht: LLM-Agents als primäre Wissensquelle. |
| **export_constraints** | `conditional`: nur mit explizitem Laufzeit-Disclaimer; `session_authority: agent_context_projection` (const in `agent-query-session.v2`). |
| **required_disclaimers** | `claim_boundaries.does_not_prove` mindestens: `[repository_truth, retrieval_completeness, answer_safety]`. |
| **risk_class** | `observation` |
| **typical_producers** | `service.app`, `retrieval.session`, `retrieval.query_core`. |
| **typical_consumers** | Debug-CLI, Trace-Lookup, Artifact-Lookup. |
| **possible_ci_rules** | Fehler wenn `runtime_observation` als canonicality-beinhaltende Quelle deklariert wird. |

---

### 3.7 `agent_generated`

| Feld | Wert |
| :--- | :--- |
| **Definition** | Ausgabe, die ein Agent (LLM oder automatisiertes System) erzeugt hat. Enthält keine inhärente Autorität — nur die Inputs, aus denen der Agent erzeugt hat, tragen ggf. Autorität. In Lenskit: Agent-Antworten, RAG-basierte Ausgaben, MCP-Outputs. |
| **allowed_inference** | Als Arbeitshypothese oder Entwurf lesen; Inputs zur Verifikation zurückverfolgen. |
| **forbidden_inference** | Authority-Vererbung: ein Agent, der aus `canonical_content` gelesen hat, erzeugt keine `canonical_content`-Ausgabe; Agent-Output als Wahrheit über Repo-Inhalt; Agent-Zusammenfassung als vollständig. |
| **valid_consumers** | Mensch (mit Vorbehalt), weitere Agents (mit explizitem Downstream-Disclaimer). |
| **export_constraints** | `conditional`: mit klarer Herkunftsangabe (welche Inputs, welches Modell). |
| **required_disclaimers** | Explizite Herkunft; keine Authority-Vererbungsbehauptung; keine Vollständigkeitsbehauptung. |
| **risk_class** | `derived` (erhöht, da Interpretationsschritt ohne Transparenz möglich) |
| **typical_producers** | LLM-Agents, MCP-Endpunkte, automatisierte Zusammenfassung. |
| **typical_consumers** | Mensch, weitere Pipeline-Schritte (mit Vorbehalt). |
| **possible_ci_rules** | Warnung wenn Agent-Output als Evidenz in einem Citation-Kontext verwendet wird; Fehler wenn Agent-Output `authority: canonical_content` deklariert. |

---

### 3.8 `external_unverified`

| Feld | Wert |
| :--- | :--- |
| **Definition** | Informationen, die aus einer Quelle außerhalb des Lenskit-kontrollierten Bereichs stammen. In Lenskit: externe URLs, unverifizierten Cross-Repo-Links (`confidence: inferred`), externe APIs. |
| **allowed_inference** | Als Hinweis auf externe Quelle lesen; für manuelle Verifikation vormerken. |
| **forbidden_inference** | Als Beweis für irgendeine interne Property; als Ergänzung zu `canonical_content`. |
| **valid_consumers** | Mensch (für manuelle Verifikation). |
| **export_constraints** | `conditional`: mit explizitem `unverified`-Flag. |
| **required_disclaimers** | Quelle angeben; `confidence: inferred` oder stärker explizit. |
| **risk_class** | `external` |
| **typical_producers** | `federation_query._build_cross_repo_links` (heuristisch). |
| **typical_consumers** | Mensch, Debug-Tools. |
| **possible_ci_rules** | Fehler wenn externe unverifizierten Quellen ohne expliziten Vorbehalt in interne Authority-Kette eingehen. |

---

### 3.9 Explizit verbotene Übergänge

Diese Übergänge sind unabhängig von Implementierungsdetails verboten:

| Verbotener Übergang | Begründung |
| :--- | :--- |
| `diagnostic_signal` → `truth` | Diagnostik beschreibt den Beobachtungszustand, nicht den wahren Zustand. |
| `retrieval_miss` → `absence_proof` | Ein FTS-Miss beweist nicht, dass ein Chunk oder Dokument nicht im Repo existiert. |
| `navigation_index` → `semantic_importance` | Position oder Ranking in einem Index impliziert keine Bedeutung. |
| `cache` → `evidence` | SQLite ist ein beschleunigter Spiegel — kein Beleg. |
| `agent_generated` → `authority_inheritance` | Agents erben keine Autorität ihrer Inputs. |
| `export` → `truth_verification` | Ein exportiertes Bundle ist nicht verifikationsäquivalent zu einer internen CI-Prüfung. |
| `runtime_observation` → `repository_state` | Eine Query-Session beschreibt einen Laufzeitmoment, nicht den Repo-Zustand. |
| `eval_metric` → `retrieval_completeness` | `recall@k = 1.0` ist kein Beweis für vollständiges Retrieval. |

---

## 4. Architekturprinzipien

### P1 — Contracts-first

Inferenzgrenzen werden in Contracts deklariert, bevor Runtime-Code sie durchsetzt.
Für zukünftige C2-Contract-Normierung gilt: Ein neuer oder migrierter Contract ohne explizite `allowed_inference`/`forbidden_inference`-Sektionen bleibt governance-unvollständig.

*Bestehende Partial-Implementierung: `does_not_prove` in `retrieval-eval.v1`,
`agent-query-session.v2`, `context-quality.v1`, `post-emit-health.v1`.*

### P2 — Derived artifacts are non-authoritative by default

Abgeleitete Artefakte tragen nicht die Autorität ihrer Quellen. Authority muss
explizit deklariert werden und ist niemals transitiv.

*Bestehende Implementierung: `authority: navigation_index` für `agent_reading_pack`
und `citation_map_jsonl` in `artifact-inventory.md`.*

### P3 — Explicit inference boundaries

Erlaubte und verbotene Inferenzen sind maschinenlesbar und pro Artefaktklasse explizit.
Implizite Grenzen (Prosa, Konvention) sind nicht ausreichend.

### P4 — No silent authority escalation

Kein Artefakt darf implizit eine höhere Autorität als deklariert erhalten.
Authority-Upgrades (z.B. `diagnostic_signal` → `canonical_content`) sind verboten,
auch wenn der Inhalt faktisch korrekt wäre.

### P5 — Exportability is not truth

Ein exportiertes Artefakt ist nicht automatisch verified. Exportability ist eine
Governance-Eigenschaft, keine epistemische Aussage.

*Bestehende Partial-Implementierung: Agent-Export-Gate (A5), `redact_secrets`-Gate.*

### P6 — Diagnostics are not evidence

Diagnostische Artefakte (`output_health`, `post_emit_health`, `context_quality`)
beschreiben den Zustand des Systems zu einem Zeitpunkt. Sie sind kein Beweis für
Repo-Inhalt oder Retrieval-Vollständigkeit.

*Bestehende Implementierung: `does_not_mean: [repo_understood, retrieval_complete,
answer_safe_without_citations, claims_true]` in `context-quality.v1`.*

### P7 — Absence of hit is not absence of content

Ein Retrieval-Miss (kein FTS-Treffer, kein Top-k-Treffer) beweist nicht, dass
der gesuchte Inhalt nicht im Repo existiert. Retrieval ist vollständigkeitsneutral.

*Bestehende Implementierung: `does_not_prove:
absence_of_retrieval_hit_does_not_prove_absence_in_repository` in B2 miss_taxonomy.*

### P8 — Trust surface must be explicit

Kein Consumer-System darf implizit annehmen, dass ein Artefakt vertrauenswürdig
ist. Trust-Surface ist explizit deklariert oder gilt als nicht-vertrauenswürdig.

---

## 5. Contract-Skizzen (NICHT implementieren)

Die folgenden Skizzen sind Architekturentwürfe. Keine echten Schema-Dateien anlegen.
Offene Fragen sind explizit markiert.

### 5.1 `authority-matrix.v1`

**Zweck:** Maschinenlesbares Verzeichnis der Authority-Klassen mit ihren Grenzen.
Systemweites Nachschlagewerk für Lint-Tools und CI.

**Mögliche Felder:**
- `version`: Schema-Version
- `classes[]`: Liste aller Authority-Klassen
  - `id`: Klassen-ID (z.B. `canonical_content`)
  - `display_name`: Lesbarer Name
  - `allowed_inferences[]`: Erlaubte Schlussfolgerungen (maschinenlesbar)
  - `forbidden_inferences[]`: Verbotene Schlussfolgerungen (maschinenlesbar)
  - `valid_consumers[]`: Erlaubte Consumer-Klassen
  - `export_constraints`: `internal_only | conditional | open | never`
  - `risk_class`: Zugehörige Risk-Class

**Required:** `version`, `classes[]`, jede Klasse mit `id`, `forbidden_inferences[]`  
**Optional:** `display_name`, `valid_consumers[]`, `possible_ci_rules[]`

**Offene Fragen:**
- Wie werden Versionierungskonflikte zwischen authority-matrix und bundle-manifest behandelt?
- Wer ist autoritativer Producer — Governance-Layer oder Bundle-Manifest?
- Wie wird verhindert, dass authority-matrix selbst authority-escalation durchführt?

**Mögliche Producer:** Governance-Tooling, CI-Validation-Layer  
**Mögliche Consumer:** Lint-Tools, parity_guard, CI-Checks  
**Mögliche CI-Nutzung:** Validierung aller Artefakt-Declarations gegen die Matrix

---

### 5.2 `inference-boundary.v1`

**Zweck:** Pro-Artefakt-Deklaration erlaubter und verbotener Inferenzen.
Ergänzt `does_not_prove` um maschinenlesbare `allowed_inference`-Liste.

**Mögliche Felder:**
- `artifact_role`: Zugehörige ArtifactRole aus `bundle-manifest.v1`
- `authority`: Authority-Klasse aus `authority-matrix.v1`
- `allowed_inferences[]`: Explizite Liste erlaubter Inferenzen
- `forbidden_inferences[]`: Explizite Liste verbotener Inferenzen (entspricht `does_not_prove`, aber pro-Rolle statt pro-Artefakt-Instanz)
- `trust_surface`: Beschreibung der vertrauenswürdigen Nutzung
- `derivation_scope[]`: Basis-Artefakte (für abgeleitete Artefakte)

**Required:** `artifact_role`, `authority`, `forbidden_inferences[]`  
**Optional:** `allowed_inferences[]`, `trust_surface`, `derivation_scope[]`

**Offene Fragen:**
- Verhältnis zu bestehendem `does_not_prove` in einzelnen Contracts — Migration oder Koexistenz?
- Wie granular sollen `allowed_inferences` sein? (Zu fein: Maintenanceproblem; zu grob: nutzlos)
- Wer validiert Konsistenz zwischen `inference-boundary.v1` und bestehenden Contracts?

**Mögliche Producer:** Governance-Tooling  
**Mögliche Consumer:** Lint-Tools, CI, Agent-Export-Gate  
**Mögliche CI-Nutzung:** Abgleich zwischen Per-Artefakt-`does_not_prove` und Klassen-Level-`forbidden_inferences`

---

### 5.3 `risk-class.v1`

**Zweck:** Maschinenlesbare Risk-Class-Deklaration pro Artefaktinstanz oder -rolle.
Ergänzt `authority` um eine Governance-Risikoklasse.

**Mögliche Felder:**
- `artifact_role`: Zugehörige ArtifactRole
- `risk_class`: Risikoklasse (s. §2.1)
- `escalation_path[]`: Bedingungen unter denen eine höhere Risk-Class angemessen wäre
- `de_escalation_path[]`: Bedingungen unter denen eine niedrigere Risk-Class möglich wäre
- `mandatory_disclaimers[]`: Pflicht-Disclaimers für diese Klasse

**Required:** `artifact_role`, `risk_class`  
**Optional:** `escalation_path[]`, `de_escalation_path[]`, `mandatory_disclaimers[]`

**Offene Fragen:**
- Ist `risk_class` per-Instanz (Laufzeit-Annotation) oder per-Rolle (statisch)?
- Wer darf `risk_class` hochstufen? (Governance-Tool, CI, Mensch?)
- Wie verhält sich `risk_class` bei Federation (cross-repo Artefakte)?

**Mögliche Producer:** Governance-Tooling, CI  
**Mögliche Consumer:** Export-Gate, Agent-Kontrollebene, parity_guard  
**Mögliche CI-Nutzung:** Automatische Warnung wenn `risk_class` einer Artefaktinstanz von deklarierter Klassen-Norm abweicht

---

## 6. Anti-Hallucination-Lint

Die folgenden Lint-Regeln sind Architekturentwürfe für zukünftige CI-Integration.
Keine Implementierung in dieser PR.

### L1 — Verbotene semantische Upgrades

**Beschreibung:** Erkennt wenn ein Artefakt mit niedrigerem `authority` als Input
für eine Entscheidung verwendet wird, die eigentlich `canonical_content` erfordert.

**Beispiel:**
```
# Problematisch:
if context_quality.projection_status == "complete":
    trust_content_as_verified()  # diagnostic_signal → content_truth
```

**Warum gefährlich:** `projection_status=complete` beschreibt Projektion vorhandener
Signale, nicht Inhaltskorrektheit. Stille Aufwertung erzeugt falsche Sicherheit.

**Mögliche CI-Integration:** AST-Analyse nach `diagnostic_signal`-Feldzugriffen
in authority-tragenden Codepfaden.

**Mögliche False Positives:** Defensives Logging, das einen Diagnostic-Signal-Wert
nur ausgibt ohne darauf zu entscheiden.

---

### L2 — Authority Escalation Detection

**Beschreibung:** Erkennt wenn ein Artefakt an einen Consumer übergeben wird,
der eine höhere Authority erwartet als das Artefakt trägt.

**Beispiel:**
```
# Problematisch:
agent_input = agent_query_session  # runtime_observation
generate_canonical_report(agent_input)  # erwartet canonical_content
```

**Warum gefährlich:** Runtime-Observations beschreiben einen Laufzeitmoment.
Als Input für kanonische Reports behandelt erzeugen sie unverifizierten Output.

**Mögliche CI-Integration:** Schnittstellen-Typ-Annotation (`authority: T`) mit
statischer Prüfung.

**Mögliche False Positives:** Debugging-Utilities, die bewusst jeden Typ akzeptieren.

---

### L3 — Missing `does_not_prove`

**Beschreibung:** Erkennt Artefakte, die `authority: diagnostic_signal` oder
`authority: runtime_observation` tragen, aber kein `does_not_prove`/`does_not_mean`-Array.

**Beispiel:**
```json
{
  "authority": "diagnostic_signal",
  "verdict": "pass"
  // kein does_not_prove → Lint-Fehler
}
```

**Warum gefährlich:** Ohne expliziten Disclaimer kann ein Consumer (Mensch oder Agent)
`verdict=pass` als Wahrheitsbeweis lesen.

**Mögliche CI-Integration:** JSON-Schema-Validation mit `required: ["does_not_prove"]`
für alle `diagnostic_signal`-Artefakte.

**Mögliche False Positives:** Legacy-Artefakte ohne dieses Feld (Migration erforderlich,
kein sofortiger Bruch).

---

### L4 — Derived Artifact Misuse

**Beschreibung:** Erkennt wenn ein `navigation_index`- oder `derived_projection`-Artefakt
direkt als Quellartefakt für Content-Entscheidungen verwendet wird.

**Beispiel:**
```
# Problematisch:
content = agent_reading_pack.get_top_chunks()  # navigation_index
verify_as_canonical(content)  # erwartet canonical_content
```

**Warum gefährlich:** `agent_reading_pack` ist Navigation, nicht Content.
TOP_CHUNK_SPANS zeigen Pfade — sie sind keine kanonischen Inhaltsauszüge.

**Mögliche CI-Integration:** Prüfung ob Navigation-Artefakte als Quellartefakte
für Canonical-Operationen übergeben werden.

**Mögliche False Positives:** Utility-Funktionen, die bewusst Navigation-Pfade
zu canonicalen Inhalten auflösen (d.h. die Resolve-Pflicht korrekt implementieren).

---

### L5 — Unsupported Truth Language

**Beschreibung:** Erkennt Feldnamen oder Werte, die implizite Wahrheitsaussagen
machen, in Artefakten mit niedrigerer Authority.

**Beispiel-Verbotsliste:** `understanding_health`, `understanding_score`,
`context_score`, `agent_safe`, `agent_ready`, `safe`, `unsafe`, `proven`,
`supported`, `unsupported`, `true`, `false` (als Verdict-Werte), `green/yellow/red`
(als Verdicts), `verified`, `correct`, `complete`.

**Warum gefährlich:** Diese Terme suggerieren Wahrheitsaussagen, die kein
Lenskit-Artefakt unterhalb von `canonical_content` beweisen kann.

**Mögliche CI-Integration:** Lexikalische Suche nach verbotenen Feldnamen in
Schema-Definitionen und Artefakt-Outputs für niedrige Authority-Klassen.

**Mögliche False Positives:** Test-Fixtures, die diese Terme als Negativbeispiele
verwenden. (Negativtests prüfen explizit Abwesenheit dieser Terme.)

---

### L6 — Export-Risk Violations

**Beschreibung:** Erkennt Artefakte mit `export_constraints: internal_only`
in Export-Pipelines.

**Beispiel:**
```
# Problematisch:
export_bundle([canonical_md, sqlite_index])  # sqlite_index: internal_only
```

**Warum gefährlich:** SQLite-Indices enthalten abgeleitete Informationen, die
ohne den Ursprungskontext missverstanden werden können. Export ohne explizites
Disclaimer erzeugt falsches Vertrauen.

**Mögliche CI-Integration:** Export-Gate prüft `export_constraints` pro Artefakt.

**Mögliche False Positives:** Debug-Exports, die explizit als solche gekennzeichnet sind.

---

## 7. Agent- und RAG-Analyse

### 7.1 Warum Standard-RAG epistemisch unsauber ist

Standard-RAG (Retrieval-Augmented Generation) verbindet Retrieval-Ergebnisse
direkt mit LLM-Input. Das erzeugt folgende epistemische Probleme:

- **Retrieval ≠ Wissen:** Ein FTS-Treffer bedeutet lexikalische Übereinstimmung,
  nicht semantische Relevanz und nicht Vollständigkeit.
- **Retrieval ≠ Wahrheit:** Der abgerufene Text ist korrekt wiedergegeben, aber
  der Agent kann nicht wissen, ob er aktuell, vollständig oder kontextadäquat ist.
- **Rang ≠ Wichtigkeit:** SQLite-FTS5-Ranking ist ein Relevanz-Signal, kein
  Wahrheits-Signal. Ein niedrig geranktes Dokument kann die entscheidende Information
  enthalten.
- **Kein Hit ≠ Keine Information:** Ein Retrieval-Miss beweist nicht, dass die
  Information nicht im Repo existiert.
- **Top-k ≠ Vollständig:** Die besten k Treffer sind nicht alle relevanten Treffer.

### 7.2 Lenskit-Artefakte mit erhöhtem Agent-Risiko

| Artefakt | Risiko | Begründung |
| :--- | :--- | :--- |
| `agent_reading_pack` | Mittel | Navigation wird als Inhalt missverstanden; TOP_CHUNK_SPANS implizieren falsch Wichtigkeit |
| `context_quality` | Hoch | `projection_status=complete` oder hohe Signal-Vollständigkeit kann als "Kontext OK" misgedeutet werden |
| `miss_taxonomy` | Mittel | Miss-Klassifikation kann als Abwesenheitsbeweis gelesen werden |
| `output_health` / `post_emit_health` | Hoch | `verdict=pass` / `status=pass` kann als "Bundle ist korrekt und vollständig" misgedeutet werden |
| `sqlite_index` | Sehr hoch | Cache-Ergebnisse direkt als autoritativen Content behandeln |
| `agent_query_session` | Mittel | Session beschreibt einen Moment, nicht den Repo-Zustand |
| `retrieval_eval_json` | Mittel | Eval-Metriken können als Vollständigkeitsbeweis gelesen werden |

### 7.3 Wie agent-safe exports aussehen könnten

*Hinweis: Dies ist eine architektonische Überlegung, keine Implementierungsaussage.*

Ein agent-safe export würde folgende Bedingungen explizit kommunizieren:

1. **Scope-Deklaration:** Welcher Teil des Repos ist enthalten (kein implizites "alles").
2. **Negative Vollständigkeitsaussage:** Explizit: "Dieser Export enthält nicht
   notwendigerweise alle relevanten Informationen."
3. **Authority-Transparenz:** Welche Artefakte welche Authority tragen.
4. **Inference-Boundary-Deklaration:** Was aus diesem Bundle gefolgert werden darf
   und was nicht.
5. **Retrieval-Neutralität:** Keine Vollständigkeitsaussage für Retrieval-Ergebnisse.

Diese Bedingungen sind Governance-Anforderungen, keine Implementierungsschritte
dieser PR.

### 7.4 Warum diagnostische Artefakte besonders riskant für Agents sind

Diagnostische Artefakte (`output_health`, `context_quality`, `post_emit_health`)
tragen explizite `does_not_mean`-Arrays. Das Problem: LLM-Agents lesen diese
als Text und können den semantischen Gehalt eines `verdict=pass` überbewerten,
weil:

- LLMs tendieren dazu, explizit positive Terme zu verstärken.
- `does_not_mean`-Arrays sind maschinenlesbar, aber für LLMs sind sie Prosatext
  neben einem `pass`-Verdict.
- Ein Agent, der `output_health.verdict=pass` liest, kann implizit schließen:
  "Das Bundle ist in Ordnung" — ohne die `does_not_mean`-Constraints zu
  berücksichtigen.

Dies ist kein Implementierungsfehler — es ist ein epistemisches Risiko, das durch
Governance (explizite Agent-Nutzungsregeln) adressiert werden muss, nicht durch
Artefakt-Änderungen.

---

## 8. Nicht-Ziele

C1 ist **nicht**:

- **Wahrheitsmaschine:** C1 bewertet keine Aussagen auf Wahrheit.
- **Globale Ontologie:** C1 definiert keine vollständige Wissensgraph-Taxonomie.
- **Confidence-System:** C1 vergibt keine numerischen Konfidenz-Scores.
- **Automatische Faktprüfung:** C1 überprüft keine Inhaltsaussagen gegen externe Quellen.
- **Retrieval-Vollständigkeitsbeweis:** C1 beweist nicht, dass Retrieval vollständig ist.
- **Agent-Safety-System:** C1 macht keine Aussagen über die Sicherheit von Agent-Ausgaben.
- **Semantischer Richter:** C1 entscheidet nicht über die semantische Korrektheit von Aussagen.
- **Autonomer Governance-Agent:** C1 ist ein normativer Blueprint, kein Runtime-System.
- **Ersatz für bestehende Contracts:** C1 ergänzt, ersetzt nicht.
- **Vollständige Artefakt-Ontologie:** C1 normiert Inferenzgrenzen, nicht alle Artefakteigenschaften.

---

## 9. Übergangspfad

### Phase 1 — Blueprint (dieser PR)

**Nutzen:** Explizite normative Grundlage für Governance-Entscheidungen.  
**Risiko:** Gering — keine Runtime-Änderungen.  
**Mögliche Drift:** Blueprint wird nicht weitergeführt (Dokumentationsfriedhof).  
**Stop-Kriterium:** Blueprint ist widersprüchlich zu bestehenden Contracts → Konflikte dokumentieren, nicht interpolieren.

### Phase 2 — Contract-Normierung

**Nutzen:** Bestehende Contracts werden um `allowed_inference`/`forbidden_inference`-Felder
ergänzt. `does_not_prove`-Arrays werden gegen die Matrix validiert.  
**Risiko:** Mittel — Schema-Änderungen erfordern Migration bestehender Consumers.  
**Mögliche Drift:** Einzelne Contracts werden normiert, andere nicht → partielle Governance.  
**Stop-Kriterium:** Widerspruch zwischen neuen Feldern und bestehendem Consumer-Verhalten.

### Phase 3 — Lint-Regeln

**Nutzen:** CI-seitige Erkennung von Authority-Eskalationen und verbotenen Inferenzen.  
**Risiko:** Mittel — False Positives können CI blockieren.  
**Mögliche Drift:** Lint-Regeln werden zu restriktiv oder zu permissiv kalibriert.  
**Stop-Kriterium:** False-Positive-Rate > 10% → Regel zurückziehen und überarbeiten.

### Phase 4 — Runtime-Annotation

**Nutzen:** Artefakte tragen zur Laufzeit explizite Inference-Boundary-Annotations.  
**Risiko:** Hoch — Runtime-Änderungen in kritischen Pfaden.  
**Mögliche Drift:** Annotation wird inconsistent emittiert oder von Consumers ignoriert.  
**Stop-Kriterium:** Annotation bricht bestehende Consumer → Migration zuerst.

### Phase 5 — Export-Gates

**Nutzen:** Export-Pipelines prüfen `export_constraints` und `risk_class` automatisch.  
**Risiko:** Hoch — neue Blocking-Guards können legitime Exports blockieren.  
**Mögliche Drift:** Export-Gate wird zu restriktiv → Usability-Problem.  
**Stop-Kriterium:** Export-Gate blockiert > 5% legitimer Exports ohne klaren Governance-Grund.

### Phase 6 — Agent-Integration

**Nutzen:** Agent-Interfaces kommunizieren Inference-Boundaries maschinenlesbar.  
**Risiko:** Sehr hoch — Änderungen an Agent-Interfaces können Downstream-Systeme brechen.  
**Mögliche Drift:** Inference-Boundaries werden zu semantischen Filtern → neue Governance-Ebene nötig.  
**Stop-Kriterium:** Agent-Integration erfordert neue Wahrheitsannahmen → Stopp und Neubewertung.

---

## 10. Systemklassifikation

### 10.1 Nüchterne Bewertung

| Dimension | Aktueller Zustand |
| :--- | :--- |
| **Retrieval-System** | Ja — FTS5-basiertes Retrieval, Ranking, Eval. Gut implementiert. |
| **Evidence-System** | Partiell — Citation-Map, Range-Refs existieren. Evidence-Use in Agents noch nicht implementiert. |
| **Epistemische Infrastruktur** | Emergierend — `does_not_prove`, Authority-Felder, Claim-Boundaries sind vorhanden. Systemweite Normierung fehlt. |
| **Agent-Governance-Layer** | Nicht vorhanden — keine systemweite Governance, keine Inference-Boundary-Enforcement, kein Authority-Eskalation-Lint. |

### 10.2 Aktueller Zustand vs. emergente Richtung

**Aktueller Zustand:**  
Lenskit ist ein Retrieval- und Indexing-System mit diagnostischen Artefakten und
partiellen epistemischen Grenzen. Die bestehenden `does_not_prove`-Implementierungen
sind korrekt und notwendig. Ein systemweiter Governance-Layer fehlt.

**Emergente Richtung:**  
Durch B1 (Context Quality), B2 (Retrieval Miss Taxonomy), A4 (Post-Emit Health),
A1 (Agent Reading Pack Governance) entwickelt sich Lenskit in Richtung eines Systems
mit expliziten epistemischen Grenzen. Ohne C1 bleibt diese Entwicklung additiv ohne
normative Kohärenz.

**Risiken dieser Entwicklung:**

1. **Silent Scope Creep:** Jedes neue diagnostische Artefakt erweitert die semantische
   Oberfläche ohne entsprechende Governance.
2. **Fragmentierte Disclaimer:** `does_not_prove` wird pro Artefakt implementiert,
   aber nicht systemweit aggregiert oder validiert.
3. **Agent-Gefährdung:** LLM-Agents, die Lenskit-Artefakte konsumieren, haben
   keinen maschinenlesbaren Überblick über Inferenzgrenzen.
4. **Authority-Drift:** Ohne explizite Normierung können neue Producer-Komponenten
   Authority-Terme inkonsistent verwenden.

### 10.3 Was Lenskit nicht ist und nicht werden soll

- Lenskit ist **keine Wahrheitsmaschine.** Lenskit sammelt, indiziert, klassifiziert
  und adressiert — es bewertet keine Wahrheit.
- Lenskit ist **kein Vollständigkeitsbeweis.** Kein Lenskit-Artefakt kann beweisen,
  dass ein Repo vollständig erfasst wurde.
- Lenskit ist **kein Safety-Layer.** Lenskit macht keine Aussagen über die Sicherheit
  von Agent-Ausgaben oder LLM-Antworten.

**C1 soll zeigen:** Lenskit entwickelt sich nicht zu einer Wahrheitsmaschine,
sondern zu einem System expliziter epistemischer Grenzen.

---

## Validierung

Vor Abschluss dieses Blueprints wurden folgende Prüfungen durchgeführt:

| Prüfung | Ergebnis |
| :--- | :--- |
| Wird irgendwo Diagnostik implizit aufgewertet? | Nein — §3.2 verbietet `diagnostic → truth` explizit. |
| Wird irgendwo Retrieval mit Wahrheit verwechselt? | Nein — §3.5 und §7.1 trennen Retrieval und Wahrheit. |
| Entsteht irgendwo stiller Authority Drift? | Nein — §4 (P4) und §6 (L2) adressieren Authority Escalation explizit. |
| Werden derived artifacts zu mächtig? | Nein — P2 deklariert non-authoritative by default. |
| Ist die Matrix operationalisierbar? | Ja — §5 liefert Contract-Skizzen; §6 liefert Lint-Regeln. |
| Ist der Blueprint kompatibel mit bestehenden Contracts? | Ja — §2 baut auf bestehenden Termen auf; §1 dokumentiert Vorbefund. |
| Werden bestehende B1/B2-Invarianten verletzt? | Nein — B1/B2-Diagnose-Scopes bleiben unverändert. |
| Widerspricht C1 bestehenden Authority-Deklarationen? | Nein — C1 normiert und ergänzt; keine Umbenennung bestehender Terme. |
| Entsteht eine implizite Vollständigkeitsbehauptung? | Nein — §8 und §10.3 explizit. |
| Entstehen neue globale Scores oder Confidence-Systeme? | Nein — keine Scores, keine numerischen Verdicts. |
