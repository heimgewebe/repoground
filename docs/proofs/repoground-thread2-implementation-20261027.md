# RepoGround – Thread 2: revisionsgebundene Geschichte und Föderation

Implementierungsquelle: RepoGround main bf2ad72785c47ede4b8b94ce2215b07e4773877e; Planungsgrundlage: PR #1352, Head 88d161e4ac46e2e4a75af5bbd1cd761b937748a8.

## Datenmodell und Zuständigkeiten

- Der bestehende History Lens liest auf Nachfrage Git-Commit-, Tree- und Blob-Objekte, statt eine neue historische Datenbank zu unterhalten.
- Die bestehende Federation ergänzt ihre bisherige rein heuristische Gleichzeitigkeit von Suchtreffern durch getrennte gerichtete Belege. Die alte Federation-Index-Schnittstelle bleibt erhalten.
- Normative Mitgliedschaft stammt ausschließlich aus metarepo/fleet/repos.yml. fleet/repo-metadata.yml ist Zusatzinformation und sync/metarepo-sync.yml deklariert beabsichtigte Kopierwege.
- Jede Beziehung hat Quell- und Zielrepository, zwei vollständige Commit-SHAs, Artefaktpfad, Git-Blob-ID, Datei-SHA256 (sofern verfügbar) und Herkunftsklasse.
- Ein Fleet-Eintrag beweist keine Runtime-Abhängigkeit. Ein deklarierter Copy-Target beweist keine erfolgreiche Synchronisierung oder Ausrollung. fleet:false gegenüber normativer Mitgliedschaft wird als Konflikt gezeigt.
- Externe Ereignisreferenzen (PR, CI, Test, Chronik, Operator-Receipt) werden nur aus explizit mitgelieferten, beschränkten Referenzen und exakten Git-SHAs gebunden; Quellidentität, Ergebnis und Kausalität werden nicht hinzugedichtet.

## Öffentliche read-only Befehle

Alle Git-Revisionen müssen vollständige 40- bzw. 64-stellige kleingeschriebene Hashes sein. Die folgenden Beispiele funktionieren bei lokal vorhandenen Git-Objekten:

    repoground federation revision --repo-root /home/alex/repos/repoground --repo-id repoground --commit dc4e0e6c5897c108933cc575eb2b3372329fb616
    repoground federation delta --repo-root /home/alex/repos/repoground --repo-id repoground --base dc4e0e6c5897c108933cc575eb2b3372329fb616 --head 274274ded84a94bc4c0af6a525b3485ba17e3b79
    repoground federation path-history --repo-root /home/alex/repos/repoground --repo-id repoground --commit bf2ad72785c47ede4b8b94ce2215b07e4773877e --path docs/roadmap/repoground-vision-and-agent-adoption.md
    repoground federation relations --metarepo-root /home/alex/repos/metarepo --metarepo-commit 0d27ec763c6e2b4973df8c065950c8b2734414d2 --target heim-pc=/home/alex/repos/heim-pc@34bfa51c80c1dedac1dd38ce48ef687d5ee778e3
    repoground federation relation-delta --metarepo-root /home/alex/repos/metarepo --base-metarepo-commit 0d27ec763c6e2b4973df8c065950c8b2734414d2 --head-metarepo-commit 0d27ec763c6e2b4973df8c065950c8b2734414d2 --target-before heim-pc=/home/alex/repos/heim-pc@34bfa51c80c1dedac1dd38ce48ef687d5ee778e3 --target-after heim-pc=/home/alex/repos/heim-pc@34bfa51c80c1dedac1dd38ce48ef687d5ee778e3

Programmgesteuerte Aufrufe: core.history_lens.git_revision_view / git_revision_delta / git_path_history / bind_external_history und retrieval.federation_query.query_federation_relations. Neue JSON-Schemata federation-timeline.v1 und federation-relation-evidence.v1. Für externe Belege zusätzlich federation history-events mit --events-json (JSON-Liste expliziter externer Nachweise; keine versteckte API-Abfrage).

## Drei echte RepoGround-Revisionen

| Revision | Commit | Nachweis |
| --- | --- | --- |
| A | dc4e0e6c5897c108933cc575eb2b3372329fb616 | Git-Baum vorhanden |
| B | 274274ded84a94bc4c0af6a525b3485ba17e3b79 | Gegenüber A eine hinzugefügte Datei |
| C | bf2ad72785c47ede4b8b94ce2215b07e4773877e | Gegenüber B fünf geänderte Dateien |

A→B: docs/proofs/external-agent-usage-review-20261027.md hinzugefügt. B→C: AGENTS.md, README.md, docs/roadmap.md und docs/roadmap/repoground-master-roadmap.md verändert; docs/roadmap/repoground-vision-and-agent-adoption.md hinzugefügt. Git-Blob-IDs und beide SHAs liegen in der Delta-Antwort. Der Reader ordnet weder Urheberschuld noch Ereigniskausalität zu.

## Zwei tatsächlich getrennte Repository-SHAs

- Metarepo: 0d27ec763c6e2b4973df8c065950c8b2734414d2.
- Heim-PC: 34bfa51c80c1dedac1dd38ce48ef687d5ee778e3.
- fleet/repos.yml erklärt heim-pc zum Core-Fleet-Mitglied. Für drei im sync/metarepo-sync.yml deklarierte, auf beiden Git-Ständen vorhandene Ziel-Dateien wurden abweichende Inhalts-SHA256s gemessen. Status: diverged_at_revisions, nicht etwa successful_sync oder aktuelle Deployment-Drift.
- Die Zielrepo-ID ist eine vom autorisierten Aufrufer gelieferte Bindung zu einem lokalen Git-Root, kein über Remote-Server beglaubigter Repositoryname. Ein unabhängiger Nachweis kann das Git-Remote/Repo-Identity zusätzlich überprüfen.

## Föderations-Kantenänderungen

Die neue read-only Operation relation-delta vergleicht für **beide Beobachtungszeitpunkte** je einen vollständigen Metarepo-Commit und einen vollständigen Git-Commit pro betroffenem Repository. Nur vollständig gelesene Manifest-Stände dürfen eingeführte und entfernte Beziehungen behaupten; bei einem nicht lesbaren Quellstand bleibt das Ergebnis partial ohne scheinbare Löschungen. Eine vollständig lesbare normative Fleet-Liste belegt dagegen ausdrücklich, dass ein früheres Mitglied heute in der gewählten Quellrevision fehlt.

Die Vergleichsfunktion verwendet keinen zusätzlichen Index: Vorher und Nachher werden durch fleet_revision_relations gelesen und anhand stabiler gerichteter Kanten zu introduced, removed und modified verglichen. Eine Änderung an fremden Fleet-Mitgliedern darf keinen geänderten Beziehungseintrag für heim-pc erzeugen. Der neue Contract erweitert federation-relation-evidence.v1 um relation_deltas und die exakten SHA-Referenzen. Unterschiedliche Git-SHAs allein belegen noch keine materielle Beziehungänderung.
## Unsicherheit, Grenzen, Sicherheit

- source_commit ist die verifizierte Git-Revisionsidentität. committer_time_reported ist die im Git-Objekt behauptete Zeit; observation_time und publication_time bleiben bei rein deterministischen Reads null. Ein später erfasster PR oder Test verändert nicht das früher entstandene Git-Objekt.
- Teilabdeckung erscheint als partial oder unverfügbar/gaps. Antworten sind begrenzt: Git-Baum 4096 gelesene Blobs, 256 öffentlich ausgegebene Dateizeilen, Python-AST 20 Dateien, externe Events 100.
- Kein Symlink-Traversal und kein Einlesen von Geheimnissen aus dem laufenden Arbeitsverzeichnis; Git-Blob-Inhalte werden für AST nur transient analysiert und nicht ausgegeben. Ohne Git-Objekt/Commit wird nichts angenommen.
- In diesem Beitrag keine vollständige dynamische Callgraph-, Import-, Testlauf- oder Runtime-Kausalitätsanalyse. Symbol-Deltas aus Python-AST sind vorläufige Diagnose und ersetzen den Strukturgraphen von Thread 1 nicht.
- Kein Fetch, Checkout, Publish oder Neubau einer Bundle-Generation bei Reads. Geschriebene Snapshots und Generationen bleiben unverändert.
- PyYAML safe_load folgt der SafeLoader-Anleitung aus Context7 /yaml/pyyaml; es verhindert Python-Objektkonstruktoren, garantiert aber weder Gültigkeit des Fleet-Vertrags noch Ressourcenschutz gegen absurd große YAML-Strukturen (darum Byte-Limit).
- Tests: merger/repoground/tests/test_history_lens_temporal.py, test_federation_relations.py und test_federation_timeline.py. Prüfen 3 echte Git-Commits in einem isolierten Fixture, zwei echte Repo-Objektbäume, negative SHA-/Pfadtests und deterministische Wiederholungen.

## Übergabe an Thread 3

Thread 3 darf die neuen read-only CLI/API-Methoden in Evidence Packs und MCP integrieren, ohne die bestehenden Dateien core/mcp_tools.py, cli/mcp_stdio.py oder core/context_compiler.py aus diesem Thread heraus zu verändern. Dabei SHA, status, source_type, gaps und does_not_establish unverändert weitergeben. Externe PR/CI/Chronik/Operator-Receipts sind nur per expliziter autorisierter Leseoberfläche aufzunehmen.

CI, Review und regulärer Merge sind eigene revisionsgebundene Gates. Ein Grün einer alten PR oder ein lokaler Beispielaufruf ersetzt nicht die Prüfung der veröffentlichten Implementierung.

## P1/P2-Reviewhärtung für PR #1355

Das revisionsgebundene Codex-Review am Head \`82c92db03f7a52973f03c2300dbe98d24a9e0d68\` ergab konkrete Gegenbeispiele; für den nachfolgenden Korrekturstand wurden diese ohne neue persistente Datenbank und ohne Änderungen an Thread 1 oder 3 behoben:

- Der gemeinsame Git-Reader setzt \`GIT_NO_LAZY_FETCH=1\`: In einem echten \`blob:none\`-Teilklon können fehlende Objekte daher nicht automatisch vom Promisor-Remote nachgeladen werden. Der Test benutzt ein lokal gefiltertes Repository, kappt dessen Remote und bestätigt \`partial\` ohne zusätzliche Packdateien.
- Für Git-Historienpfade gilt \`GIT_LITERAL_PATHSPECS=1\`. Insbesondere \`a[1].py\` darf nicht fälschlich Ereignisse von \`a1.py\` übernehmen. Der Negativtest bindet ausdrücklich eine fremde CI-Referenz und weist deren vermeintliche Dateihistorie zurück.
- Git-Bäume erhalten die Dateimodi der Blobs. \`100644\` → \`100755\` wird auch bei identischem Blob-OID als nachgewiesene Modusänderung gemeldet; der neue, abwärtskompatible Wert \`git_tree_mode_comparison\` steht im JSON-Vertrag.
- Ein im Git-Baum vorhandenes, aufgrund der Bytegrenze oder eines fehlenden Objekts nicht lesbares Sync-Ziel wird mit \`sync_target_unavailable\` als Lücke gemeldet. Die Folgeabfrage darf daraus keine entfernte Beziehung folgern.
- Bei mehr als acht Sync-Zielen und bei vorhandenen, aber nicht lesbaren Metadaten verbleiben \`sync_targets_capped\` bzw. \`fleet_metadata_unavailable\` und ein \`partial\`-Status. Ein unvollständiger Stand kann damit keine scheinbare Relation-Löschung begründen.

Der gemeinsame Federation-/History-/Delta-/API-Testlauf erreichte anschließend **135 bestandene Tests** (NixOS Python 3.12); Ruff und das bestehende Maintainability-Ratchet waren erfolgreich. Diese lokalen Befunde gelten für die jeweils getesteten Dateien; GitHub-CI und die reguläre Captain-Integration müssen zusätzlich am publizierten Head bestätigt werden.
