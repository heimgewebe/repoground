# RepoGround – massives Ausbauprogramm 2026/27

**Beschluss:** 27.10.2026 · **Status:** verbindliche Entwicklungspriorität, nicht Implementierungs- oder Reifequittung · **Repository:** heimgewebe/repoground

## 0. Neue verbindliche Priorität

**RepoGround wird zunächst umfassend zum deterministischen, zeit- und revisionsbewussten Veränderungs- und Wissenssystem für das Heimgewebe-Ökosystem ausgebaut. Die umfassende Bewertung seines Nutzens erfolgt nach diesem Ausbau.** Ein vorgezogener Nachweis allgemeiner Produktivitätsgewinne, ein vollständiger 20-Aufgaben-A/B-Benchmark oder eine bestimmte Mindestzahl freiwilliger Toolaufrufe sind **keine Start-, Architektur- oder Implementierungs-Gates** für die folgenden Epics.

Dieser Beschluss ersetzt die entgegenstehende Reihenfolge in der bisherigen [Vision und Agentenadoption](repoground-vision-and-agent-adoption.md), der [Master-Roadmap](repoground-master-roadmap.md) und älteren Planungsnotizen. Bereits vorhandene Funktionen sollen erweitert und verbunden, nicht neu erfunden werden. Lokale Tests, sichere Schreibrechte, Versionsbindung, CI, Freigaben und nachvollziehbare Wahrheitsgrenzen gelten unverändert. „Erst ausbauen“ heißt nicht „ungeprüft mergen oder deployen“.

**Zielbild:** RepoGround beantwortet deterministisch:
1. **Was existiert?** Dateien, Symbole, Dokumente, Verträge, Dienste, Konfigurationen und belegbare Abhängigkeiten.
2. **Wie hängt es zusammen?** Gerichtete Beziehungen innerhalb und zwischen Repositories mit Quell- und Evidenztyp.
3. **Was hat sich wann verändert?** Git- und explizite Ereignisrevisionen, langlebige Zustandsfolgen und nachprüfbare Deltas.
4. **Was könnte betroffen sein?** Änderung → direkte und indirekte *bekannte* Abhängigkeiten, Tests, Verträge und Konsumenten; Lücken bleiben sichtbar.
5. **Was wissen wir nicht?** Fehlende Parserabdeckung, unaufgelöste Referenzen, veraltete Bundles, widersprüchliche Quellen.
6. **Wie nutzen Agenten das?** Kleine, versionsgebundene Lesepakete für Grabowski, Claude und Codex; Entscheidungen, Tests, Änderungen und Merges liegen außerhalb von RepoGround.

## 1. Ehrlicher Ausgangsstand

Historischer, am 27.10.2026 verifizierter Stand: ein laufender Fleet-Publisher, zwölf gesunde Bundles im Katalog, read-only Grabowski/MCP, exakte Symbolsuche, Python-Aufrufgraphen, vorhandene Impact-/Delta-/Föderations-/History-/Watcher-Funktionen. Eine echte Codex-Aufgabe verwendete freiwillig RepoGround-MCP; ein streng isolierter A/B-Vergleich fand mit und ohne RepoGround alle fünf bekannten Aufrufstellen korrekt. Der beobachtete statische Python-Graph hatte rund 26,34 % eindeutig aufgelöste Aufrufkanten. Diese Daten sind **Momentaufnahmen**, keine künftigen Betriebszusagen. Größerer Gesamtnutzen ist **nicht bereits bewiesen** und muss den Ausbau nicht mehr blockieren.

Aktuelle Wahrheitsquellen sind weiterhin Git-Bäume, CI, Laufzeitdienste, Metarepo-Fleet-Quellen und die jeweils zuständigen Systeme. Die RepoGround-Publikation ist ein deterministischer, abgeleiteter Navigations-/Analysezustand, keine neue Source of Truth.

## 2. Zielarchitektur ohne zweite Systemwelt

```text
Autoritative Quellen: Git / Fleet-Contracts / konfigurierte Services /
 explizite CI-, PR-, Chronik- und Laufzeit-Belege
           │
           ▼
bestehender Publisher / Parser / strukturierte Artefakte
           │  versioniert, hash-gebunden, inkrementell
           ▼
RepoGround-Kern
 ├─ Strukturgraph (Symbole, Imports, Calls, Configs, Verträge)
 ├─ Veränderungsgraph (base..head; geänderte/berührte Beziehungen)
 ├─ Zeitachse (Revisionen, Ereignisse, belegte Vorgeschichte)
 ├─ Föderation (gerichtete repoübergreifende Beziehungen)
 └─ Unsicherheits- und Provenienzmodell (S0/S1, Lücken, Coverage)
           │
           ▼
bestehende CLI/MCP/Grabowski-Read-Frontdoors: begrenztes Evidence Pack
           │
           ▼
Grabowski / Claude / Codex: interpretieren und entscheiden selbst
           │
           ▼
Git-/CI-/Test-/Runtime-Rückprüfung durch zuständige Primärsysteme
```

Die bestehenden Indexe, Komponenten, Bundle-Manifestrollen, Range-Refs, Publisher, Watcher und Frontdoors haben Vorrang. Neue Verträge/Artefakte nur bei belegter Lücke; keine generische Ereignisdatenbank, kein zweiter Rootbroker, kein Agent in RepoGround, keine versteckten LLM- oder Deployment-Aktionen.

### Harte Datenregeln

- Jeder Datensatz trägt, wo anwendbar: `repo_id`, `source_revision`, `artifact_digest`, `origin_path`/Range, Beziehungstyp und -richtung, Erhebungs-/Ereigniszeit sowie Status `confirmed`/`derived`/`unresolved`. Ein Zustand ohne auflösbare Herkunft wird nicht als Beleg ausgegeben.
- Gegenwärtig, historisch und beobachtet sind getrennte Dimensionen. „A importiert B“ ist kein Nachweis einer produktiven Abhängigkeit; „liegt in derselben Fleet“ ist kein Aufrufbeleg.
- Die Graphabdeckung wird pro Sprache/Beziehungsart quantifiziert. Unaufgelöste und widersprüchliche Kanten bleiben explizit; niemals Vollständigkeit behaupten.
- Dateiinhalte und aktuelle Runtimezustände werden an ihren Primärquellen überprüft. `canonical_md` bleibt die autoritative Bundle-Inhaltsquelle, Indexe bleiben abgeleitet.
- Read-only CLI/MCP löst keine Git-/Index-/Publisher-Schreibvorgänge aus. Keine Geheimnisse in Exporten, Token-Spuren oder öffentlichen Reports.
- Wiederholte Analyse bei identischen Eingaben liefert identische strukturierte Ergebnisse. Hard Budgets, Idempotenz, atomare Generationen, partielle Degradierung und sichere Fallbacks bleiben erhalten.

## 3. Ausbau-Epics mit funktionsfähigen Ergebnissen

| Epic | Inhalt | Mindestprodukt / Abnahme | Federführung |
| --- | --- | --- | --- |
| **RG-XG-01** | Breite Sprache-/Artefaktabdeckung ausbauen: Python vertiefen; TS/JS, Nix, Shell, YAML/Compose, GitHub Actions, systemd/Caddy und Markdown-/Schema-Verträge gezielt erschließen | Wiederholbare Extraktion an realen Heimgewebe-Fixtures; unsupported offen benennen | Thread 1 |
| **RG-XG-02** | Typisierter Strukturgraph mit Aufrufern, Imports, Referenzen, Service-/Config-/Contract-Kanten, Provenienz, Ambiguitäten und Coverage | Gerichtete, quellgebundene Kanten; negative und mehrdeutige Fälle; vorhandenen Graphindex nutzen | Thread 1 |
| **RG-XG-03** | Revisionsgebundener Veränderungsgraph mit `base..head`, betroffenen Symbolen, direkten/indirekten *bekannten* Folgen, Vertragstests und Änderungsrisikohinweisen | Deterministischer PR-Impact-Bericht für mehrere echte Codeänderungen, inkl. fehlender Daten | Thread 1 |
| **RG-XH-01** | Revisionen und Ereignisse als nachvollziehbare technische Zeitgeschichte, Deltas über mehrere Generationen | Zwei+ historische Commits und eine reproduzierte Folge, keine erfundene Kausalität | Thread 2 |
| **RG-XF-01** | Föderation über Metarepo-Fleet, echte Imports/API-/Konfigurationsverträge, Release- und Deploymentbezüge | Mindestens eine reale Abhängigkeit über zwei Repositories mit zwei SHA-Bindungen | Thread 2 |
| **RG-XF-02** | Lesbare externe Provenienz (GitHub-PR/CI, Chronik, Operatorquittungen), Konflikt-/Stale-Diagnose und zeitliche Abgleichregeln | Herkunft und Datum jedes externen Belegs, resilienter Ausfallmodus | Thread 2 |
| **RG-XC-01** | Agenten-Frontdoor mit Taskprofilen für Review, Debugging, Testfindung, Contract-/Cross-Repo-Impact und Geschichte | CLI/MCP liefern kurze, exakt referenzierbare Evidence Packs mit Fallback | Thread 3 |
| **RG-XC-02** | Events und bestehende Publisher-/Watcher-Pfade zu idempotenten, begrenzten Kontext-Updates verbinden | Ein echtes Git-/CI-Ereignis → genau ein nachlesbarer Bericht, ohne Agentaktion | Thread 3 |
| **RG-XC-03** | Grabowski-/Claude-/Codex-Consumption, PR-Kontext und verständliche Berichte sowie Telemetrie | Echte agentische Nutzung auf anspruchsvollen Fällen; Gesamtbewertung *nach* Ausbau | Thread 3 |

### Zielübergreifende Nutzerfälle

1. PR ändert eine Python-Funktion: RepoGround zeigt Änderung, zwei belegte Aufrufer, betroffene Tests, nicht auflösbare Call-Kanten und exakte Commit-/Zeilenbezüge.
2. Eine NixOS-/Compose-/Caddy-Konfiguration ändert eine Serviceadresse: bekannte Konfigurationsbezüge, betroffene Repositories/Tests und explizite Nichtabdeckung werden dargestellt.
3. Ein Contract wird umbenannt: Producer, belegte Consumer und veraltete Bezüge über Repositorygrenzen werden sichtbar; bloße Ähnlichkeit wird nicht als Beziehung ausgegeben.
4. Ein Fehler wiederholt sich: Commit-/PR-Vorgeschichte und frühere verifizierte Tests sind auffindbar; zeitliche Nähe ist keine kausale Bestätigung.
5. Ein neuer Commit trifft ein: vorhandene inkrementelle Erfassung erstellt ein dedupliziertes Änderungs-Evidence-Pack; keine automatische Merge-/Releaseentscheidung.

## 4. Lieferwellen – Ausbau statt Vorab-Nutzen-Gate

**Welle 0 – sofort:** echte Modul-/Contract-Inventur, drei branchisolierte Writer-Lanes und minimale gemeinsame Ergebnisfelder (Repo/Revision/Diff, Provenienz, Status, Coverage, Range, Schema-Version). Keine Architektur-Neuerfindung. Jede Lane startet mit Code und Tests, nicht mit einem weiteren Metaplan.

**Welle 1 – parallel:** Thread 1 erweitert Struktur-/Impact-Kern; Thread 2 entwickelt Zeitgeschichte und echte Föderationskanten; Thread 3 baut bereits anhand existierender Bundles/Interfaces den Agenten-Kontext und Berichtsweg aus. Arbeitsflächen strikt disjunkt.

**Welle 2 – Integration:** Nach Veröffentlichung der ersten stabilen typisierten Artefakte integriert Thread 3 die Graph-/Zeit-/Föderations-Responses; Thread 1 und 2 ergänzen reale Quellfälle. Gemeinsame API-/Schemaänderungen über kleine, explizit abgestimmte Folge-PRs und Main-Rebase.

**Welle 3 – breite Erprobung:** über mehrere Heimgewebe-Repositories und echte PRs; Parserabdeckung, Änderungsfolgen, Historie, Cross-Repo, CLI/MCP und Event-Handoff end-to-end belegen. Produktive Freigabe nur nach regulären Sicherheits-/CI-/Review-Gates.

**Welle 4 – Wirkung beurteilen:** erst nach breitem Funktionsausbau 20+ echte Aufgaben mit/ohne optionales RepoGround, Kosten inkl. Publisher, Qualität, Recall und Fehlerraten pro Aufgabenklasse messen. Ergebnisse entscheiden über späteres Optimieren/Zurückbauen, **nicht** rückwirkend über die Startberechtigung dieses Ausbauprogramms.

## 5. Genau drei unabhängige Ausführungs-Threads

- **[Thread 1 – Struktur- und Veränderungskern](repoground-expansion-thread-1-graph.md)**: Graph, Parser, Change-Impact und Tests.
- **[Thread 2 – Föderation und Zeitgeschichte](repoground-expansion-thread-2-federation-time.md)**: repoübergreifende Bindung, historische Deltas und externe Lesebelege.
- **[Thread 3 – Agentenprodukt und Ereignisfluss](repoground-expansion-thread-3-consumers.md)**: CLI/MCP, PR-Evidence-Packs, Grabowski-/Claude-/Codex-Konsum.

Drei **ChatGPT-Ausführungsthreads**, nicht drei unabhängig schreibende Agenten: **Grabowski ist der alleinige autorisierte Writer und Integrator**. Pro Thread eigener Git-Branch, eigener isolierter Worktree, eigene schmale Path-Leases, eigener Scope/Task/PR. **Großer Adler** unabhängig read-only, **Gegner** frühe Same-Thread-Gegenprobe bei wesentlichen Prämissen, **Nixer** nur bei NixOS-/Nix-Details. Kein paralleles Editieren gleicher Pfade; fremde Leases, laufende Writer, Worktrees und Recovery-Zustände nicht anfassen.

Gemeinsame Integrationsregel: Thread 1/2 dürfen unabhängig strukturierte interne Daten liefern; Thread 3 allein besitzt die gemeinsamen öffentlichen CLI/MCP-Antworten. Beim ersten Vertragsschritt ein kompakter Beispiel-Response samt Negativfall, kein abstrakter Großcontract ohne ausführbare Implementierung. Vor externen Bibliotheken/APIs aktuelle Context7-Dokumentation mit echter Repoimplementierung abgleichen.

## 6. Abnahme und Nachweis ohne Nutzen-Vorabkontrolle

Jedes Epic liefert reale Codeänderungen, gezielte Tests, Diff und Ausgangs-/Ziel-SHA, Primärquellen-Readback, eine reproduzierbare Eingabe/Ausgabe und eine klare Grenze: was bewiesen, abgeleitet, unbekannt ist. Nach Möglichkeit jeweils einen echten Heimgewebe-Fall und einen Negativfall. Regressionen oder unklare Zugriffsrechte blockieren **den betreffenden Merge**, aber kein unabhängiges anderes Epic.

Keine Benchmarks, Demos oder Snapshot-Zahlen als Ersatz für funktionierende Features. Ein funktionierendes Teilergebnis darf in einem eigenen PR integriert werden, auch wenn das Gesamtprogramm noch nicht fertig ist. Änderungen an fremden Repositories/Hostdiensten nur durch getrennte, autorisierte Grabowski-Arbeiten mit eigenen Gates.

**Wahrheitsstatus:** Dieses Dokument ist die strategische Prioritätsentscheidung und der Backlog, nicht die kanonische Task-/CI-/Produktionsstatusquelle. Autoritativ bleiben `docs/tasks/index.json`, die zuständigen Grabowski-/Bureau-Belege, GitHub, Tests und Live-Readbacks.
