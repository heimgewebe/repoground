# RepoGround: Produktionsanbindung von Graph und Revisionsanalyse

Stand: 2026-10-28, UTC. Status dieser Fassung: Implementierung und lokale
Integrationsprüfung; produktive Aktivierung und reale Clientabnahme folgen separat.
Diese Fassung behauptet keinen bereits erfolgten Produktivabschluss.

## Ausgangsbeobachtung

Die ursprünglichen Ausbau-PRs sind integriert, einschließlich
[Parserwelle #1359](https://github.com/heimgewebe/repoground/pull/1359)
mit Merge `f238d4b1d0e00017aedf9c0099d5d4918157f1c0`.
Die nachfolgende Integrationsänderung baut auf diesem Main-Stand auf und ersetzt
keinen der Original-PRs.

Das tatsächlich veröffentlichte Bundle enthielt bereits diesen Quellstand,
verwendete aber Generator `7300ab306fdad12d0ed1a8dbf43e2d14953c6681`:

- Stem: `heimgewebe__repoground__main--f238d4b1d0e00017aedf9c0099d5d4918157f1c0-max-261028-2104`
- Manifest-SHA256: `eba189d0ccda6a0a7d5eb496876472594a51e06511c6bcb95735cfdf629adb23`
- 23 registrierte Artefakte; Health PASS und Range Strict PASS.
- Keine Rolle `relationship_projection_json`.

Der gesunde Katalogeintrag war deshalb kein Nachweis, dass der neue
sprachübergreifende Graph über ein veröffentlichtes Bundle verfügbar war.

## Verbindung vorhandener Komponenten

Der bestehende Generator erzeugt zusätzlich die bereits implementierte
`lenskit.relationship_projection/1.0` im selben ausgewählten Quellbaum wie
Architekturgraph und Entry Points. Der bestehende Publisher bindet außerdem den Architekturordner in seinen
Generatorinputs-Digest und die kanonische Git-Blob-Prüfung ein; reine
Parseränderungen sind damit ebenfalls Generatoränderungen.
Er registriert die optionale Rolle
`relationship_projection_json` in beiden Manifestverträgen. Die Rolle ist
abgeleitete Navigation mit Content-SHA256 und Bytezahl, Vertragskennung,
Regenerierbarkeit und expliziter Veraltungsempfindlichkeit.

Der neue kleine Artefaktleser verwendet die vorhandene begrenzte und
requestgebundene Artefaktleseschicht. Er prüft die tatsächlich gelesenen Bytes,
Schema, eindeutige Registrierung, Run-ID, kanonischen Dump-Hash, gerichtete
Kantenidentitäten, Quellenbereiche, Coverage und verpflichtende Nichtaussagen.
Er ruft den vorhandenen Nachbarschaftscompiler auf. Es gibt keinen zweiten
Graphspeicher, Parser, Publisher oder impliziten Quellen-Refresh.

Die öffentliche Oberfläche besteht aus:

- MCP `get_structure_neighborhood` für exakte Datei- oder Symbol-IDs.
- CLI `architecture --relationships --bundle-manifest ... --target-id ...`.
- Struktureller Projektion im bestehenden `change_evidence_pack`.

Der Change-Pack verwendet den bestehenden Revisionscompiler. Die
strukturbezogene Diff-Identität, die äußere Textdiff-Identität und das
veröffentlichte Bundle bleiben getrennt. Die strukturelle Quellidentität heißt
weiterhin `derived_clean_git_tree` und ausdrücklich nicht Bundle-Manifest.

## Bytebindung und Nebenwirkungsgrenzen

Die Auswahl bleibt auf vollständigen, nicht redigierten und nicht
abgeschnittenen Bundlekontakt begrenzt. Vor der Materialisierung werden
vorhandene Chunkbereiche und Hashes geprüft:

1. Der rohe Dateipuffer entspricht dem erfassten Git-Blob-Hash.
2. Seine UTF-8-/Newline-normalisierte Form entspricht allen erfassten Chunk-Hashes.
3. Die Bereiche decken die vollständige Datei ohne Lücke ab.
4. Die Hashes entsprechen dem kanonischen oder eingebetteten Bundleinhalt.
5. Genau dieser geprüfte Rohbytepuffer wird materialisiert.

Ein späterer Quellenwechsel kann so keine unbelegte neue S1-Kante hinzufügen.
CRLF, CR und fehlende letzte Newlines bleiben unterstützt. Die bestehenden
Quellbyte- und Dateigrenzen gelten weiterhin.

Der Revisionscompiler verwendet den vorhandenen begrenzten Git-Leser aus der
Zeitgeschichte. Er deaktiviert Lazy Fetch und Ersatzobjekte, isoliert geerbte
Git-Konfiguration, verhindert optionale Indexlocks und lehnt konfigurierte
ausführbare Repository-Filter vor der Statusprüfung ab. Die History-Grenze von
2 MB bleibt erhalten; die bestehenden Revisionsgrenzen werden separat verwendet.

## Tatsächliche Prüfungen

Die folgenden Job-IDs sind dauerhafte Grabowski-Hostbelege, keine CI-Nachweise.

| Prüfung | Tatsächliches Ergebnis | Beleg |
| --- | --- | --- |
| Erste integrierte Bestandsprüfung | 132 bestanden, 1 fehlender neuer MCP-Registryeintrag; zusätzlich C901 um 1 überschritten | `grabowski-job-e7a0360000aa` |
| Vier Source-Drift-Regressionen vor Korrektur | Alle vier RED: nach Capture, zwischen Text/Blob, zwischen Canonical/Chunk und fehlender letzter Chunk | `grabowski-job-c8086ed1de59` |
| Echte Veröffentlichung vor Driftkorrektur | 3 bestanden: registrierte Rolle, Sprachbeziehungen, CLI/MCP | derselbe Job, getrennte Teilprüfung |
| Verbundene Suite nach Korrektur | 264 Tests und 8 Subtests bestanden | `grabowski-job-0da5085cc682` |
| Ruff F401/F811, Komplexität, Diff-Whitespace | Alle bestanden | derselbe Job |
| Erweiterte Manifest-Race-/Partial-Clone-Fälle | 3 bestanden | `grabowski-job-c9551fbc3579` |
| Owner-Generator und Modul-/Dokumentlinkprüfung | Alle bestanden | derselbe Job |
| Generatorinputs und unveränderte Git-Status/Filter-Probe einschließlich Architekturpfad | 5 bestanden | `grabowski-job-a7a014b050d6` |

SHA256 der vollständigen Ausgaben:

- Drift-RED: `e294d58a876c30ee583e6a6ae0087462144430805e92722e0c4507177cebfede`
- 264-Tests-Lauf: `c9b361f037280585092067e3035d40c76ffbf5f9bcd0eac4f6d51e61bea87461`
- Restprüfungen: `e3c61c9dbd3598ce17f8dfc6cf84d36b6cec1bcdac8f7b53dba81a3e3916b2a4`
- Publisher-Parserbindung: `d83b0b8fb92532103d1bb58da1779875419b030d7132a89c8c6823116226991a`

Die Umgebung wurde isoliert aus
`requirements/repoground-dev.lock.txt` mit `pip --require-hashes` aufgebaut.
Produktive Pythonpakete wurden dafür nicht verändert.

Die neuen Publication-Tests erzeugen echte Bundleartefakte aus einem echten
Git-Commit. Sie prüfen Python-Aufrufe, Nix-, JS-, Schema-, Markdown- und lokale
Actions-Beziehungen sowie S0-Aufrufe. Die YAML-Anker-Blockscalar-Regression wird
durch die veröffentlichte Projektion mitgeprüft. Nach Entfernung des
ursprünglichen Checkouts liefert der Artefaktleser dieselbe Antwort.

Die Consumer-Negativfälle manipulieren tatsächlich registrierte Artefakte und
prüfen sowohl Hashabweichungen als auch nachgehashte semantische Widersprüche.
Reale Git-Paare belegen getrennte Identitäten, deterministische Wiederholung,
Dirty-/Historical-S0, Rename-/Delete-Lücken bei Budget 1, Ersatzobjekte,
ausführbare Filter und die unterschiedlichen Ausgabelimits.

## Grenzen und noch ausstehende Produktivabnahme

S1 bezeichnet eine bewiesene statische Beziehung nach den begrenzten
Producerregeln. Es beweist weder Runtime-Ausführung noch vollständige
Abhängigkeiten, Testabdeckung, Kausalität oder Mergeautorität. S0 und
Coverage-Lücken bleiben Teil der Antwort. Ein Contextbudget begrenzt die
Detailzeilen; Metadaten und Lückenzusammenfassungen werden separat ausgewiesen.

Ältere Bundles ohne optionale Beziehungsrolle bleiben lesbar und melden für
diese Abfrage fehlende Abdeckung. Ein unvollständiges vorhandenes
Architektur-/Entry-Point-Paar wird nicht überschrieben.

Vor dem Produktivabschluss sind nach dem regulären Review/Captain-Merge noch
die tatsächliche Generatoraktivierung, Veröffentlichung mit neuer
Generatoridentität, zwei unabhängige authentifizierte Agentenclients und der
bestehende authentifizierte Ereignisfluss am neuen Commit nachzuweisen.
