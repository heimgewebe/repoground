# RepoGround: Merge-to-Snapshot-Konvergenz

**Belegstand:** 31. Oktober 2026 · **Priorität:** P1 (Betriebsnutzwert vor weiterem Retrieval-/Graph-Ausbau)
**Status:** **automatische GitHub-HEAD-Konvergenz implementiert und produktiv Ende-zu-Ende nachgewiesen**; die differenzierte Laufzeitmessung größerer Publikationen ist integriert, ihr erster produktiver `phase_seconds`-Beleg steht noch aus.
**Verantwortung:** Grabowski ist alleiniger Writer/Operator. Änderungen an RepoGround, Grabowski und ggf. Heim-PC erhalten jeweils einen klar begrenzten, autorisierten Scope. Keine parallelen Writer für überlappende Pfade.

## Produktiver Ist-Stand und Grenzen (31. Oktober 2026)

Dieser Abschnitt aktualisiert den historischen Entwurf darunter. Die Abschnitte 1–6 enthalten die **Ausgangslage und ursprünglichen Akzeptanzziele vom 30.10.**, keine aktuelle Behauptung fehlender Implementierung.

- **Integriert:** PR [#1373](https://github.com/heimgewebe/repoground/pull/1373) beseitigt redundante Berechnung identischer CI-Evidenz. PR [#1374](https://github.com/heimgewebe/repoground/pull/1374) ergänzt einen günstigen, level-triggered GitHub-HEAD-Abgleich und aktiviert den vorhandenen Publisher selektiv, ohne einen zweiten Generator. Die bereits stündliche vollständige Ereignis-/Retention-Wartung bleibt erhalten.
- **Produktivnachweis:** heim-pc hat neue GitHub-`main`-Commits automatisch als geändert erkannt, veröffentlichte revisionsgebundene Bundles und lieferte anschließend via Grabowskis echtem `repoground_preflight`, `repoground_query` und `repoground_range_get` `fresh_exact`, Dateien, Zeilen und auflösbare Zitate. Einzelbelege und SHA-Bindungen stehen in den Produktivkommentaren von [PR #1374](https://github.com/heimgewebe/repoground/pull/1374).
- **Nachmessung:** 169 abgeschlossene HEAD-Watch-Läufe: Median **22,04 s**, P95 **23,43 s** Wall-Clock; fünf längere Läufe. Diese Verteilung ist **kein** Merge→Agenten-P95. Am neuen Generator-Release `1621e8864883f37980057e7b060f80bb18ceb67c` meldete der automatische Timer am 31.10. um 07:36 CET **13/13 unverändert, 0 Neubauten, 22,545 s Wall, 2,388 s CPU** und `SUCCESS`. Ein anschließender Agentenreadback lieferte `fresh_exact` für denselben `main`-Commit mit auflösbarem Quellenbereich.
- **Neue Messbarkeit:** [PR #1375](https://github.com/heimgewebe/repoground/pull/1375), regulär durch Captain gemergt, fügt fünf additive `phase_seconds`-Felder in das bestehende `published`-Receipt ein: `refresh`, `publication_state`, `authenticated_events`, `source_worktree_prune`, `retention_prune`. Das immutable Release `1621e886…` wurde Git- und archivgebunden geprüft und atomar aktiviert; der vorherige funktionierende Generator `1e8b817a…` bleibt als Rückfall erhalten.
- **Noch nicht belegt:** statistischer P95 für Merge→Agentennutzbarkeit, genaue Verteilung der bis zu etwa sechsminütigen größeren Publisherläufe auf die fünf neuen Phasen, Reboot-/Abbruchabdeckung aller denkbaren Fälle und ein gepaarter vollständiger LLM-Agentenbenchmark. Diese Lücken rechtfertigen weder die Behauptung, die HEAD-Konvergenz fehle, noch ungezielte zusätzliche Scheduler.

**Ziel:** Nach einer erfolgreichen Änderung des Default-Branches (derzeit `main`) erscheint ohne manuelles Eingreifen ein gesunder, revisionsgebundener RepoGround-Snapshot. Ein Agent findet danach aktuelle, prüfbare Quellenbelege; während des Aufbaus kann er mit klar gekennzeichneter Git-Live-Recherche weiterarbeiten.

> **Erfolg bedeutet nicht „Trigger ausgelöst“ oder „Publisher grün“**, sondern: beobachteter GitHub-HEAD → exakt dazu erzeugter, validierter und atomar aktivierter Snapshot → frische Agentenabfrage mit Quellenbelegen.

## 1. Verifizierte Ausgangslage und Problemgrenze

Am 30.10.2026 wurde auf `heim-pc` festgestellt:

- `ops/systemd/repoground-fleet/repoground-publish-fleet-watch.timer`: `OnCalendar=hourly`, `RandomizedDelaySec=10min`; Dienst: `repoground-publish-fleet --if-changed --retention 3 --limit 8`.
- Der Fleet-Publisher in `scripts/ops/repoground-publish-fleet` besitzt `--repo`, Fingerprint-Vergleich für Quellen-/Generator-/Konfigurationsidentität, GitHub-Remote-HEAD-Ermittlung, Worktree-Schutz, `flock`, revisionsgebundene Artefakte, Validierung und Retention.
- Der Fleet-Lauf **18:04:58–18:18:42 CET** dauerte 13:44 Minuten bei rund 13:22 Minuten CPU und ca. 821 MiB Peak-RAM; **0 Veröffentlichungen, 12 unveränderte Repositories**. Die wesentliche No-op-Kostenursache ist noch zu *messen*, nicht aus Log-Wiederholungen zu erraten.
- Grabowski hat in `src/grabowski_repoground_post_merge.py` bereits einen gezielten Post-Merge-Weg (`--repo ... --if-changed --retention 3`), Busy-Retries und revisionsgebundenen Freshness-Readback. Die vorhandene authentifizierte GitHub-Event-Verarbeitung im Publisher ist hingegen ein **nachgelagerter Event-/Evidence-Handoff**, kein bereits bewiesener eingehender Push-Trigger.
- Reale Agentenabfragen lieferten zitierfähige Dateien/Zeilen; einige wurden während neuer Merges mit `stale_context_refused` abgelehnt. Dieses Fail-Closed-Verhalten verhindert falsche Aktualitätsbehauptungen, darf aber keinen unnötigen Arbeitsstillstand verursachen.
- Historische PR-/Fehlerzustände (z. B. Partial Clones, große SQLite-Artefakte, absichtlich syntaktisch ungültige Parser-Fixtures) sind **keine** aktuellen Blocker ohne frischen Reproduktionsbeleg. Bestehende PR-Lanes werden nicht übernommen.

**Zum ursprünglichen Planzeitpunkt unbekannt:** Zeitanteil der einzelnen No-op-Phasen, Post-Merge-Abdeckungsgrad außerhalb von Grabowski, Triggerverlust über längere Lastphasen und veröffentlichte P95-Latenzen. Für den später verifizierten Stand gelten die Belege und offenen Grenzen im vorangestellten Produktivabschnitt.

## 2. Minimale Architektur und Wahrheiten

```text
GitHub default branch (Soll-SHA)
     |                                 (kein zweiter Publisher)
     +-- Grabowski/Captain: Merge-Receipt --+
     |                                      |
     +-- günstiger Remote-HEAD-Abgleich ----+--> vorhandener Fleet-Publisher
                                                      |  ein Writer / flock
                                                      |  --if-changed, --repo
                                                      v
                                              Build für neuesten SHA
                                                      |
                                              bestehende Validierung
                                                      |
                                            atomare Veröffentlichung
                                                      |
                                 Agent: fresh_exact + Quellenbereiche
                                          oder explizite Git-Live-Suche
```

1. **Soll-Wahrheit:** maßgeblicher GitHub-Default-Branch-Commit je Repository und gültige Fleet-Mitgliedschaft aus `metarepo/fleet/repos.yml`. Ein Push-Event ist nur ein Wecksignal. Keine zweite persistente Queue als Quelle der Wahrheit.
2. **Ist-Wahrheit:** letzter erfolgreich validierter und im kanonischen Katalog veröffentlichter Snapshot mit `repo_id`, Ref, Commit, Generator-/Konfigurationsfingerprint und Integritätsbelegen. Ein vorhandenes Verzeichnis oder ein erfolgreicher Prozess-Exit allein genügt nicht.
3. **Ein Writer:** Alle Refresh-Wege verwenden den **bestehenden** Publisher samt Lock/Worktree-/Publikationskontrakt. Der leichte Abgleich löst nur diesen Weg aus; keine parallel implementierten Generatoren und kein öffentlicher Webhookdienst.
4. **Konvergenz statt Event-für-Event-Builds:** Mehrere Updates desselben Branches werden auf den **neuesten beobachteten SHA** zusammengefasst. Deduplizierung erfolgt nur bei **identischer vollständiger Publikationsidentität** (Quell-Commit, Generator-/Konfigurationsfingerprint und relevante Ausgabe-Contracts), nicht bloß bei gleichem Quell-SHA. Fehlgeschlagene oder beschädigte Veröffentlichungen dürfen erneut gebaut werden. Ein älterer Build bleibt ggf. gültiges Historienartefakt, darf aber nicht `fresh_exact` für einen neueren HEAD behaupten.
5. **Generator-Änderung:** Ändert RepoGround selbst Generator oder relevante Bundle-Contracts, wird über die vorhandene Fingerprint-Logik der betroffene Fleet-Satz nachgezogen. Nicht bei gewöhnlichem Repo-Commit sämtliche Bundles neu bauen.

## 3. Ausführung in vier begrenzten Paketen

### RG-FRESH-01 – No-op von schwerer Wartung entkoppeln (P0 innerhalb des Plans)

**Messung:** Ein unveränderter und ein veränderter Lauf mit getrennten Wall-/CPU-/Speicherwerten für Remote-HEAD, Generator-/Config-Fingerprint, `ensure_tool_worktree`, `_unchanged_authenticated_event_with_prune`, Event-Handoff, Worktree-Prüfung, Pruning, Generierung und Validierung. Vorher/nachher dieselben Repositories und identischen SHAs verwenden.

**Kleinster Eingriff:** Remote-Ziel und Fingerprint zuerst günstig prüfen. Bei belegtem unverändertem, gesunden Publikationsstand keine teure Quelle-/Parser-/Graph-/Worktree-Behandlung auslösen. Event-Zustellung, historische Pins, Leases, Retention und Recovery dürfen dadurch nicht verschwinden: erforderliche Wartung im vorhandenen Publisher *separat budgetieren*, z. B. nur bei fälliger Wartung oder tatsächlichem Event. Keine neue Dauerschleife.

**Negativfälle:** defekter/fehlender Manifestpfad, veränderter Generator, veränderte Config, unbekannter Remote-HEAD, unvollständige Publikationsidentität und ausstehender Event-Receipt dürfen **nicht** fälschlich als No-op gelten. Ein absichtlich invalides Python-Testfixture ohne gesundheitliche Auswirkung ist kein Refresh-Abbruch.

**Abnahme:** unveränderte Fleet ohne Rebuild, alle 12+ erwarteten Repositories korrekt klassifiziert; Zielwert **≤ 10 s CPU** und **≤ 30 s Wall** bei normalem Netzwerk für die komplette unveränderte Fleet (Messziel, nicht behaupteter Istzustand); Event-/Retention-/Pin-Regressionsprüfungen erfolgreich.

### RG-FRESH-02 – Merge-Trigger und leichte Fleet-Reconciliation (P1)

**Interne Merges:** Im bestehenden Grabowski/Captain-Post-Merge-Pfad erst nach bestätigtem Merge-Commit eine gezielte Publisher-Anforderung für `owner/repo` auslösen; die tatsächliche Revision vor Publikation erneut gegen GitHub prüfen. Keine Kopplung von Merge-Erfolg an den vollständigen, eventuell langen Rebuild.

**Externe Merges/direkte Pushes:** Zunächst **kein neuer Webhookserver**. Der vorhandene systemd-Watch ruft nach behobenem No-op-Pfad alle **zwei Minuten** einen günstigen, unveränderungsbewussten Remote-/Fingerprint-Abgleich auf (`RandomizedDelaySec=0`; laufzeitgebundene systemd-Nachläufe so wählen, dass lange Jobs spätere Checks nicht dauerhaft verdrängen). Wenn ein bestehender bereits vertrauenswürdig angebundener GitHub-Push-Eingang nachgewiesen ist, nur dessen Wecksignal wiederverwenden.

**Gezielt:** Gewöhnlich `--repo heimgewebe/<repo> --if-changed`. Für nicht durch Event erwischte Änderungen wählt der Fleet-Watch nur veränderte Fingerprints. `--limit 8` ist ein *Arbeitsbudget*, keine Aussage, dass die übrigen fertig sind.

**Abnahme:** ein durch Grabowski bestätigter Merge, ein über GitHub außerhalb Grabowski gemergter PR und ein direkter Push auf den Default-Branch führen ohne Handarbeit zu einem passenden Snapshot. Unveränderte Fleet löst keinen teuren Build aus.

### RG-FRESH-03 – Busy, Rennen und Nachholung ohne Verlust (P1)

Die bestehende Einzel-Publisher-Sperre bleibt bestehen. Bei `busy` gilt **nicht** „verarbeitet“: Der Remote-Branch bleibt im nächsten Abgleich Sollzustand. Das Ende eines langen Publishers stößt, soweit für niedrige Latenz nötig, einen kurzen Nachlauf an; auch nach Prozessabbruch oder Host-Neustart erkennt der nächste Watch die Differenz automatisch. Keine ungesicherte RAM-only-Queue und kein paralleler Writer.

**Priorisierung:** erst geänderter RepoGround-Generator (bei entsprechendem Fingerprint), dann gezielt angeforderte **tatsächlich stale** Repositories, danach älteste *tatsächliche* Publikationsschuld. Alter eines bereits frischen Bundles allein ist kein Neubaugrund. Eine dauernd geänderte Quelle darf ältere wartende Repositories nicht unendlich verhungern lassen. Begrenztes Zeit-/Arbeitsbudget und nachvollziehbare Verschiebung statt sofortigem Voll-Rebuild.

**Revisionsgrenzen:** Der Publisher baut einen expliziten beobachteten Ziel-SHA, validiert das Ergebnis und prüft vor Erfolgsmeldung den dann aktuellen Remote-HEAD. Ist dieser weitergezogen, bleibt ein neuer Refresh nötig. Ereignis `A` ist durch `B` nur erledigt, wenn `A` als Vorfahr von `B` belegt ist, `B` erfolgreich veröffentlicht wurde und die aktuelle Remote-Freshness gesondert bewertet wird. Bei Force-Push oder nicht nachweisbarer Abstammung keinesfalls stillschweigend quittieren.

**Abnahme:** zwei schnelle Merges, Merge während langem Build, Busy-Retry, Jobabbruch, Reboot, Remote-HEAD-Wechsel und Generator-Upgrade; jeweils entweder `fresh_exact` des aktuellen HEAD oder ein sichtbarer, automatisch erneut versuchter Pending-/Fehlerzustand.

### RG-FRESH-04 – Agenten-Lesepfad und Produktivabnahme (P1)

Die bereits in `AGENTS.md` dokumentierte Regel „bei stale/unavailable normales Git/Dateilesen“ ist **zuerst in der tatsächlich aktiven Grabowski-Consumerstrecke nachzuweisen**, bevor neue Fallback-Software entsteht. Nur falls dieser Weg dort real blockiert, eine minimale Revision-pinnierte Git-Live-Suche ergänzen.

Der Agent erhält alternativ zu `fresh_exact`: `source=live_git`, abgefragter Commit-SHA, Dateien/Zeilen, ausdrückliche Einschränkung von Graph-/Impact-Vollständigkeit. Kein stilles Mischen alter Graph-Belege mit aktuellem Code, keine neuen obligatorischen Freigaben.

**E2E-Abnahme auf heim-pc:** echten `main`-Commit erzeugen bzw. einen vorhandenen neu gemergten PR beobachten → Trigger/Head lesen → targeted Publisher → Bundle-Manifest und Health prüfen → `repoground_preflight`/`repoground_query` aus einem echten Grabowski-Consumer → konkrete Quellenzeilen und Commit-Bindung nachlesen. Danach einmal mit stale Zustand prüfen, dass normale Live-Recherche funktioniert. Ein grüner Timer, Commit in `main` oder erfolgreiche Build-CI genügt nicht.

## 4. Messmodell und Entscheidungsschwellen

Zeitpunkte unabhängig erfassen: `t_merge` (authentischer GitHub-Merge-/Push-Zeitpunkt, soweit verfügbar), `t_observed` (erster HEAD-Abgleich), `t_started` (Buildstart), `t_published` (atomare Aktivierung nach Validierung), `t_usable` (erfolgreiche Agentenabfrage). Ausgeben: Erkennungs-, Warte-, Build-, Publikations- und Nutzbarkeitszeit, keine verschmolzene „Latenz“.

| Messung | Angestrebte Abnahme |
| --- | --- |
| No-op gesamt | ≤ 10 s CPU, ≤ 30 s Wall unter normalem Netzwerk |
| Externer Commit → erkannt | P95 ≤ 2 Minuten bei gesundem GitHub-Zugriff |
| Grabowski-Merge → erkannt | unmittelbar nach bestätigtem Receipt, ohne Fleet-Timer-Wartezeit |
| Erkannt → nutzbar | tatsächliche Build-/Validierungszeit + möglichst ≤ 60 s Koordinations-Overhead |
| Busy / Absturz / Neustart | nie als erledigt quittiert; ohne manuelle Reparatur nachgeholt |
| Agent bei stale | laufende Aufgabe kann belegbar auf Git-Live-Recherche ausweichen |
| Unnötige Builds | 0 Neubauten bei unveränderter, gesunder **vollständiger Publikationsidentität**; erforderliche Wiederholungen bei Fehlern oder verändertem Generator/Config sind zulässig |

P95-Werte erst nach mehreren repräsentativen realen Merges ausweisen; einzelne Smoke-Tests beweisen die Funktionskette, nicht das Perzentil. Fehlende Beobachtungen und externe GitHub-Ausfälle separat zählen. Bei tatsächlich hohen Buildzeiten vorerst **nicht** mehr Scheduling-Schichten einführen: erst messen, ob inkrementelle Indexierung wirtschaftlich wäre.

## 5. Zuständigkeiten, Scope und Integrationsfolge

1. **RepoGround (zuerst):** No-op-Kostenmessung und Fast-Path, Reconciliation-/Priorisierungsregeln, minimale systemd-Änderung, Tests in `merger/repoground/tests/test_fleet_runtime.py`. Vor Veränderung die aktuellen Unit- und Live-Publisher-Versionen prüfen; die installierte Runtime kann hinter `main` liegen.
2. **Grabowski (anschließend, eigener PR):** vorhandenen Post-Merge-Receipt-/Busy-Weg auf tatsächliche Zustellung und E2E-Readback prüfen; Consumer-Fallback nur bei belegter Lücke ändern. Kein zweiter Scheduler oder ausführender Publisher in Grabowski.
3. **Heim-PC (nur bei Bedarf, eigener Scope):** bestehende Runtime-Installations-/systemd-Aktivierung anpassen. Keine NixOS-Konfigurationsänderung ohne nachgewiesene Notwendigkeit.
4. **Produktivabnahme:** RepoGround-Generatorstand, aktive systemd-Units, Fleet-Publikations-HEAD, Grabowski-Release und echter Client-/MCP-Readback frisch gegeneinander prüfen. Fremde offene PRs/Writer-Lanes nicht überschreiben.

**Rollout:** zunächst manueller isolierter No-op-/geänderter-Lauf und Regressionen, dann einen Canary-Repository-Merge inklusive Busy-/Restart-Gegenprobe, danach den kurzen Watch aktivieren und weitere Fleet-Repositories kontrollieren. **Rollback:** auf vorige Unit-/Runtime-Revision zurück, alte gesunde Bundles über bestehende Retention erhalten und den Fleet-Watch wieder stündlich betreiben; veraltete Indizes weiter korrekt als stale markieren. Keine GC-/Integritätsgrenzen abschalten.

## 6. Nicht-Ziele und Abschlussdefinition

Nicht Bestandteil: neue zentrale Ereignis-Datenbank, externer Webhookdienst, Voll-Fleet-Rebuild nach jedem Commit, neuer Agentenrouter, allgemeine Graph-Auflösungsverbesserung, Retrieval-Ranking oder automatische Merge-Freigaben.

**Definition of Done:** Zwei unterschiedliche reale Merge-Wege, Mehrfach-Merge unter laufendem Publisher und Wiederanlauf nach Fehler sind mit exakt gebundenem GitHub-SHA, erfolgreicher Bundle-Validierung und **echter Agentenabfrage** belegt; No-op-Kosten sind gegenüber dem 13:44-Minuten-Referenzlauf deutlich gesunken. Ergebnisquittungen enthalten die fünf Zeitpunkte, Commitidentitäten, Test- und Runtime-Versionen. Bleibende Lücken sind sichtbar, nicht durch `status=ok` verdeckt.

**Abgrenzung:** Dieses Dokument ist Ausführungsplanung und kein zweites Task-Register. Kanonische Aufgabenstände verbleiben bei `docs/tasks/index.json`, PR-/CI-/Runtime-Belegen und den jeweiligen Grabowski-Lanes. Der strategische Ausbau vom 27.10.2026 wird nicht durch eine neue globale Benchmark-Sperre blockiert; diese Betriebsreparatur hat für die tatsächlich nutzbare Agentenstrecke operativen Vorrang.