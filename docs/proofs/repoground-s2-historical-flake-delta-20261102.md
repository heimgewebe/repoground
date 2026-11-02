# RepoGround S2 – Git-gebundener Flake-Änderungsnachweis

**Prüfung:** 2. November 2026. **Implementierungsbasis:** RepoGround `7d299a7d1248a22263e176a7f7c5182a2ad57ba2`.
**Status:** In isolierter Grabowski-Work-Lane implementiert und lokal verifiziert. Dieses Dokument behauptet weder GitHub-Merge noch Generatoraktivierung oder Fleet-Publikation.

## Verhaltensvertrag

`federation flake-relation-delta` ruft für zwei volle, exakt gebundene Heim-PC-Git-SHAs den bestehenden S1-Produzenten `flake_revision_relations` auf, ergänzt den existierenden `git_revision_delta` mit Pfaden und Git-Blob-OIDs und vergleicht semantische Beziehungen. Deterministische JSON-Ausgabe führt `source_repo`, Basis-/Zielcommit, explizite Target-Pins, beide S1-Evidenzdigests, direkten Git-Dateidelta, Zeilen-/Blob-Belege, Kantenübergänge, Gaps und einen SHA-256-Digest.

Da S1 ausdrücklich **keine vollständige Eingabe-/Relationsabdeckung** zusichert, ist auch `gaps=[]` kein Beweis für die Nicht-Existenz einer Beziehung. Nicht mehr beobachtete Kanten heißen deshalb stets `unverified`, erstmals beobachtete `newly_verified`; ihr fehlender positiver Abdeckungsnachweis erzeugt `relation_absence_not_proven`. Nur auf beiden Revisionen erkannte, belegte Relationen können `changed` sein. Es gibt hier **keinen** automatisch behaupteten `removed`- oder `added`-Relationsübergang. Eine unabhängig beobachtete Änderung der Git-Quelldateien bleibt weiterhin ein echter `git_revision_delta`-Befund. Direkte Quellveränderungen und nur vermutete transitive Auswirkungen bleiben strikt getrennt (`transitive_impacts=[]`). S2 ist keine Aussage über Build, aktivierte Generation oder laufenden Dienst.

## Echtes historisches Goldset

- Quelle: `heimgewebe/heim-pc`
- Basis: `7ff110f9dc2c561ca9bb525edb4d4b41a3796bfe`
- Ziel: `12a8c6af34e5aedfa98f795c1261c782f97731d8`
- Nixer vor Änderung: `f66d0a38ef3c75833fa20db8aa6bd9202c9608a5`
- Nixer danach: `6c1fae3936e441c43d19a7924f2f26f3539fb1d3`

Wiederholung im RepoGround-Root (vollständige lokale Gitobjekte vorausgesetzt):

```bash
python -m merger.repoground.cli.main federation flake-relation-delta \
  --repo-root /home/alex/repos/heim-pc --repo-id heimgewebe/heim-pc \
  --base 7ff110f9dc2c561ca9bb525edb4d4b41a3796bfe \
  --head 12a8c6af34e5aedfa98f795c1261c782f97731d8 \
  --target-before heimgewebe/nixer=/home/alex/repos/nixer@f66d0a38ef3c75833fa20db8aa6bd9202c9608a5 \
  --target-after heimgewebe/nixer=/home/alex/repos/nixer@6c1fae3936e441c43d19a7924f2f26f3539fb1d3
```

**Frisch beobachtet:** `status=partial`, `head_gaps=["inner_flake_input_unverified:nixer"]`, exakt die direkten Dateien `flake.lock` und `flake.nix` verändert. Eine `flake_pinned_input`-Beziehung trägt `changed`; Modulbindung, lokale Moduleinbindung und zwei deklarierte Dienste tragen `unverified`. Kein `removed`-Übergang. Ergebnis-Digest: `379cd0e6374ae20f90bc18b830248006305ac43fdd70e84792342efc1792ec01`.

Die automatisierte Antwort ist somit: Der äußere Nixer-Pin wurde geändert, der innere blieb zunächst widersprüchlich; eine vollständig belegte Modulbindung kann für diese Revision **nicht** bestätigt werden. Aus diesem Git-Befund folgt keine produktive Laufzeitversion.


## Unabhängiger realer S2-Fall: Metarepo-Kopiervertrag → RepoGround

Der bereits bestehende Produzent \`federation relation-delta\` wurde unabhängig von Nixer und ohne neue Architektur an tatsächlich verschiedenen RepoGround-Revisionen aufgerufen:

- Metarepo-Quelle, beide Seiten: \`heimgewebe/metarepo@c1ac04fec54de590eda209b916f81c4ce8eb363a\`
- RepoGround-Ziel vor Änderung: \`70a481fec04370cee06bd62ba1c3fe135183f14e\`
- RepoGround-Ziel nach Änderung: \`520199e2727fab11aae080ad81837d283e60e3f8\`
- Deklarierter Vertrag: \`sync/metarepo-sync.yml\` → \`.github/workflows/wgx-guard.yml\`

Der echte CLI-Lauf lieferte \`status=ok\`, \`gaps=[]\` und genau **eine** \`relation_deltas[].transition=modified\`-Beziehung vom Typ \`declared_copy_target\`. Die Git-gebundenen SHA-256-Quellbytes am Ziel wechselten von \`9cb7c5b0579d2b022fc68c926cd6e04695a09eb5441a6e716376b3640c192695\` auf \`8cdaec478de624bd59a7bec17cedb56c369376c18d69f86ab5c25444af28232b\`. **Dies ist eine Änderung des Zielinhalts innerhalb eines deklarierten Kopiervertrags, kein Beweis einer erfolgten Synchronisierung oder Runtime-Auswirkung.**

Wiederholung:

\`\`\`bash
python3 -m merger.repoground.cli.main federation relation-delta \
  --metarepo-root /home/alex/repos/metarepo \
  --base-metarepo-commit c1ac04fec54de590eda209b916f81c4ce8eb363a \
  --head-metarepo-commit c1ac04fec54de590eda209b916f81c4ce8eb363a \
  --target-before repoground=/home/alex/repos/repoground@70a481fec04370cee06bd62ba1c3fe135183f14e \
  --target-after repoground=/home/alex/repos/repoground@520199e2727fab11aae080ad81837d283e60e3f8
\`\`\`

Dieser reale Vergleich nutzt die schon vorhandene allgemeine \`relation-delta\`-Funktion; der neue \`flake-relation-delta\`-Aufruf deckt den Nixer-Fall ab. Die Fälle prüfen unterschiedliche Relationstypen und dürfen nicht als gleichartige Flake-Kanten statistisch vermengt werden.

## Gegenproben, Prüfungen und Grenzen

`merger.repoground.tests.test_flake_relation_delta`: gezielte Tests für stabile Revision, widersprüchliche innere Flake, konsistenten Pinwechsel, syntaktisch entferntes Dienst-Attribut ohne bewiesene relationale Löschung, **gültige mehrzeilige Nix-URL ohne fälschliches `removed`**, fehlendes Ziel-Gitobjekt und CLI-SHA-Validierung. Der andere, unabhängige Repo-Vertrag ist bereits über die vorhandene Metarepo-`relation-delta`-Fixture abgedeckt, muss aber in einem vollständigen Agenten-Goldset gesondert gemessen werden.

Ruff mit `ruff-ci.toml`: PASS. Der Graph-Komplexitäts-Ratchet meldete nach einem gezielten CLI-Refactoring **PASS** mit explizit im PATH bereitgestelltem Ruff. Die kombinierte S1-/S4-/S2-Unittest-Suite bestand mit **51/51** Tests. Vollständige GitHub-CI-/PR-/Bundle-Abnahme ist weiterhin gesondert erforderlich.

**Grenze:** Die revisionsgebundene Analyse liest bei dieser Ausführung weiterhin Git. Sie ist noch nicht als neues S2-Bundle-Artefakt vorab berechnet; S4 bleibt die bestehende, unverändert produktive S1-Beziehungsrolle. Der Übergang von Gitdeklaration zu Nix-Derivation/Systemgeneration/Prozess gehört ausdrücklich zu S3.