# RepoGround – Codex JSONL-Adapter für reale A/B/C-Langzeitmessungen

**Status:** Der Adapter ist ein expliziter, instrumentierter Prozess für das bestehende
[Langzeit-Messprotokoll](repoground-agent-study-v1.md). Er erstellt weder Snapshots
noch führt er ungefragt Providerläufe aus. Jede tatsächliche Ausführung muss
eine eigene Run-ID und einen vorher gebundenen Protokollschlüssel besitzen.

## Aufgabe und Garantien

Die CLI `tools/agent_study_codex_runner.py` liest genau einen
`repoground.agent_study_request` von stdin und gibt höchstens ein JSON-Receipt
auf stdout zurück. Der vorhandene
`merger.repoground.cli.agent_study`-Runner erzeugt und bewertet die Aufträge.

- **A – git_only:** Codex erhält keine RepoGround-MCP-Registrierung. User-Apps
  und Plugins sind bei allen Bedingungen deaktiviert.
- **B – repoground_mandatory:** Dieselben Git-/Dateiwerkzeuge, zusätzlich
  exakt die gebundenen RepoGround-MCP-Werkzeuge; wenigstens ein tatsächlich
  erfolgreicher RepoGround-Aufruf ist erforderlich.
- **C – repoground_selective:** Dieselben Werkzeuge wie B, aber auch null
  RepoGround-Aufrufe gelten als korrektes selektives Verhalten.
- **Gleiche Aufgabe:** Der eigentliche Fragetext wird für alle Arme bytegleich
  übertragen. Nur der experimentelle Werkzeugzugang und die dokumentierte
  Gebrauchspflicht unterscheiden sich.
- **Frische Umgebung:** Jede Anfrage benutzt eine einmalige Codex-Sitzung
  (`--ephemeral`) und einen neuen privaten Workspace. Git-Quellen werden
  von den explizit gebundenen Repositories nach dem eingefrorenen Commit
  geklont, ohne den aktuellen HEAD als Ersatz zu verwenden.
- **Exakter MCP-Werkzeugumfang:** Mit `--repo-root` bietet der Server unter anderem `change_evidence_pack` an. Codex erhält ausschließlich die zwölf im Experiment vorgesehenen Read-Tools über `mcp_servers.<server>.enabled_tools`. Der lokale Codex-CLI-Client 0.164.0 bestätigte diese Whitelist im Konfigurations-Readback; nachträglich hinzugefügte Serverwerkzeuge sind nicht automatisch verfügbar.
- **Unveränderliche Belege:** Die verwendeten Bundle-Manifeste, Generator-,
  Quell- und Health-Identitäten werden vor dem Providerstart geprüft.
  Danach bekommt jeder Agentenlauf eine **private Kopie der exakten
  Manifestbytes** im frischen Workspace; referenzierte, unveränderliche
  Bundle-Artefakte werden ohne erneutes Kopieren per Hardlink eingebunden.
  Eine lokale Kopie des Post-Emit-Health-Dokuments wird zusätzlich an den
  originalen Manifest-SHA256 gebunden, weil der ursprüngliche absolute
  Publikationspfad kein Pfad zur privaten Kopie ist. Das MCP startet
  ausschließlich mit dieser privaten Manifestdatei und prüft den Hash
  nach dem Providerlauf erneut. Damit kann das spätere Ersetzen eines
  öffentlichen Manifestpfads keinen anderen Snapshot unter derselben
  `pinned_exact`-Quittung einschleusen. Der Original-Health-Beleg
  und das ursprüngliche Bundle bleiben unverändert.
- **MCP-Ressourcenmetadaten:** Die Codex-eigenen Aufrufe
  `list_mcp_resources` und `list_mcp_resource_templates` dürfen
  nichtleere Ressourcenlisten liefern. Diese Aufrufe bleiben im
  unveränderten JSONL-Trace erhalten, zählen aber weder als
  RepoGround-Abfrage noch als fehlgeschlagener unregistrierter Read.
  Ein tatsächliches nicht zugelassenes Ressourcen-Lesewerkzeug wird
  hingegen weiterhin abgewiesen.
- **Echte Messwerte:** Input-/Output-/Cache-Tokens werden ausschließlich
  aus dem tatsächlichen `turn.completed.usage` des Codex-JSONL übernommen.
  Die Zeit umfasst den gesamten Codex-Aufruf. Tool-Ein-/Ausgabebytes
  stammen aus beobachteten Start-/Ende-Ereignissen.
  Abrechnungskosten bleiben `null`, solange der Provider keine tatsächliche
  Rechnung pro Lauf liefert.

**Wichtige Grenze:** Einzelne Codex-JSONL-Toolereignisse enthalten nicht
zwingend eine eigene monotone Zeitangabe. Der Adapter misst deshalb die
lokalen Empfangszeitpunkte von `item.started` und `item.completed`.
Werden beide Ereignisse zusammen ausgeliefert, kann die beobachtete
Einzellatenz **0 ms** betragen, obwohl das Werkzeug gearbeitet hat.
Diese Toolzeiten sind nur Beobachtungs-/Untergrenzen, nicht
präzise providerinterne Werkzeuglaufzeiten. Sie dürfen nicht als
Kausalnachweis für die End-to-End-Dauer verwendet werden.

## Vorbedingungen

Ein lokaler, authentifizierter Codex-CLI-Client sowie ein funktionierendes,
rein lesendes RepoGround-MCP müssen vorhanden sein. Die Codex-Binary,
MCP-Python-Binary und MCP-Skriptdatei werden mit absoluten Pfaden benannt.
Drei Git-Repositories müssen die Frozen-Commits als Git-Objekte enthalten.
Unregistrierte Apps/Plugins sind ausgeschlossen, und die Arbeitsräume
dürfen keine fremden Chat- oder Lauftranskripte enthalten.

Das Adapterprofil wird vor einer Messreihe unveränderlich festgelegt.
Modell, Codex-Version, Adapter-Dateihash, MCP-Skripthash **und**
SHA256 des installierten MCP-Implementationsquellbaums (ohne Tests/Fixtures),
Sampling, Hostklasse, Cachemodus und Werkzeugnamen gehören zum
`protocol_key`. Der dünne MCP-Launcher allein identifiziert
die tatsächlich ausgeführten Handler nicht. Bei einer Adapteränderung startet eine neue
Studienkohorte mit **neuer Run-ID**; eine abgebrochene Position darf
nicht heimlich als Wiederholung erneut laufen.

## Praktischer Ablauf

`runner-resources.json` wird **außerhalb des Repositories** in einem
privaten Verzeichnis hinterlegt (keine Secrets im JSON):

```json
{
  "codex_bin": "/ABSOLUT/CODEX-BINARY",
  "mcp_python": "/ABSOLUT/REPOGROUND-PYTHON",
  "mcp_script": "/ABSOLUT/repoground-mcp-stdio.py",
  "source_roots": {
    "repoground": "/ABSOLUT/GIT/repoground",
    "grabowski": "/ABSOLUT/GIT/grabowski",
    "commonthing": "/ABSOLUT/GIT/commonthing"
  },
  "workspaces_root": "/PRIVAT/STUDIE/workspaces",
  "trace_root": "/PRIVAT/STUDIE/traces"
}
```

Zunächst die tatsächlich installierte Adapter- und Toolidentität ermitteln:

```bash
python3 -B tools/agent_study_codex_runner.py \
  --config /PRIVAT/runner-resources.json --fingerprint
```

Aus diesen **wirklich beobachteten** Werten ein `profile.json`
mit Provider `openai-codex-cli`, exakter Modellkennung und
Sampling `{"model_reasoning_effort":"medium"}` bilden.
`tool_names` und `runner_version` sind unverändert aus dem
Fingerprintergebnis zu übernehmen. Der `host_class`-Wert bezeichnet
die tatsächlich verwendete Hostkonfiguration, `cache_policy` hier
`controlled`.

Der vorhandene Planer erzeugt aus eingefrorenem Taskset, Git-Wurzeln,
gesundheitsgeprüften Manifesten und dem Profil den A/B/C-Plan:

```bash
python3 -B -m merger.repoground.cli.agent_study plan \
  --taskset docs/retrieval/repoground_agent_study_cases.v1.json \
  --profile /PRIVAT/profile.json --roots /PRIVAT/roots.json \
  --snapshots /PRIVAT/snapshots.json \
  --run-id EINE-NEUE-RUN-ID --suite pilot --repetitions 2 \
  --out /PRIVAT/plan
```

Die Runner-Argumentliste wird ohne Shell-Interpretation gespeichert:

```json
["python3", "-B", "/ABSOLUT/REPOTREE/tools/agent_study_codex_runner.py",
 "--config", "/PRIVAT/runner-resources.json"]
```

Danach kontrolliert ausführen, etwa zunächst mit `--max-runs 3`
für genau einen balancierten Aufgabenblock:

```bash
python3 -B -m merger.repoground.cli.agent_study run-batch \
  --plan /PRIVAT/plan/plan.json \
  --runner-command /PRIVAT/runner-command.json \
  --trace-root /PRIVAT/STUDIE/traces \
  --receipts /PRIVAT/STUDIE/receipts --max-runs 3 \
  --timeout-seconds 360
```

Der nächste Aufruf ohne `--max-runs` fährt nur fort, wo noch kein
Versuch gestartet wurde. Bereits gültige Receipts werden nochmals
vollständig geprüft. Jede begonnene Position besitzt eine create-only
`.attempts`-Quittung. Auch bei fehlerhaftem JSONL,
abgebrochener Ausgabe oder Timeout speichert der Adapter die bis dahin
empfangenen, auf 32 MiB begrenzten Originalbytes zunächst mit Dateimodus
`0600` und `fsync` im privaten Trace-Verzeichnis. Ein Fehler ohne
gültiges Receipt bleibt als Versuch erhalten; er wird **niemals
automatisch erneut gestartet**. Ein Rawtrace allein ist kein
gültiges Provider-/Qualitäts-Receipt.

## Bewertung und Langzeitvergleich

Die vollständigen Codex-JSONL-Transkripte enthalten potentiell
private Informationen. Sie bleiben im privaten Studien-State, nicht
in Git. Nur der gebundene Hash, Byteumfang und der bereinigte
Auswertungsbericht können nach Sichtprüfung versioniert werden.

Nach den Läufen müssen unabhängige Prüfer die **echten Antworten**
und **jede als geprüft bewertete Quellenzeile** am eingefrorenen
Git-Commit lesen. Die separat versionierte Goldpfadliste ist dabei
eine Prüfhilfe, keine automatische Wahrheitsgarantie. Eine
ungeprüfte Modellantwort erhält **kein** Qualitätssiegel.

```bash
python3 -B -m merger.repoground.cli.agent_study evaluate \
  --taskset docs/retrieval/repoground_agent_study_cases.v1.json \
  --plan /PRIVAT/plan/plan.json \
  --receipts /PRIVAT/STUDIE/receipts \
  --trace-root /PRIVAT/STUDIE/traces \
  --grades /PRIVAT/STUDIE/grades.json \
  --measurement-scope real_runner_reported \
  --out /PRIVAT/STUDIE/report.json \
  --markdown /PRIVAT/STUDIE/report.md
```

Ohne unabhängige `grades.json` wird `--grades` weggelassen.
Dann liegen womöglich echte Zeit-/Tokenmessungen, aber **keine
unabhängig nachgewiesenen Antworten** vor. Eine Full-Study- oder
Default-Beförderung folgt daraus nie automatisch.

Verschiedene `protocol_key`-Werte (neuer Agent, Modell, Runner,
Prompt, Hardwareklasse oder Cachepolitik) sind verschiedene
Vergleichsgruppen; die `trend`-Funktion hält sie getrennt.
Ein neuer RepoGround-Generator darf als beabsichtigter Eingriff
wechseln, während die **Quellrevisionen** für den Längsschnitt
unverändert bleiben.

## Tests und Grenzen

```bash
python3 -B tests/test_agent_study_codex_runner.py
```

Die Vertragstests verwenden keinen Provider und sind **synthetische
Negativ-/Parserkontrollen**, keine Agentenleistung. Vor der
Produktivverwendung müssen der echte GitHub-CI-Prüfstand, der
revisionsgenaue PR-Review und der tatsächliche Lauf an einem
neuen Agenten-Request bestanden sein.

Für den Übergang zu anderen Providern ist kein zweiter Dienst
erforderlich: `agent_study` nutzt bereits ein allgemeines JSON-stdio-
Runnerinterface. Ein anderer Provider benötigt allerdings seinen
eigenen tatsächlich instrumentierten Adapter und einen **anderen**
Protokollschlüssel.