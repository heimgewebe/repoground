# AUSFÜHRUNGSAUFTRAG 2/3 – Föderation und technische Zeitgeschichte

**Priorität:** P0 Ausbau · **Projekt:** [RepoGround](https://github.com/heimgewebe/repoground) · **Programm:** [massiver Ausbau](repoground-massive-expansion-program.md) · **Stand:** 27.10.2026

**Direkt kopierbare Anweisung für einen eigenen ausführenden ChatGPT-Thread.** Implementierung, PRs und Tests statt einer weiteren Vision. Der Nutzer wünscht einen **massiven Ausbau vor der Gesamt-Nutzenbewertung**.

**Alleiniger Writer/Integrator:** Grabowski im eigenen, mit Leases abgesicherten Worktree. Großer Adler nur unabhängige read-only Beobachtung; Gegner bei wesentlichen Prämissen frühzeitig als Same-Thread-Gegenprobe, nicht als Reviewer oder Evidenzquelle; Nixer nur für Nixfragen. RepoGround bleibt ein deterministischer, grundsätzlich lesender Analyse-Layer, kein Agent.

## 0. Verifizierter Ausgangspunkt

- Live-`main`/GitHub, vorhandene Bundles/Fleet, offene PRs, Leases, CI und Runtime vor Codeänderungen lesen; nicht auf die historische Momentaufnahme vertrauen.
- Bestehende Teile wiederverwenden: `merger/repoground/core/federation.py`, `merger/repoground/retrieval/federation_query.py`, `merger/repoground/cli/cmd_federation.py`, `merger/repoground/core/history_lens.py`, `merger/repoground/retrieval/incremental_snapshot.py` sowie vorhandene Föderations-/Delta-/History-Verträge und Tests.
- Metarepo-Quellen korrekt binden: `fleet/repos.yml` entscheidet normative Fleet-Mitgliedschaft, `fleet/repo-metadata.yml` enthält Zusatz-/Beziehungsmetadaten; generiertes `repos.yml` ist keine autoritative neue Quelle. Related und `fleet: false` respektieren.
- Keine neue zentrale Datenbank oder ein heimlicher externer Mirror. Die vorhandene Veröffentlichung und die zuständigen Primärsysteme haben Vorrang.

## 1. Echte temporale Historie (RG-XH-01)

- Revisionsadressierbare Knoten/Kanten oder begrenzte Zeitdeltas aus vorhandenen Git-/Bundle-Generationen gewinnen. Exakt unterscheiden: **Quellrevision**, **Ereigniszeit** und **Zeitpunkt der Beobachtung/Publikation**. Nachträgliche Erfassung ändert kein früheres Ereignis.
- Deltas umfassen hinzugefügte/entfernte/geänderte Symbole, Contract-/Config-Referenzen, abweichende Abhängigkeitsauflösungen und relevante Regressionsergebnisse, soweit Primärbelege existieren.
- Ansichten: „Was galt zum Commit X?“, „Was veränderte sich zwischen X und Y?“, „Welche früheren Änderungen betrafen diese Quelle/Relation?“, „Welcher Test belegte was und zu welchem SHA?“.
- Nutzbar auch bei fehlender Zwischenrevision, geändertem Manifest oder veraltetem Bundle: `partial/stale/unavailable/ambiguous` explizit. Keine erfundenen Ereigniszeitpunkte oder behauptete Kausalität.
- Test mit mindestens drei historischen echten Commits aus einem Heimgewebe-Repo; wiederholte Anfragen und Rebuilds deterministisch, ältere Generationen unbeschädigt.

## 2. Belastbare Cross-Repo-Relationen (RG-XF-01)

- Fleet, deklarierte Contracts, API-/Schema-Referenzen, nachweisbare Konfigurations-/Service-Beziehungen und explizite Import-/Publikationsadressen zu **gerichteten** repositoryübergreifenden Kanten verbinden.
- Auf beiden Seiten **Repo-ID, Commit, Quellrange/Artefaktdigest und Herkunftstyp** festhalten. Zwei Dateien mit ähnlichem Namen sind kein API-Vertrag. Ein Fleet-„related“ ist keine Laufzeitabhängigkeit.
- Relevante echte Repo-Beispiele: `metarepo ↔ grabowski/heim-pc` für belegte Verträge/Metadaten; weitere Paare erst anhand der tatsächlich gefundenen Quellbelege. Nicht vorhandene/ungültige Quellen nicht „reparieren“, indem man Beziehungen erfindet.
- Version-, Konflikt- und Richtungslogik: mehrere Produzenten, abweichende Branchstände, umbenannte Contracts, fehlende Gegenstelle, freigegebene vs. unveröffentlichte Änderung separat darstellen.
- Ergebnis: einzelne reproduzierbare Cross-Repo-Abfrage und ein gebundener Veränderungsfall mit **mindestens zwei Repository-SHAs**, Quellbelegen und sichtbarer Nichtabdeckung.

## 3. Externe technische Vorgeschichte und Konflikte (RG-XF-02)

- Bereits bestehende Chronik-/GitHub-/CI-/Grabowski-Belege **nur über explizite, autorisierte read-only Schnittstellen** referenzieren. Keine ungeprüften Volltext-Kopien, Credentials, Betriebsgeheimnisse oder automatischen Produktivitätsannahmen.
- Unterschiedliche Ereignisquellen separat ausweisen: Commit/PR, CI-Lauf, bekannte Regression, Operator-Receipt und möglicherweise Runtime-Snapshot. Primärquelle bleibt autoritativ.
- Unzuverlässige Quellen, widersprüchliche Kanten, fehlende Permission oder Zeitsprünge werden als Lücken behandelt. Die bloße chronologische Nachbarschaft zweier Ereignisse ist keine Kausalbeziehung.
- Inkrementelle Erneuerung benutzt bestehende Bundle-Generationen/Watcher und erhält frühere gültige Generationen atomar. Read-Aufruf baut keine Snapshots und aktualisiert keine Git-Repositories.

## 4. Parallelarbeit ohne Konflikte

**Primäre Schreibflächen:** `core/federation.py`, `retrieval/federation_query.py`, `cli/cmd_federation.py`, `core/history_lens.py`, passende neue `contracts/federation-*`/`history-*` und `tests/test_federation*`/`test_history_lens.py`. Eigene Unterverzeichnisse bei Bedarf.

**Nicht in dieser Lane bearbeiten:** Graph-/Call-/Impact-Implementierung von Thread 1; `core/mcp_tools.py`, `cli/mcp_stdio.py`, `core/context_compiler.py` und Agenten-Routing von Thread 3. Für Querschnitts- oder öffentliche API-Schnittstellen ein kleines versioniertes internes Beispiel mit genauem Producer/Consumer vereinbaren; die Frontdoor verdrahtet Thread 3. Keine fremden Repoquellen editieren, sondern korrekt lesen.

## 5. Abarbeitung und harte Testanforderungen

1. Source of Truth und vorhandene Implementierungen unterscheiden; maximal drei aktuelle Defizite auswählen, direkt mit Code beginnen.
2. Erst historische Revisionsabfrage im vorhandenen History-Pfad implementieren und testen; dann zwei-repository-Relation aus echten Quellen; dann externen Provenienzpfad und Aktualisierungslogik.
3. Je PR einen echten historischen oder Cross-Repo-Fall sowie Negativtests mit ungültigem Commit, unaufgelöster Beziehung, Veraltung und abweichendem SHA.
4. Determinismus, Revisionstreue, absolute Pfad-/Symlink-/Secret-Sicherheit, begrenzte Payloads, Fallback und CI mitprüfen.
5. Reguläre Grabowski/Captain-Publikation und Merge-Gates benutzen; Main-/Produktivstand nach jedem Merge frisch lesen.
6. Unabhängige Epics bei Blockern anderer Lanes weiterbearbeiten. Keine Wartepflicht bis zum Gesamtnutzenbenchmark.

**Fertig:** echte integrierte Funktionen mit reproduzierbarer Vergangenheit- und Cross-Repo-Abfrage, mindestens einem realen mehrrevisionären und einem zweirepositorischen Nachweis, transparenten Lücken, CI und genauer Integrationsübergabe an Thread 3. Der spätere systemweite Nutzenvergleich ist **keine** Startvoraussetzung.

**Übergabe:** veröffentlichte Vertragsversionen, genaue Input-/Output-Fixtures und SHA, geprüfte Quellen, offene Coverage-Grenzen, PR-/Merge-Receipts und konkreter Frontdoor-Anschlussbedarf.
