# RepoGround Agent Benchmark v1 bedienen

Der Benchmark-Harness ist ein Prüfstand. Er plant und prüft echte Agentenläufe,
stellt aber selbst weder ein Sprachmodell noch Zugangsdaten bereit.

## 1. Gefrorenes Taskset prüfen

```bash
python -m merger.repoground.cli.agent_benchmark validate-taskset \
  --taskset docs/retrieval/repobrief_agent_benchmark_taskset.v1.json
```

Die Ausgabe nennt Taskset-ID, SHA-256 und Fallzahl. Für v1 müssen genau 24
Fälle vorhanden sein. Jede inhaltliche Änderung verändert den SHA-256 und ist
damit ein anderes Experiment.

## 2. Runner-Identität beschreiben

`runner.json` enthält keine Zugangsdaten. Es bindet nur die Konfiguration, die
später für beide Bedingungen identisch sein muss:

Für einen generischen externen Runner kann die Datei weiterhin providerneutral
bleiben:

```json
{
  "provider": "provider-name",
  "model": "exact-model-id",
  "sampling": {
    "temperature": 0
  }
}
```

Ein Grabowski-Liveplan über Claude Code muss dagegen den ausführbaren Vertrag
explizit binden:

```json
{
  "execution_contract": "grabowski-claude-code-live-v1",
  "provider": "anthropic-claude-code",
  "model": "claude-haiku-4-5-20251001",
  "sampling": {}
}
```

Der Vertrag wird in jeden erzeugten Request übernommen. Die mehrdeutige
Providerkennung `anthropic`, ein anderer Provider unter diesem Vertrag, ein
unbekannter Vertrag oder ein nicht leeres Samplingobjekt werden bereits beim
Planen abgelehnt. Damit kann ein formal erzeugter Plan nicht erst beim späteren
Live-Runner an diesen Identitätsunterschieden scheitern.

Der externe Runner muss dieselbe Provider-, Modell- und Sampling-Identität in
jeder Laufquittung zurückgeben.

## 3. RepoGround-Snapshots binden

`manifest-bindings.json` ordnet jedem Repository seinen unveränderlichen
Snapshot und den lokalen MCP-Startbefehl zu:

```json
{
  "lenskit": {
    "manifest": "/absolute/path/lenskit.bundle.manifest.json",
    "manifest_sha256": "64-lowercase-hex-characters",
    "mcp_command": [
      "python",
      "scripts/repoground-mcp-stdio.py",
      "--bundle-root",
      "/absolute/path/to/bundle"
    ]
  },
  "grabowski": {
    "manifest": "/absolute/path/grabowski.bundle.manifest.json",
    "manifest_sha256": "64-lowercase-hex-characters",
    "mcp_command": ["...", "..."]
  },
  "weltgewebe": {
    "manifest": "/absolute/path/weltgewebe.bundle.manifest.json",
    "manifest_sha256": "64-lowercase-hex-characters",
    "mcp_command": ["...", "..."]
  }
}
```

Die Beispielwerte müssen durch reale Manifestpfade, echte Digests und einen
funktionierenden lokalen MCP-Befehl ersetzt werden.

## 4. Vollständigen Paarplan erzeugen

```bash
python -m merger.repoground.cli.agent_benchmark plan \
  --taskset docs/retrieval/repobrief_agent_benchmark_taskset.v1.json \
  --runner runner.json \
  --manifest-bindings manifest-bindings.json \
  --repetitions 2 \
  --out benchmark-plan
```

V1 akzeptiert ausschließlich zwei Wiederholungen. Der Plan enthält 96
Laufaufträge:

- 24 Fälle;
- zwei Bedingungen;
- zwei Wiederholungen.

Jeder Auftrag besitzt eine eigene Sitzungs- und Arbeitsraum-ID. Baseline und
Behandlung dürfen diese Identitäten nicht teilen.

## 5. Externen Runner binden

`runner-command.json` ist eine JSON-Argumentliste, keine Shell-Zeichenkette:

```json
[
  "/absolute/path/to/instrumented-agent-runner",
  "--json-stdio"
]
```

Ein einzelner Auftrag wird so ausgeführt:

```bash
python -m merger.repoground.cli.agent_benchmark run \
  --request benchmark-plan/requests/REQUEST.json \
  --runner-command runner-command.json \
  --transcript-root benchmark-transcripts \
  --out benchmark-receipts/REQUEST.json
```

Der Runner liest den vollständigen Auftrag als JSON von Standard Input und
schreibt genau eine strukturierte Laufquittung nach Standard Output. Er muss
unter anderem liefern:

- exakte Provider- und Modellkennung;
- vom Provider gemeldete Input- und Output-Tokens;
- Toolaufrufe mit Status, Dauer und Byteumfang;
- finale strukturierte Antwort;
- vollständiges Inline-Transcript oder ein hashgebundenes Transcript-Artefakt;
- Exitstatus und strukturierte Fehlerklasse.

Fehlende oder geschätzte Tokenwerte gelten nicht als null, sondern machen den
Lauf ungültig.

## 6. Einzelne Quittung nachprüfen

```bash
python -m merger.repoground.cli.agent_benchmark validate-receipt \
  --request benchmark-plan/requests/REQUEST.json \
  --receipt benchmark-receipts/REQUEST.json \
  --transcript-root benchmark-transcripts
```

Die Prüfung umfasst Identität, Auftrag-SHA-256, Tool-Allowlist, Budgets,
Transcript-Digest und Statuskonsistenz.

## 7. Vollständige Auswertung erzeugen

Für echte gepaarte Agentenläufe:

```bash
python -m merger.repoground.cli.agent_benchmark evaluate \
  --taskset docs/retrieval/repobrief_agent_benchmark_taskset.v1.json \
  --requests benchmark-plan/requests \
  --receipts benchmark-receipts \
  --transcript-root benchmark-transcripts \
  --measurement-scope real_paired_agent_runs \
  --out benchmark-evaluation.json
```

Für reine Vertragstests muss stattdessen
`synthetic_contract_fixture` verwendet werden. Eine solche Auswertung bleibt
zwingend `synthetic_only` und darf keinen Agentennutzen begründen.

## Gültigkeitsgrenzen

Ein Lauf oder Paar wird unter anderem ungültig bei:

- verändertem Prompt, Commit, Budget oder Toolvertrag;
- unterschiedlicher Modellkonfiguration innerhalb eines Paars;
- fehlendem oder doppeltem Auftrag beziehungsweise Receipt;
- wiederverwendeter Sitzung oder wiederverwendetem Arbeitsraum;
- nicht erlaubtem Werkzeug;
- geschätzten statt Provider-gemeldeten Tokens;
- fehlendem, manipuliertem oder außerhalb des Transcript-Verzeichnisses
  liegendem Transcript;
- Budgetüberschreitung.

Ungültige oder fehlgeschlagene Läufe bleiben in der Auswertung sichtbar. Sie
werden nicht still wiederholt oder in erfolgreiche Werte umgedeutet.

## Was v1 noch nicht leistet

Der Harness belegt allein keinen realen Vorteil von RepoGround. Dafür muss
`RAB-V1-T002` einen qualifizierten instrumentierten Agent-Runner binden und den
vollständigen Plan zweimal unter realen Bedingungen ausführen. Bis dahin gilt
`default_promoted=false`.
