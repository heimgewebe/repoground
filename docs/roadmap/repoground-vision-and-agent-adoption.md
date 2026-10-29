# RepoGround – Vision und ausführbarer Entwicklungsplan

**Stand:** 29. Oktober 2026 (operatives Audit-Update; Ausbauprogramm vom 27.10. bleibt Referenz)

**Rolle:** Strategischer Ausführungsplan, kein Nachweis für Implementierung, Produktionsreife oder abgeschlossene Aufgaben.

**Verbindliche neue Ausbaupriorität (27.10.2026):** Das [massive Ausbauprogramm](repoground-massive-expansion-program.md) ersetzt die frühere Reihenfolge „erst allgemeine Produktivitätssteigerung/20 A/B-Aufgaben nachweisen, dann breit implementieren“. **Zuerst** wird der deterministische Graph-, Änderungs-, Zeit- und Föderationskern einschließlich echter Agenten-Consumer in drei abgegrenzten Arbeitssträngen substanziell ausgebaut. **Danach** folgt die breite Gesamt-Nutzenbewertung. Vorlaufende Nutzenmessungen, historisch fehlende Bundles oder freiwillige Agentenaufrufe sind keine Start- oder Merge-Gates für unabhängige Features; korrektes Verhalten, Versionstreue, Rechte, Tests, CI und bestehende Sicherheitsgates bleiben verpflichtend.

**Bezug:** [Master-Roadmap](repoground-master-roadmap.md) · [Agent Operationalization](lenskit-agent-operationalization-roadmap.md) · [Deterministic Core](../architecture/deterministic-repoground-core.md)

## Optimierungsplan nach Gesamtaudit (29.10.2026)

**Geltung:** Aktuelle operative Prioritäten auf Basis des Live-Audits. Dies ist **ein Plan**, weder Implementierungsnachweis noch zweite Taskstatus- oder Release-Quelle. Das Ausbauprogramm vom 27.10. bleibt fachliche Referenz, aber die nächste operative Arbeit priorisiert nachgewiesenen Nutzwert, aktuelle Agenten-Quellen und geringe Reibung vor weiteren unbewerteten Features. Unabhängige Arbeit wird nicht pauschal blockiert.

**Ziel:** Ein Agent findet in einem aktuellen Repository die richtigen belegten Implementierungsstellen und erledigt eine reale Aufgabe mit **mindestens gleicher Korrektheit und geringerem Gesamtaufwand** als mit Git/Dateisuche allein. Weder Artefaktzahl noch Graphgröße, CI-Grün oder freiwillige Toolaufrufe sind selbst Erfolgskriterien.

### A. Gemessene Ausgangsbasis

| Gebiet | Stand 29.10.2026 | Aussagegrenze |
| --- | --- | --- |
| Produktionsversion | GitHub `main`, aktivierte Immutable-Runtime und RepoGround-Bundle verwenden `88584eee78a68c717bd9dc61bedbc865eed27fea`; 27/27 GitHub-Checks erfolgreich | Kein automatischer Agenten-Nutzenbeweis |
| Graphgeschwindigkeit | Vier erneute Aufrufe über die **aktive Runtime**: Mittel **3,28 s**, vorheriger Vergleich **12,80 s**; je Ziel übereinstimmende Antwort-Hashes | Direktabfrage, nicht Agenten-End-to-End |
| Fleet-Aktualität | 12 gesunde Bundle-Einträge, davon 10 `fresh_exact` und 2 `stale_head`: `heim-pc`, `grabowski` | Die autoritative `metarepo/fleet/repos.yml` nennt 11 Mitglieder **ohne Grabowski** |
| Nativer MCP-Client | Runtime neu, `--repo-root` /home/alex/repos/repoground jedoch auf `7300ab30` (37 Commits hinter aktuellem `main`), `live_freshness=stale` | Grabowskis separate RepoGround-Frontdoor verwendet das aktuelle Publikationscheckout |
| Beziehungsgraph | 119.202 Beziehungen, 50.025 als `resolved`; Python-Aufrufgraph 23.640/88.499 eindeutig aufgelöst (= 26,7 %) | `S0` ist nicht `S1`, keine vollständige Wirkungsanalyse |
| Standard-Suche | Aktuelles `retrieval_eval_json`: **1/20** Fragen-Recall@10 und **1/60** Zielfundstellen-Recall; Default-Promotion blockiert | Kanonisches **lexikalisches** Goldset, keine Aussage über alle spezialisierten Suchwege |
| Agenten-Suchweg | Sechs Auditfragen: **3/6** richtige Implementierungsdatei in Top-5, **2/6** auf Rang 1; Symbolsuche und `range_get` funktionieren | Kleine gezielte Stichprobe |
| Alte Agenten-A/B-Messung | 20 gepaarte Codex-Aufgaben, Git Ø 25,107 s, mit RepoGround Ø 39,852 s (**+59 %**), gemeldete Eingabe-Tokens **+32 %** | Vor der jüngsten Beschleunigung; Ziel-ID in der Antwort beweist nicht volle Korrektheit |
| Betrieb | Fleet-Timer aktiv und letzter geprüfter Lauf erfolgreich; ca. 3,2 GiB Bundle-Bestand | Ein gesunder Altbestand ist nicht automatisch aktuell |

**Primärbelege und Wiederholung:** [Graphintegration #1362](https://github.com/heimgewebe/repoground/pull/1362), [Beschleunigung #1363](https://github.com/heimgewebe/repoground/pull/1363), [20-Paare-Messung](../proofs/repoground-agent-utility-20pairs-20261029.md), [Produktionsintegration](../proofs/repoground-production-graph-integration.md), `docs/retrieval/review_queries.v1.json`, `retrieval_eval_json` im commitgebundenen Bundle und [Fleet-Mitglieder](https://github.com/heimgewebe/metarepo/blob/main/fleet/repos.yml). Die Tabelle ist eine datierte Momentaufnahme und muss vor Änderungen am jeweils zuständigen Live-System überprüft werden.

### B. Arbeitspakete, kleinster wirksamer Eingriff

#### RG-OPT-01 – Echten MCP-Checkout an die beabsichtigte Revision binden (P0)

**Ursache:** Das neue MCP-Skript läuft mit altem `--repo-root`, wodurch `live_freshness` korrekt `git_head_mismatch` meldet und `change_evidence_pack` gegebenenfalls nicht zum aktuellen Arbeitsstand gehört.

**Umsetzung:** Im zuständigen Client-/Host-Setup den richtigen Checkout mit dem intendierten Git-Stand herstellen oder den MCP-Prozess auf einen vorhandenen exakt gebundenen Checkout zeigen lassen. Die Auswahl hängt vom tatsächlichen Agenten-Task ab; die immutable Publikationsquelle ersetzt nicht automatisch einen editierbaren Worktree. Keine pauschalen Resets, kein verdeckter Snapshot-Refresh, kein Abschalten der Freshness-Erkennung.

**Abnahme:** Echter Client-Roundtrip `initialize` → tools/list → live_freshness → ask_context und `change_evidence_pack` für einen bekannten `base..target`: `fresh` bei passendem, sauberem Checkout; `stale` bei bewusst falschem Commit; korrekte Quellen und identische Diffbindung. Bei nicht verfügbarem Kontext geht native Git-/Dateisuche weiter. **Owner:** Grabowski, Client-/Host-Repository.

#### RG-OPT-02 – Fleet-Freshness und Zuständigkeit dauerhaft klären (P0)

**Ursache:** `heim-pc` hinkt der aktuellen Git-Revision hinterher; `grabowski` erscheint als gesundes, aber veraltetes Legacy-Bundle außerhalb der elf kanonischen Fleet-Mitglieder.

**Umsetzung:** Den bestehenden Scheduler/Publisher auf wirkliche Änderungsaufnahme prüfen; `heim-pc` über denselben Publikationspfad nachführen, sofern nicht bereits durch einen regulären Lauf geschehen. Für `grabowski` explizit entscheiden: entweder als gewolltes Fleet-Mitglied im Metarepo aufnehmen **oder** eine bereits vorhandene zuständige Publikationsroute benutzen und den Legacy-Katalogeintrag korrekt behandeln. Keine zweite Queue, keine heimliche Fleet-Erweiterung oder erzwungene Full-Scans auf Lesewegen.

**Abnahme:** Für jeden tatsächlich benötigten Consumer ein frisches, revisions-/hashgebundenes Bundle nach realem Quellupdate; Verzögerungen über **zwei reguläre Timerläufe** sind als Ursache/Fehler sichtbar. `stale` bleibt bei echter Differenz wahr; nur der Publisher schreibt. **Owner:** Grabowski, RepoGround/Metarepo je tatsächlicher Ursache.

#### RG-OPT-03 – Richtige Implementierungsdatei beim ersten Versuch finden (P1, Haupthebel)

**Ursache:** Die breite Wortsuche mit `or_relaxed` übergewichtet teils Tests und Dokumentation. Das vorhandene exakte Symbol-/Pfad-Routing wird bei natürlichen Implementierungsfragen nicht zuverlässig gewählt.

**Umsetzung:** Die 20 kanonischen Goldsetfragen und die sechs Auditfragen mit eingefrorenen Commits aufschlüsseln; `query_existing_index`, `find_symbol`, vorhandene aufgabenspezifische Routen sowie `rg`/`git grep` vergleichend prüfen. Exakte Identifier und Dateinamen vorrangig durch **bestehende** Symbol-/Pfadfunktionen auflösen; breite Mischfragen klein und nachvollziehbar aufteilen; Ränge für Implementierung, Tests und Verträge begründet gewichten. Nur minimale Routingkorrektur samt Negativtests, keine neue Suchdatenbank und kein Standard-Embedding-Reranking.

**Abnahme:** Zielwerte **mindestens 5/6** korrekte Implementierungsdateien in Top-5 der Auditstichprobe und **mindestens 10/20** Fragen-Recall@10 im kanonischen Goldset; kein Verlust gültiger Belege/Range-Auflösung, keine unbelegte S1-Promotion. Ergebnisse gegen ursprüngliche Messung **und** native Git-Suche ausweisen. Ziele werden nicht durch Umformulieren des Goldsets erreicht. **Owner:** Grabowski, RepoGround-Retrieval. Eine separate aktive Agent-Tool-Auswahl-Lane arbeitet bereits an verwandter Routingdisziplin: Ergebnisse übernehmen, keine konkurrierenden Regler bauen.

#### RG-OPT-04 – Tool- und Kontextaufwand an der Aufgabe ausrichten (P1)

**Ursache:** Der alte Codex-Vergleich benötigte 78 zusätzliche RepoGround-MCP-Aufrufe und +32 % gemeldete Eingabe-Tokens, ohne nachgewiesenen Qualitätsgewinn.

**Umsetzung:** Für bekannten Pfad/einzelnen Identifier normale Datei- und Git-Suche nutzen; für unbekannte eingehende Abhängigkeiten, mehrstufige Relationen, revisionsgebundene Auswirkungen oder Testfolgen RepoGround gezielt verwenden. Doppelte `discover`/`preflight`-, unnötige Range- und Kontextaufrufe vermeiden, bestehende Budgets respektieren. Bei `stale`, `unavailable`, geringer Coverage oder `degraded` offen zur Primärquelle zurückfallen.

**Abnahme:** Echte Agenten-Traces dokumentieren Auswahl, Fundstellen, Anzahl Aufrufe, Gesamtzeit, Tokens, fehlgeschlagene Versuche und Korrektheit. Weniger Werkzeugaufrufe allein genügt nicht; Antwortqualität darf nicht sinken. **Owner:** zuständiger Consumer-Owner via Grabowski; abgestimmt mit der bestehenden Tool-Auswahl-Lane.

#### RG-OPT-05 – Agentennutzen auf der neuen produktiven Runtime belegen (P1)

**Messaufbau:** Mindestens 20 reale gepaarte Aufgaben **über mehrere Repositories**, jeweils identische Prompts, Modell, Checkout/Commit, Ressourcenrahmen und Bewertungsstandard. Gruppen getrennt betrachten: bekannte Dateistelle, unbekannte eingehende Abhängigkeit, relevante Tests, `base..head-Folgen`, repositoryübergreifender Vertrag. Tools bleiben freiwillig nutzbar, nicht per Prompt erzwungen.

**Abnahme:** Tatsächlicher Toolkonsum, korrekte Zielfundstellen **und** fachliche Lösung, Nacharbeit, vollständige Bearbeitungszeit inklusive Kontext-/Snapshotbetrieb, Input-/Output-/Cache-Tokens und Fehlversuche je Paar. RepoGround nur für belegbar bessere Aufgabenklassen als Default empfehlen. Bei ausbleibendem Vorteil selektive Nutzung statt erzwungener Agentenarbeit. Neue unabhängige Feature-PRs werden nicht allein wegen einer laufenden Messung blockiert. **Owner:** Grabowski; bei entscheidenden Stichproben unabhängiger read-only Gegencheck durch Großen Adler.

#### RG-OPT-06 – Graphabdeckung nur dort vertiefen, wo sie reale Lücken schließt (P2)

**Umsetzung:** Fehlende Beziehungen aus echten Impact-/Testfragen sammeln; wenige nachweisbar eindeutige Python-/Konfigurationsfälle ergänzen, jeweils mit positiven und negativen Regressionsbelegen. S0/S1, Parserlücken und Lösch-/Umbenennungsgrenzen sichtbar halten. Keine künstliche Erhöhung der 26,7-%-Quote und kein neues Parallelgraph-System.

**Abnahme:** Bessere korrekte Test-/Abhängigkeitsfunde bei gleich bleibender Falschpositiv-Rate und reproduzierbaren Diff-, Manifest- und Hashbindungen. **Owner:** Grabowski, getrennte Parser-/Graph-Lane nach Bedarf.

#### RG-OPT-07 – Historische Quellstand-Pins getrennt abschließen (P2, Recovery)

[PR #1344](https://github.com/heimgewebe/repoground/pull/1344) bleibt ein eigenständiger Draft mit im Audit fehlgeschlagenem `pytest-full.` Aktuellen Head/CI erneut lesen, tatsächliche Ursache beheben und an einer **späteren normalen Fleet-Publikation** belegen, dass der benötigte historische Quellstand weiterhin verfügbar ist. Keine pauschale Aufhebung sinnvoller Aufbewahrungsgrenzen; nicht mit Suche/Graph zusammen mergen. **Owner:** bestehende zuständige Writer-Lane über Grabowski.

### C. Reihenfolge, Erfolg, Nicht-Ziele

1. **Zuerst RG-OPT-01 und -02:** Agenten müssen aktuelle und richtig zugeordnete Quellen sehen, bevor ein A/B-Test Aussagekraft hat.
2. **Dann RG-OPT-03 und -04:** Bestehende Suche und Toolwahl reparieren, nicht die Zahl der Funktionen erhöhen.
3. **Danach RG-OPT-05:** Aufgabenklassen einzeln gegen reine Git-Werkzeuge bewerten und die bevorzugte Route nur nach tatsächlichem Nutzen wählen.
4. **RG-OPT-06/07** nur entlang realer Lücken bzw. vorhandener Recovery-Zuständigkeit. Keine vorgezogene Mikrooptimierung des nun ca. 3,3-s-Graphlesepfads, solange schlechte Trefferraten die Gesamtarbeit dominieren.
5. **Betriebsnachweis statt Formalstatus:** Ein Plan, PR, Merge oder grüner Build ist noch kein abgeschlossener Nutzerweg. Für jede tatsächliche Änderung gilt frischer Git-/Runtime-/Client-Readback plus betroffene Regressionen, ohne unnötige Freigabeschleifen oder Architekturaufbau.

**Abschlusskriterium der Optimierungswelle:** Bei einem vorab festgelegten Aufgabenmix liefert RepoGround aktuelle, auflösbare Belege und gegenüber Git **bessere Trefferqualität oder geringere Gesamtzeit bei mindestens gleicher Korrektheit**. Fehlt dieser Nachweis, bleibt RepoGround ein selektives Werkzeug; es wird nicht durch Nutzungszwang zum Erfolg erklärt.

---

## 1. Auftrag

**RepoGround wird die deterministische, revisionsgebundene Wissens-, Struktur- und Veränderungsschicht, die Heimgewebe-Agenten bei realen Entwicklungsaufgaben nachweislich besser macht.**

Der Nordstern ist *nicht* die Zahl der Snapshots, Werkzeuge oder erzeugten Metadaten. Entscheidend sind korrekte Lösungen, weniger wiederholte Analyse, bessere Änderungsfolgenabschätzung, aktuelle Belege und geringere Gesamtkosten.

```text
Git / Quellcode / Verträge / explizite externe Ereignisbelege
     ↓
RepoGround: deterministisch erfassen, indexieren, vergleichen, adressieren
     ↓
Aufgabenspezifischer, revisionsgebundener Kontext (CLI / MCP)
     ↓
Claude / Codex / Grabowski: interpretieren, planen, ggf. umsetzen
     ↓
Autoritative Rückprüfung (Git, CI, NixOS, Systemd, Testsysteme)
     ↓
Verifizierte Ergebnisse stehen späteren Aufgaben wieder zur Verfügung
```

Langfristig entsteht eine **temporale Veränderungslandkarte**: Was existiert? Was hat sich verändert? Welche bekannten Beziehungen könnten betroffen sein? Welche frühere technische Erfahrung ist belegbar? Was bleibt ungewiss?

### Verantwortungsgrenzen

- **RepoGround ist kein Agent.** Der Standardkern bleibt deterministisch, nachvollziehbar und lesend. Keine versteckten LLM-Entscheidungen, automatischen Review-Urteile, Patches, Commits oder Merge-Freigaben.
- **Agenten interpretieren und handeln.** Claude und Codex entwickeln, Grabowski ist der autorisierte Writer/Integrator. RepoGround stellt überprüfbare Daten bereit.
- **Keine zweite Wahrheitsquelle.** `canonical_md` ist die kanonische *Bundle-Inhaltsquelle*; andere RepoGround-Artefakte sind Navigation, Diagnose und abgeleitete Beziehungen. Aktueller Code-/Git-/CI-/Runtimezustand stammt weiterhin aus seinen jeweiligen Live-Primärquellen.
- **Beobachtet ≠ abgeleitet ≠ bestätigt.** Ein struktureller Zusammenhang beweist keine Laufzeitkausalität. Ein Testverweis beweist keine Testvollständigkeit. Gleiches gilt für Sicherheit und Produktionsreife.
- **Keine konkurrierende Systemsteuerung.** Atlas erfasst explizite Dateisystemzustände, Chronik hält Ereignisse fest, Bureau/Grabowski organisieren autorisierte Arbeit; RepoGround kann solche Belege später lesend verknüpfen, ersetzt die Zuständigkeiten aber nicht.
- **Kein Einsatz um des Einsatzes willen.** Kurze Aufgaben dürfen direkt mit Git/Dateisuche erledigt werden. Wenn RepoGround nicht verfügbar oder veraltet ist, ist ein expliziter Fallback besser als ein künstlicher Arbeitsstopp.

## 2. Ausgangslage und ehrliche Beleglage

**Vorhanden:** Bundle-/Manifest-Produktion, Range-/Citation-Adressen, Symbolsuche, allgemeine und spezielle Retrieval-Verfahren, opt-in Review-Intent-Routing, Python-Strukturgraphen, begrenzte Impact-Projektionen, read-only MCP und inkrementelle Retrieval-Snapshots samt optionalem Watcher. Erste Cross-Repo-Föderation besteht, bleibt aber unvollständig.

**Nicht gleichbedeutend mit Alltagstauglichkeit:** Viele dieser Funktionen sind technisch implementiert, aber nicht notwendigerweise als aktuelle Bundles publiziert oder von realen Agenten tatsächlich verwendet.

**Beobachtungen, nicht verallgemeinern:**

- Historische [kanonische Retrieval-Messung](../proofs/repobrief-canonical-retrieval-measurement-v1-proof.md): 5 % Fragen-Recall@10, 1,67 % Einzelziel-Recall auf einem expliziten damaligen Commit und Goldstandard.
- Separater [Review-Intent-Nachweis](../proofs/review-intent-router-v1-target-proof.md): spezialisierte deterministische Suche kann auf *anderem* Messstand deutlich besser sein. Das beweist keine aktuelle Default-Verbesserung.
- [PR #1350](https://github.com/heimgewebe/repoground/pull/1350) enthält externe Claude-Nutzungsbeobachtungen: `doctor` und `build` funktionierten; eine einfache `query` verfehlte den relevanten Implementierungsort. Keine produktive Codekorrektur in diesem PR.
- Ein datiertes Heim-PC-Readback vom 27.10.2026 ergab für Grabowskis RepoGround-Frontdoor `publication_unavailable` / `no_bundle_available`. Beim Beginn des ersten Arbeitspakets **frisch neu prüfen**; dieser historische Check ist kein dauerhafter Betriebsstatus.
- Die bisherigen Claude-A/B-Läufe belegen gezielt die Nutzung von Snapshot-Freshness, **nicht** eine generelle Verbesserung von Coding-Agenten. Der ursprüngliche Codex-Benchmark bleibt getrennt.

**Historische Folgerung (in der Reihenfolge abgelöst):** Der frühere Vorrang von Betrieb, Adoption und Suche vor breiter Feature-Arbeit gilt nicht mehr als programmweite Implementierungssperre. Diese drei Fähigkeiten werden parallel zum großen Ausbau weiter verbessert; der neue Schwerpunkt liegt auf Veränderungsgraph, Zeitgeschichte, Föderation und darauf aufbauenden Agentenprodukten.

## 3. Produktstufen

| Stufe | Nutzbarer Effekt | Nachweisgrenze |
| --- | --- | --- |
| A – Code finden | Relevante Dateien, Symbole, Tests und Verträge schneller mit Belegen finden | Kein allgemeines Repositoryverständnis |
| B – Veränderung analysieren | Zwischen zwei Revisionen geänderte Symbole und abhängige Stellen lokalisieren | Kein vollständiger Wirkungsradius |
| C – Geschichte nutzen | Vorherige Revisionen, reproduzierte Fehler und externe Testbelege wiederfinden | Zeitliche Nähe beweist keine Ursache |
| D – Mehrere Repositories verbinden | Nachweisbare Schnittstellen und Abhängigkeiten über Projekte hinweg finden | Keine automatisch vollständige Systemkarte |
| E – Auf Ereignisse reagieren | Neue Änderung triggert definierten Vergleich oder begrenzten Agentenkontext | RepoGround wird dadurch kein Agent |

## 4. Arbeitspakete und Abnahmebedingungen

Die Kennungen unten sind **Plan-IDs**, noch keine angelegten Bureau-Aufgaben. Bei Abarbeitung jeweils eine separate kanonische Task-ID, Ausgangsrevision, genau ein Scope, Tests und einen belastbaren Readback anlegen. Bereits existierende Features nicht neu implementieren.

### P0 – Betrieb und echte Agentenadoption (parallel fortführen, kein Ausbau-Gate)

#### RG-P0-01 – Aktuelle Bundles zuverlässig bereitstellen

- Aktuelle RepoGround-Installation, Git-Stand, Heim-PC-Produktionspfade und kanonischen Publikationskatalog prüfen. Den bestehenden Pfad reparieren, keine zweite Publisher- oder Snapshotarchitektur erfinden.
- Schreibende Veröffentlichung strikt von lesenden `discover`, `preflight`, `query`-Aufrufen trennen. Leser dürfen niemals stillschweigend einen neuen Snapshot erzeugen.
- **Abnahme:** Für mindestens ein echtes Heimgewebe-Repository lässt sich ein eindeutiges, hash- und revisionsgebundenes Bundle über Grabowski mit `repoground_bundle_discover`, `repoground_preflight` und einem realen `repoground_query` abrufen. `stale` und `unavailable` werden korrekt offengelegt. Manifest, CLI-/MCP-Ausgabe und aktuelle Primärquellen sind dokumentiert.
- **STOP:** Bei fehlender Autorität, fremder Lease oder ungeklärter Revision nicht mutieren. Nur den konkreten Blocker dokumentieren; keine Sicherheitsarchitektur neu erfinden.

#### RG-P0-02 – Agenten verwenden RepoGround wirklich

- Integrationsreihenfolge: **Grabowski → Claude Code → Codex → weitere Agenten nach Nutzennachweis**. Jeder Consumer erhält eine kleine, reviewte eigene Host-/Repositorykonfiguration, statt dass RepoGround fremde Projekte ungeprüft verändert.
- Für passende Aufgaben (`basic_repo_question`, `pr_review`, `change_impact`, `find_relevant_tests`, `ground_claim`) vor der Kontextsuche Repoidentität, Git-Revision, Bundle-Freshness, Aufgabenprofil und verfügbare read-only Werkzeuge prüfen.
- **Wenn gesund:** tatsächliche MCP-/CLI-Suchfunktion verwenden, kompakte Quellbereiche und Revisionen in der Agentenarbeit berücksichtigen. **Wenn nicht gesund:** `no_bundle_available`, `stale`, `ambiguous` etc. als Diagnose kennzeichnen; regulär mit Git, `rg` oder der bestehenden Agentensuche fortfahren. Sicherheits- und Live-Prüfungen werden nicht durch RepoGround ersetzt.
- **Abnahme:** Pro Consumer ein echter, wiederholbarer End-to-End-Task mit **nachgewiesenem Toolaufruf**, korrekter Quelle, passendem Modell-/Checkout-Kontext und getestetem Fallback. „MCP eingerichtet“ oder „Tool verfügbar“ ist kein Nutzungsnachweis.
- Credentials dürfen niemals in RepoGround-Bundles, Repositorytexte oder Benchmarkartefakte gelangen.

#### RG-P0-03 – Realen Mehrwert gegen normale Agenten messen (Gesamtbenchmark nach Ausbau)

**Neue Terminierung:** Die mindestens 20 realen A/B-Aufgaben bleiben als spätere Gesamtabnahme erhalten, sind aber **keine Voraussetzung für RG-XG/RG-XH/RG-XF/RG-XC-Implementierungen**. Kleine Tests während der Entwicklung sind zulässig, ohne über das Ausbauprogramm zu entscheiden.

- Vor jeder Messreihe Aufgaben, Goldstandard, Modell, Revision, Ressourcenbudgets, Bewertung und Stop-Kriterien fixieren.
- Mindestens **20 reale** Aufgaben aus **mehreren** Heimgewebe-Repositories: Code-Navigation, Fehleranalyse, Testfindung, Änderungs- und Vertragsfolgen, Patch-Vorbereitung. Keine künstlichen „ist RepoGround-Snapshot fresh?“-Aufgaben als allgemeiner Nützlichkeitsbeleg.
- Jeder Agent erledigt Vergleichsaufgaben **mit** und **ohne** optional verfügbares RepoGround; der Agent darf Tools normal wählen. Tatsächliche Verwendung wird gemessen, nicht erzwungen.
- **Abnahme:** vollständige, identitätsgebundene A/B-Quittungen inklusive Fehlern: richtige Zielfundstellen und Aufgabenergebnisse, Recall@k/Einzelziel-Recall, Nacharbeit, Toolaufrufe, Tokens und gesamte Zeit **einschließlich** Snapshot-Erzeugung/Betrieb. Pro Aufgabenklasse separate Entscheidung, keine globale Promotion aus Einzelbeispielen.

### P1 – Suchqualität parallel zum massiven Ausbau verbessern

#### RG-P1-01 – Vorhandene deterministische Suchwege richtig nutzen

- Claudes `resolve_canonical_md`-Befund aus PR #1350 am aktuellen Commit reproduzieren.
- Standard-`query` mit `query_existing_index`, `find_symbol`, vorhandenem Review-Intent-Router und direkter `rg`/`git grep`-Suche vergleichen.
- Nur nach Ursachenbeleg die **kleinste** sinnvolle Verdrahtung für passende Aufgabenprofile oder Identifier durchführen. Keine zweite Indexarchitektur, kein voreiliges Embedding-Default.
- **Abnahme:** fixierter Goldstandard, Ränge, Recall/MRR, Einzelzielquote, Quell-/Range-Gültigkeit und Nichtregression nach Kategorie. Bestehende Interfaces bleiben kompatibel.

#### RG-P1-02 – Passenden Kontext in Agentenantworten wirksam machen

- Taskprofil-Routing und begrenzte Evidenzpakete in den tatsächlichen Consumer-Verträgen nutzbar machen. Fehler und Degradierung explizit zurückgeben.
- **Abnahme:** mindestens zwei reale Agenten nutzen nachweislich die passende Route und lösen eine dokumentierte Klasse von Aufgaben besser als mit ihrer nativen Suche.
- Optionales Embedding-Reranking bleibt außerhalb des deterministischen **Standardkerns** und braucht einen eigenen Mess- und Freigabepfad.

### P2 – Change Intelligence als Kern des großen Ausbauprogramms

#### RG-P2-01 – Revisionsgebundener Änderungsbericht

- Explizites Git-`base..head` oder eindeutig gebundenes Dirty-Delta auf geänderte Dateien und Symbole abbilden; bekannte Aufrufer, Schnittstellen, relevante Tests und Verträge aus *bestehenden* Graph-/Impactflächen verbinden.
- Relationen mit Richtung, Belegart, Revision und Unsicherheitsgrenze liefern. „Potentiell betroffen“ ist weder ein bestätigter Fehler noch ein Review-Urteil.
- **Abnahme:** ein echter Heimgewebe-Änderungsfall mit präzisen, wiederauflösbaren Belegen und nachgewiesen nützlichem Agentenkontext; Ergebnis ist bei identischen Inputs deterministisch.

#### RG-P2-02 – Veränderung inkrementell und historisch verfolgen

- Vorhandene `retrieval-snapshot`-/Watcher-Funktionen nutzen. Je Revision nur relevante Teile erneuern, alte Generationen atomar erhalten und Delta-Identitäten dokumentieren.
- **Abnahme:** mindestens zwei reale aufeinanderfolgende Revisionen reproduzierbar vergleichen; Refresh-Kosten, Änderungslatenz, Fehlerfall und Recovery sind gemessen; kein unnötiger Full-Scan bei bloßen Leseanfragen.

### P3 – Technische Zeitgeschichte und Cross-Repo-Beziehungen

#### RG-P3-01 – Repository-übergreifende Belege

- Vorhandene Föderation für explizite API-/Dienst-/Konfigurationsbeziehungen nutzen und identitäts-/versionsgebunden härten.
- **Abnahme:** eine tatsächlich repository-übergreifende Heimgewebe-Aufgabe erhält belegte Beziehungen, ohne unbekannte Links, Vollständigkeit oder Runtime-Verhalten zu erfinden.

#### RG-P3-02 – Technische Vorgeschichte abrufbar machen

- Commit- und Vertragsgeschichte mit *explizit adressierten* externen Chronik-, GitHub-, CI- und Grabowski-Belegen verknüpfen. Nur autorisierte lesende Schnittstellen; Primärsysteme behalten ihre Wahrheit.
- **Abnahme:** ein wiederkehrender Vorfall lässt sich mit früheren Revisionen und verifizierten Prüfergebnissen schneller analysieren. Keine Kausalbehauptung aus reiner zeitlicher Korrelation.

### P4 – Proaktive, aber deterministische Unterstützung

#### RG-P4-01 – Ereignisgesteuerte Beobachtung und Handoff

- Relevante Git-/CI-Ereignisse können definierte, deduplizierte Analysen auslösen und einen kleinen Quellenbericht an Grabowski/Bureau liefern. RepoGround entscheidet **nicht** über Reparatur, Review-Freigabe oder Deployment.
- **Abnahme:** ein realer Änderungsfall führt zu genau einem überprüfbaren Kontext-Handoff und einem extern bestätigten Ergebnis, ohne Endlosschleifen oder unerlaubte Mutationen.

#### RG-P4-02 – Nützliche Verfahren behalten, unnütze zurückbauen

- Durch tatsächliche Nutzung, Aufgabenqualität und Betriebsaufwand regelmäßig prüfen, welche bestehenden Such- und Artefaktflächen einen messbaren Zusatznutzen bringen.
- **Abnahme:** neue Features nur mit konkretem Consumer und Messbeleg; ungenutzte Komplexität kontrolliert reduzieren, stabile Contracts nicht überraschend brechen.

## 5. Verbindliche Agentennutzung – sobald P0 einen gesunden Pfad belegt

Für die genannten passenden Aufgaben wird diese *nicht blockierende* Disziplin in Grabowski, Claude Code und Codex nach und nach in ihren jeweiligen Konfigurationen eingeführt:

1. **Bindung:** Repositoryidentität, aktueller Git-Commit, Worktree-Status und gegebenenfalls angefragter Diff aus Primärquellen.
2. **Preflight:** genau ein verfügbarer, gesunder RepoGround-Katalogtreffer und passendes Aufgabenprofil. Bei Veraltung/Mehrdeutigkeit keine verdeckte Ersatzwahl.
3. **Echter Konsum:** mindestens die für die Aufgabe passende read-only Suche/Range-Abfrage, soweit nützlich und verfügbar. Antworten enthalten nachvollziehbare revisionsgebundene Fundstellen.
4. **Native Rückprüfung:** aktuelle Git-, Test-, CI- und Betriebsaussagen unabhängig verifizieren, bevor der Agent daraus Änderungen oder Freigaben ableitet.
5. **Fallback:** bei fehlender RepoGround-Verfügbarkeit die normalen Git-/Dateiwerkzeuge verwenden und Diagnose offenlegen. Ein freiwilliger Kontextdienst darf keine sachfremde Sicherheits- oder Betriebsblockade erzeugen.
6. **Verbrauchsbeleg:** Toolaufruf, relevanter Kontext, Gesamtkosten, Belegqualität und tatsächliches Arbeitsergebnis registrieren, ohne Credentials oder geheime Pfade zu veröffentlichen.

**Kein Globalzwang:** einfache `git grep`-Aufgaben bleiben möglich. Verpflichtend sind die *Prüfung der Eignung und ehrliche Beleglage*, nicht blindes „RepoGround einmal aufrufen“.

**Wichtig:** Eine Ergänzung von `AGENTS.md` in diesem Repository beweist **keine** aktuelle Nutzung durch andere Agenten. Andere Repositories und Host-Konfigurationen benötigen separate kleine Integrationsänderungen samt End-to-End-Nachweisen.

## 6. Erfolg, Promotion und Stop

| Gate | Erfolgsbeleg | Wenn nicht erfüllt |
| --- | --- | --- |
| Betrieb | Eindeutiges frisches Bundle + reale discover/preflight/query-Antwort | Tool als unavailable markieren, native Suche nutzen |
| Adoption | tatsächlicher MCP-/CLI-Tool-Read + gültige Referenz + Consumer-Ergebnis | „installiert“ nicht als benutzt zählen |
| Retrieval | fester Goldstandard, Recall/MRR/Einzelziele, Nichtregression | alten Default beibehalten |
| Agentennutzen | echte Aufgaben mit vorher festgelegten Kriterien und Gesamtkosten | optional lassen oder gezielt zurückbauen |
| Change Intelligence | commit-/diffgebundene, prüfbare Beziehungen | unbekannte Reichweite sichtbar halten |
| Föderation/Chronik | autoritative externe Quellen und nachvollziehbare Identität | unbewiesene Relationen ausschließen |

Konkrete Default-Schwellen für jede Aufgabenklasse werden **vor** der jeweiligen Messung im Goldstandard festgelegt (etwa Aufgabenerfolg, tolerierbare Mehrkosten und Vermeidung wesentlicher Regressionen). Ein hoher Recall-Wert allein beweist keine allgemeine Agentenqualität.

## 7. Neue Ausführungsreihenfolge: drei parallele Ausbau-Threads

**Beschluss vom 27.10.2026:** Das [massive Ausbauprogramm](repoground-massive-expansion-program.md) und seine drei Arbeitsaufträge sind jetzt der verbindliche Einstieg, nicht mehr die frühere Reihenfolge „RG-P0-01, dann Adoption, erst danach Features“.

1. [Thread 1: Strukturgraph und Veränderungsanalyse](repoground-expansion-thread-1-graph.md) – echte Parser-/Graph-/Impact-Implementierung.
2. [Thread 2: Föderation und technische Geschichte](repoground-expansion-thread-2-federation-time.md) – revisionsgebundene Geschichte und belegte Cross-Repo-Beziehungen.
3. [Thread 3: Agentenprodukt und Ereignisfluss](repoground-expansion-thread-3-consumers.md) – nachvollziehbare CLI/MCP-Berichte, aktive Consumer und inkrementeller Handoff.

**Gleichzeitig ausführbar:** Je Thread ein unabhängiger Grabowski-Writer-Scope mit eigenem Branch, Lease, Task/PR und disjunkten Dateipfaden. Keine parallelen Änderungen an denselben Modulen. Öffentliche Antwort-Verträge werden als kleine Folge-PRs koordiniert; Risiken blockieren nur die jeweilige betroffene Mutation, nicht das ganze Programm.

**Bereits historische P0-01-Ergebnisse:** Ein tatsächlicher Fleet-Publisher, gesunde Bundles sowie Grabowski/Codex-MCP-Nutzung wurden am 27.10.2026 beobachtet. Das ist kein Freibrief, aktuelle Verfügbarkeit nicht mehr frisch zu prüfen. Die ursprünglichen P0-IDs werden nicht als erneut ungeprüft offen oder als globaler Stop angenommen.

Die Plan-IDs ersetzen **nicht** die kanonischen Taskstatus in `docs/tasks/index.json` beziehungsweise Bureau. Jede Implementierung erhält einen kleinen Scope, Tests und revisionsgebundenen Merge-/Produktions-Readback.

**Entscheidung:** Erst den echten deterministischen Mehr-Repo-Veränderungskern massiv ausbauen und anschließend den systemweiten Nutzen evaluieren. RepoGround bleibt ein Werkzeug für Agenten, kein Agent selbst.
