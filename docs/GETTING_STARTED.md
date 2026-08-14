# Getting Started mit RepoGround

> Aktualisiert am 2026-08-07.
> Einstieg in fünf Minuten: Repository aufbereiten, Ergebnis lesen, durchsuchen.
> Für die normative Spezifikation siehe
> [`merger/repoground/repoground-build-spec.md`](../merger/repoground/repoground-build-spec.md),
> für die Architektur die
> [Systemkarte](architecture/system-map.repoground.md), für Begriffe das
> [Glossar](glossary.md).

## 1. Was ist RepoGround?

RepoGround ist **Merger** und **Scanner** im Heimgewebe-Organismus. Es überführt
Arbeitskopien von Repositories in strukturierte, für LLMs navigierbare und
**zitierbare** Hyper-Merge-Berichte (Bundles). Es gibt zwei funktionsgleiche
Frontends:

- **RepoGround** — die Pythonista/iPad- und CLI-Oberfläche
  (`merger/repoground/frontends/pythonista/build.py`).
- **RepoGround** — die Web-UI/Service-Schicht für Heim-PC/Server
  (`merger/repoground/cli/serve.py`, `merger/repoground/service/app.py`).

Die **Wahrheitsquelle** ist immer der kanonische Markdown-Dump (`canonical_md`).
Alle anderen Artefakte (Index, Citation-Map, Agent Reading Pack, Health) sind
**Navigation/Diagnose, nicht Wahrheit**.

## 2. Voraussetzungen und reproduzierbarer Einstieg

### Python- und Abhängigkeitsvertrag

- **CPython 3.12** ist die aktuelle CI- und Release-Kandidaten-Basis. Genau
  diese Version läuft in `pytest-full` und `release-candidate`.
- Ein anderer Interpreter ab Python 3.10 kann einzelne Core-Pfade ausführen,
  gehört aber nicht zur aktuell reproduzierten Release-Basis; `repoground
  doctor` meldet ihn deshalb als `degraded` statt ihn still als gleichwertig
  auszugeben.
- Der Repositoryvertrag behauptet derzeit **keine PyPI-/Wheel-Installation** als
  kanonischen Einstieg. Der reproduzierbare Pfad ist ein Source-Checkout plus
  die hashgebundenen Locks im Repository.

Einen neuen Source-Checkout anlegen und anschließend in einer lokalen Python-3.12-Umgebung den reproduzierbaren Runtime-Lock anwenden:

```bash
git clone https://github.com/heimgewebe/repoground.git
cd repoground
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements/repoground-runtime.lock.txt
.venv/bin/python -m merger.repoground --version
.venv/bin/python -m merger.repoground doctor --repo-root .
```

`doctor` installiert oder repariert nichts. Direkt nach einem frischen Checkout
ohne vorhandenes Bundle ist ein `degraded`-Ergebnis erwartbar; die einzelnen
Checks erklären den Grund. Der optionale globale Befehl `repoground` ist kein
Dienststarter: die kanonische Vorlage liegt in
`scripts/ops/repoground-cli-wrapper`, startet Python gegen CWD-Shadowing im
Isolated Mode und delegiert anschließend an die kanonische RepoGround-CLI. Das
aufrufende Arbeitsverzeichnis bleibt dabei für relative Nutzerpfade erhalten.
Standardmäßig ist `~/repos/repoground` der Source-Checkout; für einen anderen
Checkout kann `REPOGROUND_ROOT` explizit gesetzt werden. Auf verwalteten
Heim-PC-Installationen bevorzugt der Wrapper ohne explizites
`REPOGROUND_PYTHON` den Interpreter der **aktiven immutable Runtime** unter
`~/.local/share/repoground-runtime/current/.venv/bin/python`; fehlt dieser
Aktivierungszeiger, bleibt `python3` der kompatible Fallback für Core-Pfade und
Doctor meldet weiterhin die Abweichung von der 3.12-Basis. Ein explizites
`REPOGROUND_PYTHON` hat Vorrang vor beiden Defaults.

Der Produktionsdienst hat einen strengeren Vertrag als die statische
Source-Checkout-Beispielunit in `docs/systemd/repoground.service`: produktive
Runtimes werden aus einem verifizierten Release-Kandidaten git-frei unter
`~/.local/share/repoground-runtime/<commit>` materialisiert. Source-Verzeichnis,
`PYTHONPATH`, `REPOGROUND_VERSION`, `REPOGROUND_BUILD_ID` und der Interpreter
`<commit>/.venv/bin/python` müssen auf denselben exakten Commit zeigen.
`scripts/ops/render_repoground_immutable_service.py` rendert diese commitgebundene
Produktionsunit deterministisch; sie fällt **nicht** auf `/usr/bin/python3`
zurück. Der `current`-Zeiger ist nur die CLI-Aktivierungsreferenz und darf erst
nach vorbereitetem Canary/Rollback atomar auf denselben Release umgeschaltet
werden, den der Dienst explizit verwendet.

Doctor vergleicht einen gefundenen globalen Wrapper mit der Vorlage aus der
laufenden RepoGround-Installation, unabhängig vom per `--repo-root` untersuchten
Repository, und meldet historische Service-/Browser-Starter oder fremde
Executables nicht als `available`.

Für Tests und Entwicklungswerkzeuge zusätzlich:

```bash
.venv/bin/python -m pip install --require-hashes -r requirements/repoground-dev.lock.txt
```

Wer Abhängigkeits-Locks pflegt, verwendet ausschließlich den in der
[Release-Policy](release/release-policy.md#dependency-locks) beschriebenen
Python/pip/pip-tools-Vertrag. Die dort gebundenen Versionen werden aus
`requirements/repoground-lock-tools.in` gelesen; ein implizites neuestes pip
ist nicht unterstützt. Im Normalfall wird das Lock-Werkzeug ausschließlich aus
der gehashten Tool-Lock installiert. Weicht ein exakter direkter pip- oder
pip-tools-Pin ab, kompiliert die bisherige gehashte Toolchain zuerst eine neue
gehashte Kandidaten-Tool-Lock. Die neue Toolchain wird erst daraus isoliert
installiert; nach der vollständigen Regeneration wird auch die endgültige
Tool-Lock erneut hashgebunden installiert und mit `--check` geprüft. Derselbe
kanonische Read-only-Check läuft lokal und in CI:

```bash
scripts/release/compile_dependency_locks.sh --check
```

Optionales semantisches Reranking hat einen engeren Vertrag und bleibt
standardmäßig aus. Unterstützt ist nur CPython 3.12 / Linux x86-64 / CPU:

```bash
.venv/bin/python -m pip install --only-binary=:all: --require-hashes \
  -r requirements/repoground-semantic-linux-x86_64-py312.lock.txt
```

### Upgrade eines Source-Checkouts

1. Den Checkout über den normalen reviewten Git-/Deployment-Pfad auf den
   gewünschten RepoGround-Commit bringen. `doctor` führt **kein** `fetch`,
   `pull`, `reset` oder anderes Upgrade aus.
2. Den aktuellen Commit mit `git rev-parse HEAD` kontrollieren.
3. Den hashgebundenen Runtime-Lock erneut anwenden; bei Entwicklungsarbeit auch
   den Dev-Lock.
4. `.venv/bin/python -m merger.repoground doctor --repo-root .` ausführen.
5. Nach Auswahl oder Erzeugung eines Bundles den strikten Bundle-Readback aus
   Abschnitt 6 ausführen.

Damit sind Source-Revision, Abhängigkeiten und Diagnose getrennt prüfbar. Ein
grüner Doctor ist trotzdem kein Test-, Review- oder Merge-Reife-Beweis.

## 3. Minimalbeispiel: einen Dump erzeugen

Aus dem Repo-Wurzelverzeichnis, das aktuelle Verzeichnis (`.`) aufbereiten:

```bash
# Schneller Überblick
python3 -m merger.repoground.frontends.pythonista.build . --level overview

# Voller Merge mit Split (20MB), voller Metadichte, Dual-Output (MD + Index)
python3 -m merger.repoground.frontends.pythonista.build . \
  --level max \
  --split-size 20MB \
  --meta-density full \
  --output-mode dual
```

Wichtige Flags (vollständig via `--help`):

| Flag | Werte | Bedeutung |
| --- | --- | --- |
| `--level` | `overview`, `summary`, `dev`, `max` | Detailtiefe / Profil |
| `--mode` | `gesamt`, `pro-repo` | Single- vs. Multi-Repo-Merge |
| `--output-mode` | `archive`, `retrieval`, `dual` | nur MD / nur Index / beides |
| `--meta-density` | `min`, `standard`, `full`, `auto` | Metadaten-Drosselung (Default `auto`) |
| `--split-size` | z. B. `20MB`, `1GB` | Ausgabe in Teile splitten |
| `--path-filter` | Substring, z. B. `docs/` | nur passende Pfade |
| `--extensions` | z. B. `.md,.py` | nur diese Endungen |
| `--code-only` / `--plan-only` | – | nur Code / nur Plan |
| `--json-sidecar` | – | maschinenlesbarer JSON-Zwilling |
| `--redact-secrets` | – | heuristische Secret-Redaktion |

> `--meta-density auto` wählt automatisch: `full` bei vollständigem Dump,
> `standard` sobald ein Pfad-/Endungsfilter aktiv ist.

## 4. Was kommt heraus? (Bundle lesen)

Ein Merge erzeugt ein Bundle mit invarianter Sektionsreihenfolge (Spec v2.4):
*Source & Profile → Profile Description → Reading Plan → Plan → Structure →
Manifest → Content*. Die wichtigsten Dateien:

| Datei (Rolle) | Wofür | Authority |
| --- | --- | --- |
| `*.merge.md` (`canonical_md`) | **Die Wahrheitsquelle.** Vollständiger Dump zum Zitieren. | `canonical_content` |
| `*.bundle.manifest.json` | Registry aller Bundle-Artefakte (Rollen, Pfade, Hashes). | – |
| `*.agent_reading_pack.md` | **Hier zuerst lesen** (LLM-Agent). Lese-Policy, Artefaktrollen, Suchanleitung, Health-Verdict, Top-Chunk-Spans. | `navigation_index` |
| `*.chunk_index.jsonl` | Chunk-Spannen für FTS/Range-Auflösung. | `retrieval_index` |
| `*.citation_map.jsonl` | Quell-Byte-Bereich → stabile Citation-ID. | `navigation_index` |
| `*.output_health.json` | Maschinenlesbarer Selbsttest (FTS leer? Range-Ref ok? Hash ok?). | `diagnostic_signal` |

Reihenfolge für LLM-Agents: **agent_reading_pack.md → manifest → canonical_md**.
Zitiert wird ausschließlich gegen `canonical_md`.

## 5. Durchsuchen & zitieren (`repoground` CLI)

```bash
# 0) Read-only Umgebung, MCP-Konfiguration und vorhandene Evidence prüfen
python3 -m merger.repoground doctor --repo-root . --json

# 1) Index bauen (SQLite FTS5)
python3 -m merger.repoground.cli.main index \
  --dump <dump_index.json> --chunk-index <chunk_index.jsonl> --out index.sqlite

# 2) Volltextsuche
python3 -m merger.repoground.cli.main query --index index.sqlite --q "range resolver" --k 10

# 3) Deterministischen Byte-Bereich auflösen (verifiziert Hash)
python3 -m merger.repoground.cli.main range get --manifest <bundle.manifest.json> --ref ref.json

# 4) Citation-Map erzeugen / Bundle-Health prüfen
python3 -m merger.repoground.cli.main citation produce <bundle.manifest.json> --json
python3 -m merger.repoground.cli.main bundle-health post <bundle.manifest.json>

# 5) Agent Reading Pack regenerieren
python3 -m merger.repoground.cli.main agent-pack produce <bundle.manifest.json> --json
```

Weitere Subkommandos: `doctor`, `eval`, `architecture`, `atlas`, `federation`,
`context-quality`, `governance`, `parity`, `artifact`, `service-client`, `verify`,
`pr-explain`. Jeweils `--help` für Details.

Federierte Query ohne persistierten Index:

```bash
repoground federation query --bundle repo_a=/path/to/bundle-a --bundle repo_b=/path/to/bundle-b -q "symbol" --trace
```

## 6. Doctor, erster Bundle-Readback und MCP

`repoground doctor` ist die gemeinsame **read-only** Diagnoseoberfläche. Sie
fasst vorhandene RepoGround-Prüfpfade zusammen, erzeugt aber keine zweite
Wahrheitsquelle. Jeder Check meldet `available`, `degraded` oder `blocked` sowie
Ursache, Auswirkung und eine erlaubte nächste Aktion. Fehlende optionale
Sprach-/Graphadapter blockieren den Python-/FTS-Kern nicht.

Nach dem ersten Build den vom Build ausgegebenen Manifestpfad exakt
zurücklesen:

```bash
.venv/bin/python -m merger.repoground doctor \
  --repo-root . \
  --manifest /absolute/path/to/<stem>.bundle.manifest.json \
  --strict --json
```

`--strict` liefert Exit 1, wenn ein **erforderlicher** Check nur `degraded` ist;
`blocked` liefert immer Exit 2. Fehlende optionale Adapter verändern den
Core-Gesamtstatus nicht. Der Freshness-Check vergleicht nur das vorhandene
Bundle mit dem ausdrücklich angegebenen lokalen Checkout. Er synchronisiert
nicht mit GitHub und baut kein Bundle neu.

Für projektlokales MCP ist die eingecheckte `.mcp.json` der kanonische Einstieg.
Sie startet `scripts/repoground-mcp-project.py`; dieser bindet den Checkout als
`--repo-root` und wählt fail-closed genau ein gesundes Bundle aus dem
kanonischen Publikationskatalog. Der Doctor prüft Konfigurationsdatei und Starter,
behauptet aber **keine** aktive MCP-Clientverbindung. Der direkte Serverstart und
die generische Client-Konfiguration stehen in
[`usage/repoground-mcp-stdio.md`](usage/repoground-mcp-stdio.md).

Doctor-Grenzen:

- kein `pip install` oder Interpreterwechsel;
- kein `git fetch/pull/reset` und keine Repositorymutation;
- kein Bundle-Build oder Refresh;
- kein Dienststart/-restart;
- kein Secret-Read;
- keine Netzwerk-Synchronisierung.

Ein `available`-Verdikt belegt lokale Bereitschaft der geprüften Oberflächen,
nicht Repositoryverständnis, Antwortkorrektheit, Testgenüge, Reviewvollständigkeit
oder Merge-Reife.

## 7. Fehlerbehebung (Kurz)

- **„range_ref failed schema" / Hash mismatch:** Der `range_ref` passt nicht
  zum Artefakt-Inhalt — Bundle veraltet oder Ref von Hand editiert. Bundle neu
  erzeugen; Felder nicht manuell ändern. Mehr im [FAQ](FAQ.md).
- **FTS-Index leer:** Repo enthält keinen indexierbaren Text, oder
  `--output-mode archive` (kein Index). Mit `dual`/`retrieval` neu bauen.
- **„No module named pytest" o. Ä.:** Dev-Abhängigkeiten installieren
  (Abschnitt 2).
- **Atlas verweigert Pfad:** `..`/relative Pfade sind verboten; absolute Pfade
  oder Presets nutzen (s. README, „ATLAS MODE").

## 8. Weiterlesen

- [Master-Roadmap](roadmap/repoground-master-roadmap.md) — Reihenfolge & Tracks
- [Systemkarte](architecture/system-map.repoground.md) — Modul-Zusammenspiel
- [Glossar](glossary.md) · [FAQ](FAQ.md) · [CONTRIBUTING](../CONTRIBUTING.md)
- [Service-API](service-api.md) · [Parity-Guard](PARITY_GUARD.md)
