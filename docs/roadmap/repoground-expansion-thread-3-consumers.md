# AUSFÜHRUNGSAUFTRAG 3/3 – Agentenprodukt und Ereignisfluss

**Priorität:** P0 Ausbau · **Projekt:** [RepoGround](https://github.com/heimgewebe/repoground) · **Programm:** [massiver Ausbau](repoground-massive-expansion-program.md) · **Stand:** 27.10.2026

**Direkt kopierbare Anweisung für einen eigenen ausführenden ChatGPT-Thread.** Der Nutzer beauftragt ausdrücklich einen umfassenden RepoGround-Funktionsausbau **vor** einer umfassenden Nutzwertbewertung. Kein weiterer Planungs- oder Benchmark-Loop als Bedingung für Implementierungsarbeiten.

**Sole Writer/Integrator:** Grabowski; eigene exakt gescopte Leases, Branch, Worktree, Task-ID und PRs. Großer Adler unabhängiger read-only Observer, Gegner frühe Same-Thread-Prämissen-Gegenprobe, Nixer nur für Nix-/NixOS-Fragen.

## 0. Bestehende produktive Wege erhalten

- Vor Mutationen GitHub-`main`, CI, PRs, Eigentümer/Leases, aktive systemd-Dienste, Bundles und echte MCP-Verbindungen frisch prüfen.
- Vorhanden und nach Möglichkeit direkt verwenden: `scripts/repoground-mcp-stdio.py`, `merger/repoground/cli/mcp_stdio.py`, `merger/repoground/core/mcp_tools.py`, `core/context_compiler.py`, `core/agent_reading_pack.py`, `retrieval/task_profile_routing.py`, `retrieval/incremental_snapshot.py`, Grabowskis read-only RepoGround-Frontdoor und die installierte Fleet-Publisher-Unit.
- Frühere Belege: RepoGround war via Codex nutzbar, manchmal ungenutzt; bei echter Change-Impact-Aufgabe verwendete Codex freiwillig `bundle_discover`, `find_references` und `live_freshness`. Codex hat zusätzlich einen **separaten App-Tool-Zugang**; für spätere kontrollierte Vergleiche Apps und lokale MCP-Quellen sauber getrennt halten.
- Das neue Programm erlaubt Implementierung **ohne** die 20 geplanten A/B-Aufgaben zuvor abzuschließen. Lokale Funktionstests, Sicherheits-/CI-/PR-Integrationsgates gelten weiter.

## 1. Das nutzbare Agentenprodukt (RG-XC-01)

Baue ein verständliches, kleines **Change Intelligence Evidence Pack** aus vorhandenen Daten und bestehenden CLI/MCP-Responsefamilien:

- Aufgabe und Quellbindung: `repo`, optional `base..head`, `diff_sha256`, Bundle/Manifest, Freshness, Worktree-Grenze, Budget.
- Funktionen: `explain-change`, `find-related-tests`, `contract-impact`, `cross-repo-impact`, `what-changed-since`, `source-and-proof`. Diese sind zunächst **Anwendungsfälle**, keine Verpflichtung, sechs neue öffentliche Werkzeuge zu schaffen. Bestehende `query`-, `find_symbol`-, `get_callers`-, `context_compose`- und Federation/History-Befehle bevorzugen.
- Ausgabe: direkt geänderte Stellen, bekannte Beziehungen, begründete Prüfstellen, Quellranges, Coverage/Unsicherheit, veraltete oder fehlende Daten, klare Begrenzung von Aussagen. Menschenlesbares Markdown + validierbares JSON aus demselben deterministischen Kern.
- Native Fallbacks unverändert: Git/`rg`/Tests/CI bleiben nutzbar. Kein blindes Tool-Calling als Pflicht, keine künstliche Agentenblockade bei `no_bundle_available`, kein automatisches LLM-Urteil.
- Eigene Fixtures/Tests belegen kleine Antwort, stabile Reihenfolge, gesicherte Ranges, erlaubte Pfade, keine Geheimnisse, keine implizite Snapshot-Schreiboperation.

## 2. Breite Integrationen statt RepoGround-Selbstgespräch (RG-XC-03)

- In Grabowskis üblichen Aufgabenprofilen (PR-Review, Bug/Regression, Testauswahl, Change-Impact, Contract-/Service-Folgen) RepoGround bei echten passenden Aufgaben erreichbar, auffindbar und mit korrekter Identität machen; Tool-Discoverability an konkreten Fällen verbessern.
- Claude Code und Codex mit ihren **tatsächlichen**, unterschiedlichen Clientverträgen integrieren: optional read-only, revisionsgebunden, Toolaufrufe aus Modell-/CLI-Quittungen messen, keine Behauptung aus `mcp list` allein.
- Konfiguration fremder Repositories oder `heim-pc`/Grabowski nur über **eigene separate PRs und die zuständige Writer-Autorität**, nicht ungefragt durch RepoGround-Lesezugriffe.
- Prüfe mindestens eine echte schwierige Änderung pro Consumer mit gültigen Quellen und offenem Fallback. Das ist eine Integrations-/Korrektheitsprobe, **nicht** das abschließende Werturteil.
- Quellen vor Schlussfolgerung: RepoGround indexiert, Agent interpretiert, Git/CI/Runtime bestätigen unabhängig.

## 3. Ereignisbasierte, inkrementelle Kontextbereitstellung (RG-XC-02)

- Bestehende Fleet-Publisher-/Watcher-/Incremental-Snapshot-Flächen erweitern: autorisierte Git-/CI-Ereignisse können einen **fest definierten, idempotenten** Analysejob und versionierten Kontext-Handoff auslösen.
- Event-Key aus Quelle/Ereignis-ID/Revision, gegen Mehrfachausführung deduplizieren; begrenzte Replay-/Backfill-Möglichkeiten, sichtbarer Lag, Stale- und Fehlerstatus.
- Reader bleiben ohne Nebenwirkung. Der schreibende Watcher/Publisher handelt unter separatem Host-/Lease-Vertrag; **keinen zweiten Scheduler/Daemon/Rootweg** erfinden, solange bestehende Wege reichen.
- Ein realer Commit oder CI-Übergang → genau ein überprüfbares aktuelles Evidence Pack, das Grabowski/Claude/Codex abrufen können. Es folgt **kein** automatischer Patch/Merge/Deploy.

## 4. Paralleler Betrieb mit den anderen beiden Threads

**Eigene primäre Codeflächen:** `core/mcp_tools.py`, `cli/mcp_stdio.py`, `core/context_compiler.py`, `core/agent_reading_pack.py`, `retrieval/task_profile_routing.py`, enger Read-only-CLI-/Event-Handoff-Adapter, einschlägige Consumer/MCP-Tests und Dokumentation.

**Nicht berühren:** `architecture/`, Kern-Graph/Impact-Dateien (Thread 1); `core/federation.py`, `core/history_lens.py`, `retrieval/federation_query.py`, `cli/cmd_federation.py` (Thread 2). Thread 3 verbraucht die **veröffentlichten** internen Ergebnisverträge beider Lanes; bis dahin vorhandene Bundles/Responses oder Test-Fixtures verwenden. Keine parallelen Änderungen an Master-Roadmap, `AGENTS.md` oder denselben Contractdateien. Contract-Integration in kleine Folge-PRs auf Main aufteilen.

Wenn `service/models.py`/`JobRequest` oder Frontend-Funktionen tatsächlich geändert werden, bestehende Pythonista/WebUI-Parität samt `tools/parity_guard.py` verpflichtend wahren.

## 5. Konkrete Ausführung, nicht bloß Verbindungstest

1. Reale aktuelle Consumer-/Publisher-Readbacks, RepoGround-Aufrufspuren und Source-Bindung sammeln; 2–5 gezielte Checks für das erste Hindernis, dann minimal implementieren.
2. Erst funktionsfähiges Evidence Pack an einem **echten Pull-Request-Diff** in der bestehenden API/CLI, danach task-profile routing und Agentenaufrufe, anschließend Event-/Handoff-Workflow.
3. Im eigenen Grabowski-Worktree testen, committen, PR öffnen, erforderliche CI-/Sicherheits-/Review-Gates durchlaufen; nach Merge Live-Bundle-/Consumer-Readback verifizieren.
4. Bei Cross-Repo-Konfigurationsänderungen separates scoped Writer-PR erstellen; systemweite Änderungen erst nach isolierter Freigabe. Nie Zugriffsdaten oder ChatGPT-Authentifizierung in Bundles/Logs/Repo exportieren.
5. Sobald Thread 1 und 2 stabile interne Antwortformen liefern, diese an die **eine vorhandene** Frontdoor anschließen. Keine zweite Agentenplattform aufbauen.
6. Den systematischen 20+-Aufgaben-A/B-Test und ökonomische Gesamtbewertung erst **nach** breitem Ausbau ansetzen; Tool-/Kostenquittungen während der Entwicklung sammeln, aber keine Gate-Blockade daraus machen.

**Fertig:** Agenten können an realen PRs deterministische Change-/History-/Cross-Repo-Belege nutzen, sie in Source/CI überprüfen, und ein autorisiertes Ereignis produziert nachweislich einen deduplizierten Context-Handoff. Mindestens zwei reale Consumer nachweislich benutzt, sichere Fallbacks, fokussierte Tests, PR-/Merge-Receipts, offengelegte Unbekannte.

**Übergabe:** konkrete CLI/MCP-Beispiele und Response-SHAs, betroffene externe Consumer-PRs, CI-Läufe, Event-/Handoff-Receipt, Source-/Revisionsbindung und verbleibende Abhängigkeiten zu Thread 1/2.
