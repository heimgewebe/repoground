# AUSFÜHRUNGSAUFTRAG 1/3 – Strukturgraph und Veränderungskern

**Priorität:** P0 Ausbau · **Projekt:** [RepoGround](https://github.com/heimgewebe/repoground) · **Programm:** [massiver Ausbau](repoground-massive-expansion-program.md) · **Stand:** 27.10.2026

**Dieser Text ist eine direkt kopierbare Anweisung für einen eigenen ausführenden ChatGPT-Thread.** Kein weiterer Masterplan; echten Code, Tests und integrierbare PRs erstellen.

## Auftrag

Baue RepoGround als **deterministischen Struktur- und Veränderungsanalysator** massiv aus. Der Nutzer hat ausdrücklich entschieden: **erst die breite Funktionalität aufbauen, ihren Gesamtnutzen danach beurteilen**. Keine vorgezogene 20er-Benchmark- oder Nutzwert-Freigabe; das ist kein Anlass, Tests und Sicherheitsgates abzuschalten.

**Sole Writer/Integrator: Grabowski.** Großer Adler ist unabhängig read-only, Gegner frühe Same-Thread-Gegenprobe zu tragenden Prämissen/Path-Locks, Nixer bei echten NixOS-Fragen. RepoGround ist kein KI-Agent und entscheidet nicht über Codeänderungen, Tests, Reviews oder Merges.

### 0. Reale Arbeitsumgebung bindend prüfen

- Github-`main`/Branch, Checkout-Status, offene fachgleiche PRs, CI, bestehende Schreib-Leases und lokale isolierte Worktrees lesen. Keine fremde Dirty-Worktree/Lease übernehmen.
- Bestehende Systeme untersuchen, bevor neue Klassen/Indexe entstehen: `merger/repoground/architecture/{symbol_index,call_graph,import_graph,graph_index,graph_quality_eval}.py`, `core/{call_graph_navigation,call_graph_impact_index,agent_impact_context,agent_impact_refinement,delta_context}.py`, die vorhandenen Vertragsartefakte und Tests.
- Historische Beobachtung: Bei einem Snapshot waren 22.114 von 83.954 erkannten Python-Aufrufkanten aufgelöst (26,34 %). Wert **frisch validieren**; nicht als gegenwärtigen Status voraussetzen. Die bereits existierenden fünf bekannten Aufrufstellen von `resolve_canonical_md` eignen sich als Regression, nicht als einziges Erfolgsszenario.
- Genau eigenen branchisolierten Grabowski-Writer-Scope und RepoGround-Task-ID anlegen, nicht den kanonischen `main`-Checkout verändern.

### 1. Breite Strukturabdeckung (RG-XG-01)

Erweitere die *vorhandenen* Extraktions-/Indexfunktionen entlang realer Heimgewebe-Beispiele:

1. Python: bessere Auflösung von lokalen und modulübergreifenden Aufrufen, Imports, Aliasen und Symboldefinitionen. Ambiguität und dynamische Grenzen weiter sichtbar machen.
2. JavaScript/TypeScript: mindestens Import/Export, benannte Funktionen, statische Aufruf-/Referenzbeziehungen; vorhandene Parserbibliotheken nur mit aktuellem Context7-Check einsetzen.
3. Nix/NixOS, YAML/Compose, systemd/Caddy, Shell und GitHub Actions: strukturierte Konfigurations-/Service-/Artefaktbezüge, aber **keine erfundenen Laufzeitabhängigkeiten**. Nur in den nächsten Wellen vertiefen, wenn der erste Parserpfad getestet ist.
4. Markdown-/JSON-Schema- und Vertragsreferenzen als explizite Kanten; deklarierte Referenzen von aus Text geratenen Beziehungen unterscheiden.

Lieferungen: versionierte, deterministische strukturierte Kanten; gezielte Negativfixtures, Mehrdeutigkeitsbehandlung, parser-/sprachebezogene Abdeckung und direkte Quelladressen.

### 2. Gerichteter Beziehungsgraph (RG-XG-02)

- Vorhandene Call-/Import-/Symbol-Graphen nicht duplizieren, sondern Kantenarten in konsistenten, versionierten Projektionen verwenden: `defines`, `calls`, `imports`, `references`, `tests`, `declares_contract`, `configures_service`, ggf. weitere exakt begründete Typen.
- Jede Kante hat eindeutige Quell-/Zielidentität, Git-/Bundle-SHA, Relationstyp und -richtung, Quelle/Range, Belegebene (z. B. S0 vs S1), `resolved/ambiguous/unresolved`. Coverage pro Beziehungsklasse, keine implizite Vollständigkeitszusage.
- Fehlende Parser, unscharfe Namen und mehrdeutige Ziele werden explizit und kompakt berichtet. Gegenbeispiele testen, in denen gleiche Namen nicht dasselbe Symbol sind.
- Queries begrenzen; Graphdurchläufe schützen gegen Zyklen, übermäßige Fan-outs, Datenmengen und ungültige Rangereferenzen.

### 3. Echte Änderungsauswirkung (RG-XG-03)

- Vorhandene `base..head`-Delta-/Impact-Schnittstellen auf echte geänderte Symbole, eingehende/ausgehende bekannte Beziehungen, relevante Tests, Contracts und Risiken anheben. Ein Path-Diff allein ist nicht das Ziel.
- Basiskommit, Zielkommit, Hash des geprüften Diffs, Manifest-Identität und saubere Dirty-/Stale-Grenze verpflichtend. Unterschiedliche Revisionsstände dürfen nicht unbemerkt verschmolzen werden.
- Ergebnis: strukturierter **PR-Veränderungsbericht** mit Kategorien „direkt verändert“, „potenziell berührt (belegte Kante)“, „fehlend/unaufgelöst“ und „erwarteter Prüfschritt“, mit exakten Dateien/Zeilen. Kein automatisches Reviewurteil.
- Tests: echte Heimgewebe-Änderung an einer Python-Funktion, echte Änderung an einem Contract oder an Nix-/Compose-Konfiguration; mindestens ein Negativfall ohne behauptete Kante.
- Zweimal dieselbe Eingabe ergibt bytegleiches Ergebnis; tatsächliches `git show`/`git diff` validiert die Fundstellen.

### 4. Scope und Zusammenarbeit

**Primärer Besitz:** `merger/repoground/architecture/`, Graph-/Impact- und Delta-Module unter `merger/repoground/core/`, passende contracts/graph- und tests/graph-/impact-Dateien.

**Nicht in dieser Lane editieren:** `core/federation.py`, `core/history_lens.py`, `retrieval/federation_query.py`, `cli/cmd_federation.py` (Thread 2); `core/mcp_tools.py`, `cli/mcp_stdio.py`, `core/context_compiler.py`, `retrieval/task_profile_routing.py` (Thread 3). Gemeinsame Schnittstellenänderungen zuerst als kleine versionierte interne Response inkl. Beispiel und Negativfall publizieren; öffentliche MCP-Verdrahtung gehört Thread 3. Pfade nicht mit einem anderen Writer teilen.

Behalte alte Consumer und Contracts funktionsfähig, sofern ein Migrationsvertrag nicht ausdrücklich getestet ist. Keine neue Root-/Agent-/Publisher-/Graph-Doppelarchitektur, keine fremden Repoänderungen ohne eigene Autorität.

### 5. Operative Abarbeitung und Abschluss

1. Ist-Code und Teststand, maximal drei konkrete Lücken und nur erforderliche Checks bestimmen.
2. Sofort erste sinnvolle Implementierung inkl. Test im eigenen Grabowski-Worktree beginnen. Nicht bei Architekturdiagrammen stehenbleiben.
3. Erweiterungen in **kleinen, eigenständig integrierbaren PRs** liefern: zunächst Python-Graphverbesserung, dann weitere Parser/Relationen, dann Impact-Bericht und echte Cross-Surface-Fixtures.
4. Je PR: SHA-/Diff-Bindung, Regressionen, Nichtregression, kontraktkonforme Beispiele, Quell-/Range-Validität, CI und unabhängiges risikoskaliertes Review, danach reguläre Captain-Integration.
5. Nach jedem Merge vorhandene Bundles über den bestehenden Publisher aktualisieren und tatsächliche neue Graf-/Delta-Antwort read-only prüfen; kein zweiter Publisher.
6. Danach weitere Epic-Stufen autonom abarbeiten. Nur echte fremde Lease, ungeklärte Schreibautorität oder sicherheitsrelevante Defekte halten die betroffene Mutation an; andere unabhängige Arbeiten weiterführen.

**Abschlusskriterium für diesen Thread:** nicht „Plan erstellt“, sondern mehrere integrierte, getestete Code-PRs plus konkrete strukturierte Reports aus echten Commits, explizite Coverage und belegte Grenzen. Gesamt-Nutzenbenchmark kommt erst nach breitem Ausbau.

**Nächste Übergabe:** Links/SHA der integrierten PRs, Version der Ergebnisverträge, präziser Prüfbefehl, noch offene Parser-/Graphklassen und Schnittstelle für Thread 3.
