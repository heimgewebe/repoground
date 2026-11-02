# RepoGround S4 – vorabberechnete Cross-Repo-Flake-Belege im bestehenden Bundle

**Erhebungsstand:** 02.11.2026, Europe/Berlin. **Quellbasis:** RepoGround \`b45c9566cbfb280f114960200334ae3299d37670\` (S1 in main). S4 ist in diesem Arbeitsstand ein **getesteter Kandidat**, noch keine automatisch aktivierte Produktivfunktion.

## Ziel und Abgrenzung

Ein Agent soll eine revisionsgenaue Nix-Flake-Abhängigkeit aus **einem bereits veröffentlichten Manifest** abrufen können – ohne jedes Mal die Quell-Repositories, ihre Gitobjekte oder das Netzwerk öffnen zu müssen. Dafür wird die bestehende Flake-Git-Analyse \`flake_revision_relations\` **einmal während der normalen Fleet-Bundle-Erzeugung** angewendet.

Der vorhandene \`repoground-publish-fleet\` ist weiterhin der alleinige Scheduler, Writer und Publisher. Keine zweite Datenbank, Hintergrundaufgabe, FTS-Struktur oder ungesicherter Alias. Die Rolle \`flake_relation_evidence_json\` erhält den üblichen SHA-256-, Byte-, Profil-, Export- und Manifest-Vertrag und liegt in derselben immutablen Bundle-Generation.

Die Quellidentität wird an den tatsächlichen GitHub-Origin gebunden. Der Nixer-Zielcommit stammt aus \`flake.lock\`, **nicht** vom schwankenden Nixer-\`main\`. Fehlende Gitobjekte und nicht unterstützte dynamische Nix-Formen erscheinen als Lücken und werden nicht zu S1-Kanten befördert.

Ein bestehendes \`fleet-context\`-Bundle kann den Nachweis liefern, ein \`public-share\`-Profil schließt die neue Rolle aus. Abfragewege: \`federation flake-pack-manifest\` und die vorhandene MCP-Toolregistrierung mit \`get_flake_relation_evidence\`. Beide lesen nur verifizierte, persistierte Artefaktbytes. Der MCP-Weg verlangt den erwarteten Owner/Repo und den vollständigen Commit. Er öffnet weder Git noch Netzwerk noch baut er den Index erneut.

## Realer Git-Fall und Statusgrenzen

Der am selben Tag regulär veröffentlichte Heim-PC-Snapshot ist \`heimgewebe/heim-pc@ff991e7a2d0a98ab4bab849515e5344e224131cb\`, erstellt durch RepoGround-Generator \`b45c9566cbfb280f114960200334ae3299d37670\`. Der aktuelle Source-\`flake.nix\` und der innere \`nixos/system/flake.nix\` deklarieren beide den Nixer-Pin \`c252b62b0fcd0bd5442681bb68d809a4b5984c61\`. Nach gezieltem Abruf **nur dieses Gitobjektes** lieferte der produktive S1-Producer fünf belegte Deklarationskanten, \`status=ok\`, \`gaps=[]\`, SHA-256 \`d00cdb4bc2fccef76af27609ac8862883dfbdc56322e8948a6978a210882e569\`.

Die **Live-Quelle ist separat**: Großer Adler sah am 02.11.2026 um 10:30:57 UTC \`nixer-headless.service\` im **System**-Manager (\`active/running\`, PID 4413, Listener \`127.0.0.1:18187\`). Der Servicebefund hat keine vollständige Runtime-Commit-Identität. Frühere Build-Objekt-Belege verknüpften nur einzelne Quelldateien mit einem älteren Nixer-Pin \`6c1fae…\`. Weder der heutige Git-Pin \`c252b62…\` noch die fünf S1-Deklarationskanten beweisen, dass die tatsächlich aktivierte NixOS-Generation aus dieser Source-Version stammt.

Der historische S2-Fall ist ebenfalls eigenständig: Ein Heim-PC-Pinwechsel \`7ff110f...\` → \`12a8c6a...\` hatte vorübergehend einen äußeren neuen und einen inneren alten Nixer-Pin. Der S1-Producer verweigerte dort zu Recht die angeblich vollständig aufgelöste Modulbeziehung (\`inner_flake_input_unverified:nixer\`). Die neue S4-Rolle veröffentlicht **revisionsgenau den jeweiligen Stand**; sie konstruiert noch keine automatische, vollständige Veränderungsfolge über Commits.

## Reproduzierbare Tests

Lokale Quelle, 02.11.2026, mit dem Python-3.12-Releaseinterpreter und aktivem \`jsonschema\`:

\`\`\`bash
/home/alex/.local/share/repoground-runtime/current/.venv/bin/python \
  -m unittest -q tests.test_flake_evidence_pack tests.test_cross_repo_flake_relations

/nix/store/0zh3g7fz7h3nh34cnzda1dbvg0cgwfsy-ruff-0.16.6/bin/ruff \
  check --config ruff-ci.toml merger/repoground/core/flake_evidence_pack.py

python3 scripts/ci/check_graph_maintainability.py --root . --format json
\`\`\`

**Beobachtet:** 42 Testfälle erfolgreich (31 ursprüngliche Cross-Repo-Tests und 11 neue S4-Tests). Der tatsächliche End-to-End-Fixture-Pfad erzeugte über \`build_snapshot_create_result\` mit \`fleet-context\` ein vollständiges Bundle; Post-Emit-Health, Bundle-Schema, Exportgate und Snapshot-Finalisierung bestanden. Die eindeutige Flake-Rolle wurde in den veröffentlichten Manifestdaten wiedergefunden und beide Agentenwege lasen denselben SHA-256-geprüften Inhalt, während \`subprocess.run\` für Git ausdrücklich auf Fehler gestellt war. Die Gegenproben verweigerten falsche Source-Owners, SHA-/Commit-Änderungen, Symlinks und S1-Runtime-Behauptungen. Ruff und der graphische Komplexitäts-Ratchet bestanden.

## Vergleichbare Latenzmessung (kein Marketing-Quotient)

Messdatei: \`docs/retrieval/repoground-flake-evidence-measurement-20261102.json\`. Wiederholung mit \`python -m scripts.measure_flake_evidence\`, festen Source-/Target-Git-SHAs und demselben \`--samples\`-/\`--warmups\`-Vertrag. Die Messung nutzt denselben Prozess, dieselben Gitobjekte und abwechselnde Reihenfolge je Paar; jede Antwort wird auf **identischen Pack-SHA-256** geprüft.

| Zugriff (35 warm-cache-Anfragen, 4 Warmups) | Median | p95 |
|---|---:|---:|
| Git-only, vollständige revisionsgebundene Neuberechnung | 140,207 ms | 177,316 ms |
| Vorabberechnete JSON-Bytes, vollständig hashgeprüft, kein Git | 0,241 ms | 0,432 ms |

Das p95-Verhältnis der beiden **isolierten Datenzugriffe** betrug 410,454. **Nicht enthalten**: die einmalige Erstellung, die Fleet-Publikation, MCP-/CLI-Prozessstart und -Transport, tatsächliche Antworten eines KI-Agenten sowie NixOS-Build oder Runtimezugriff. Das ist ein praktischer Vorteil für häufig wiederkehrende, identische revisionsgebundene Fragen, keine pauschale Agentenbeschleunigung. Die Vergleichsreihe ist bewusst über die Zeit wiederholbar statt nur ein einmaliger Demo-Wert.

## Bestehender Veröffentlichungsweg und noch fehlende Abnahme

Nach regulärem PR-Merge: denselben immutable Release-/Canary-/Pointer-Aktivierungsweg wie S1 für den neuen Generator verwenden. Danach **nur** das Heim-PC-Fleetbundle über den bestehenden Publisher bei geänderter Generatoridentität erneuern; Stable-Manifest, \`generator.runtime.git_commit\`, \`snapshot_provenance.repositories[*].git_commit\`, neue Artefaktrolle, Post-Emit-Health, echten MCP-/CLI-Packread und realen Nixer-Quell-Pin frisch kontrollieren. Die produktive Manifest-Abnahme ist **erst dann** erbracht.

Für den ursprünglichen Gesamtauftrag bleiben S2 automatische historische Folgen/Folgewirkungen, S3 vollständige Source-→Build-→Generation-Provenienz und ein Agenten-Wirkungsbenchmark gegen Git-only über denselben Aufgaben-Goldset separat offen. Unvollständigkeit ist hier eine belegte S0-Lücke und kein negativer Abhängigkeitsnachweis.
