# RepoGround Thread 1: deklarative Quellbeziehungen (Welle 4)

**Stand:** 2026-10-27. **Implementierungsbasis:** Pull Requests [#1353](https://github.com/heimgewebe/repoground/pull/1353), [#1354](https://github.com/heimgewebe/repoground/pull/1354) und [#1356](https://github.com/heimgewebe/repoground/pull/1356). Diese Welle ist auf dem Head von #1356 gestapelt.

## Bereits existierenden Graphen erweitern

Das bestehende File-Inventar (`architecture/import_graph.py`) erkennt jetzt zusätzlich `.sh`, `.bash`, `.zsh`, Systemd-`.service/.socket/.timer/.target/.path`, `.caddy` und die endungslose Datei `Caddyfile`. Die Dateiliste wird weiterhin durch die bestehenden File- und Byte-Grenzen beschränkt. Es gibt keinen neuen Index, keinen eigenen Publisher und keinen KI-Agenten.

`architecture/static_config_links.py` hängt an `architecture/declared_relations.py` an und liefert versionstreue, gerichtete `references`- und `configures_service`-Kanten in `lenskit.relationship_projection` v1.0:

| Quellformat | Statischer Beleg | Stufe |
|---|---|---|
| Markdown | Literaler lokaler Link zu einer exakt inventarisierten Datei | S1 (Dateireferenz; Anker ungeprüft) |
| GitHub Actions | `jobs.<job>.uses` auf bekannte lokale Workflow-Datei bzw. `steps[*].uses` auf einzigartige lokale `action.yml/.yaml`-Metadaten | S1 (Quellreferenz; keine Ausführungszusage) |
| GitHub Actions | Externe Referenz, ungültige/mehrdeutige lokale Metadaten oder dynamische Referenz | S0 |
| Shell | `source ./...` bzw. `. ./...` | S0 wegen unbekanntem Arbeitsverzeichnis |
| Systemd | `Requires/Wants/After/Before/BindsTo/PartOf` sowie konfigurierte Unit-Datei | S0, keine Aussage zu geladenen Units |
| Caddy | `import` mit Dateinamen/Snippet/Glob | S0, keine Aussage über effektive Konfiguration |

Markdown-Codeblöcke/Inline-Code/HTML-Kommentare und GitHub-Actions-Run-Blockskalare werden nicht als echte Deklaration gelesen. GitHub-Actions-Keys außerhalb gültiger `jobs`-/`steps`-Positionen dürfen niemals eine S1-Referenz erzeugen. Lokale Workflowdatei und lokales Action-Verzeichnis sind unterschiedliche Syntaxarten. Die bestehenden SHA-, Provenienz- und Kantenlimits bleiben intakt; `core/revision_graph_impact.py` teilt seinen Quellklassen-Check mit dem Inventar, damit auch ignorierte `Caddyfile`-Dateien und Symlinks keinen scheinbar revisionsfesten Beleg liefern.

Für die lokale GitHub-Actions-Syntax wurde die aktuelle offizielle Dokumentation über Context7 (`/websites/github_en_actions`, *Workflow syntax / Reuse workflows*) geprüft. `./.github/workflows/...yml` ist ein same-commit Workflow-Quellverweis, während lokale Action-Schritte Verzeichnisse mit Metadaten referenzieren. `./`-Actions können vom tatsächlichen Checkout des Runners abhängen: RepoGround leitet daraus **keine** Laufzeitwirkung ab. Ausschließlich Python-Standardbibliothek, daher keine weiteren externen API-/Parser-Abhängigkeiten.

## Reproduzierbare Tests

```bash
python3 -m unittest merger.repoground.tests.test_static_config_links merger.repoground.tests.test_revision_graph_impact merger.repoground.tests.test_declared_relations merger.repoground.tests.test_relationship_projection -q
python3 scripts/ci/check_module_reachability.py --root . --format text
```

Bereits vor diesem zusätzlichen PR ausgeführter lokaler Testlauf: **49 bestanden**, Reachability **270 Produktmodule, 0 unbelegte**. Die GitHub-CI des neuen PR ist die maßgebliche separate Integrationsprüfung; lokal fehlte die native `ruff`-/`pytest`-Python-Umgebung, daher dürfen deren Ergebnisse nicht als lokal bestanden ausgegeben werden.

**Vorläufige diagnostische Quelle, kein veröffentlichter Bundle-Snapshot:** Auf dem uncommitteten vierten Wellen-Checkout wurde `generate_relationship_document` mit einem ausdrücklich diagnostischen Run-ID und Dummy-Hash auf den realen RepoGround-Quellen ausgeführt. Ausgabe: 118.626 vorhandene Graphkanten; davon 158 Kanten aus den neuen Deklarationsursprüngen, 88 S1, 70 S0 (u. a. 90 Markdown-Links und 63 externe GitHub-Actions-Verweise). Dabei meldete der Parser zwei übersprungene, zu große Quelldateien und folglich `declared_source_coverage.truncated=true`. Diese Diagnostik **ist kein revisionsgebundener, publizierter Graph** und darf nicht als solcher verwendet werden.

Vor der breiten Integration sind bestehende Captain-Gates einschließlich nachgewiesener Operator-Integrität, aktueller CI und verifizierter Self-Review-Evidenz zwingend. Für den tatsächlichen Change-Impact aus echten Git-Commits liegen auf #1356 separate SHA-gebundene Berichte vor; dieser neue Graphpfad macht keine automatische Mergeentscheidung und liefert keine Test-Suffizienzbehauptung.
