# RepoGround – Nutzwert- und Chancenbewertung (02.11.2026)

**Art:** datierte Einschätzung durch einen Coding-Agenten (Claude Code), kein Proof, keine Roadmap-Entscheidung und kein Ersatz für die [Stop-/Fortsetzungsregeln](../roadmap/repoground-agent-tool-selection-plan.md#r5--zwei-nutzwertversuche-und-stopentscheidung-01112026) oder das [Ausbauprogramm](../roadmap/repoground-massive-expansion-program.md).
**Gebunden an:** `heimgewebe/repoground@7d299a7d1248a22263e176a7f7c5182a2ad57ba2` (main), MCP-Bundlekatalog unter `manifest-publications/bundles` zum Lesezeitpunkt. Alle Zahlen sind Momentaufnahmen und vor Wiederverwendung an den Primärquellen neu zu prüfen.

## Kurzfazit

Als **allgemeiner Beschleuniger für Coding-Agenten** hilft RepoGround nicht. Das zeigt die eigene R5-Messung, und die Stichproben unten passen dazu. Stark ist RepoGround bei einer anderen Frage: **Was hängt über Repo-Grenzen hinweg zusammen, in welcher Version, und was ist geplant, gebaut oder läuft tatsächlich?** Diese Frage beantwortet Git allein nur mühsam. Dort liegt das Ausbaupotenzial.

## 1. Ausgangslage

- **Umfang** (lokal gezählt): etwa 280.000 Zeilen Python unter `merger/`, 419 Testdateien, 13 Werkzeuge über MCP. Im Katalog liegen 41 veröffentlichte Bundles mit rund 11 GB.
- **Sorgfalt bei Belegen:** Jede Aussage ist an einen Commit gebunden, hat Datei, Zeilen und Prüfsumme und sagt ausdrücklich, was sie *nicht* beweist (`does_not_establish`).
- **Gemessene Studie R5** (siehe [Studienregister](repoground-agent-study-history.md)): Mit Pflichtnutzung (Arm B) brauchten die Agenten pro Aufgabe etwa 9,7 Sekunden länger und etwa 59 % mehr Input-Tokens als ohne RepoGround (Arm A). Die Qualität war nicht besser. Durften sie selbst wählen (Arm C), haben sie RepoGround nie benutzt. Die Stoppentscheidung für den allgemeinen Suchbeschleuniger bleibt richtig.

## 2. Live getestet über MCP

| Werkzeug | Ergebnis |
| --- | --- |
| `get_flake_relation_evidence` (heim-pc@`78795312…` → nixer) | **Sehr gut.** heim-pc pinnt nixer@`c252b62b…`, bindet das Modul in `nixos/system/flake.nix:41` ein und deklariert `services.nixer` (`nixos/system/modules/nixer.nix:46`) sowie `systemd.user.services.nixer` (Zeile 69). Jede Kante trägt Blob-OID, SHA256 und S1. `asserts_runtime_dependency=false` ist korrekt ausgewiesen. |
| Git-Gegenprobe zum selben Fall | Der Pin `c252b62b…` liegt **8 Commits vor** dem lokalen nixer-Checkout `c0e254fd…` (Stand 22.10.). Das veröffentlichte heim-pc-Bundle liegt **16 Commits hinter** dem lokalen heim-pc-HEAD `f39d564`. Genau solche Abweichungen sollte RepoGround künftig selbst melden. |
| `get_callers` (`read_flake_evidence_from_manifest`) | **Richtig:** 3 Aufrufer, dieselben wie mit grep. Die Antwort war aber etwa 4 KB groß für 3 Treffer. Nur 26,2 % der Python-Aufrufkanten sind aufgelöst (25.046 von 95.626), deshalb meldet das Werkzeug alle Profile (`review`, `change_impact`, `find_relevant_tests`, …) selbst als `insufficient`. |
| `get_callers` mit nicht existierendem Symbol | Sauberer Fehler `symbol_not_found`, es werden keine Aufrufer erfunden. |
| `bundle_discover` | Etwa 20 KB Antwort mit 41 Einträgen, darunter bis zu 3 Bundles für denselben Commit. Das trägt vermutlich zum Token-Mehrverbrauch in R5 bei; belegt ist das nicht. |
| `live_freshness` | Liefert immer `not_comparable` mit `repo_root_not_configured`, weil der registrierte MCP-Server ohne `--repo-root` läuft. Die Prüfung, ob ein Bundle aktuell ist, bleibt im Alltag damit wirkungslos. |

## 3. Wo die großen Chancen liegen

Die Reihenfolge entspricht der erwarteten Hebelwirkung. Jeder Punkt ist eine **Hypothese** und braucht vor einer Nutzenaussage die Abnahme nach Abschnitt 7.4 des Ausbauprogramms.

1. **Abweichungen zwischen geplant, gebaut und laufend erkennen.** Für jeden Host eine Kette: deklarierter Pin → Lockdatei → Build → aktive NixOS-Generation → laufender Dienst. Daraus ein täglicher Bericht, etwa: „heim-pc pinnt nixer X, aktiv ist Y, der lokale Checkout steht auf Z.“ Der nixer-Fall oben ist dafür ein kleines, echtes Beispiel. Das entspricht den Schritten S1–S3.
2. **Folgen einer Vertragsänderung über alle Repos.** Ein PR in `contracts-mirror` oder `metarepo` zeigt automatisch, welche Repos den Vertrag erzeugen, welche ihn nutzen und wo veraltete Bezüge stehen, jeweils mit Commit-Angabe. Git schafft das nur Repo für Repo.
3. **Prüfung von Agenten-Aussagen.** `grounding_verify` könnte zum festen Schritt vor einem Review werden. Jede Aussage von Grabowski, Codex oder Claude bräuchte dann einen Beleg mit Commit und Zeilen, sonst wird sie markiert. Hier zählt die Determinismus-Stärke am meisten. Das Werkzeug muss Agenten dafür nicht schneller machen, nur ehrlicher.
4. **Zeitreise durch die ganze Flotte.** „Wie sah das System am Tag X aus, und was hat sich bis zum Ausfall geändert?“ Zusammen mit der Chronik wird daraus eine belegte Zeitleiste für die Fehlersuche, ohne erfundene Ursachen.
5. **Fertige Belegpakete für PRs.** Beim Push erzeugt der Publisher ein kleines Paket mit Änderung, bekannten Aufrufern, Tests, Lücken und Folgen für andere Repos. Reviewer lesen es nur noch. Der Aufwand fällt einmal an, nicht bei jeder Agentenfrage. Das entspricht Schritt S4 und `change_evidence_pack`.
6. **Fremder Code in genau der eingesetzten Version.** Bibliotheken oder nixpkgs-Module offline lesen, und zwar im Stand aus der Lockdatei. Context7 und ähnliche Dokumentationsquellen liefern dagegen den aktuellen Stand, nicht die Version, die tatsächlich genutzt wird.
7. **Abgleich von Doku und Wirklichkeit.** Die Architekturtexte im `metarepo` behaupten Abhängigkeiten. RepoGround prüft, ob es dafür Belege gibt, und meldet Widersprüche oder fehlende Belege.

## 4. Was vorher passieren sollte

- **Discovery verkleinern:** pro Repo und Commit nur das neueste gesunde Bundle anzeigen und die Antwort kompakt halten. Gleichzeitig alte Bundles aufräumen (rund 11 GB, Dubletten pro Commit).
- **MCP mit Repo-Pfaden starten:** `--repo-root` setzen oder mehrere Repo-Pfade erlauben, damit `live_freshness` echte `fresh`/`stale`-Ergebnisse liefert.
- **Antworten kleiner machen:** Bei Graph-Reads standardmäßig eine knappe Form liefern und die wiederholten `does_not_establish`- und `mutation_boundary`-Blöcke einmal per Referenz statt mehrfach ausgeben.
- **Python-Aufrufgraph:** Entweder die Auflösung deutlich über 26 % bringen, zum Beispiel mit Typinferenz, oder Folgen-Aussagen bewusst auf die Bereiche beschränken, in denen RepoGround schon stark ist: Nix, Verträge, Konfiguration.
- **Fokus:** Abschnitt 7 des Ausbauprogramms (S1–S4) ist der richtige Weg. Noch enger gefasst: zwei bis drei Anwendungsfälle (Punkte 1–3 oben) mit echten Nutzern fertig bauen, statt mehr Parser zu schreiben. Bei rund 280.000 Zeilen für ein Hilfswerkzeug ist der Wartungsaufwand das größte Risiko.

## 5. Was diese Bewertung nicht belegt

Keine neue Agentenstudie, kein Wirkungsnachweis, keine Laufzeit- oder Build-Aussage über heim-pc oder nixer. Die lokalen Checkout-Stände wurden nicht gegen GitHub geprüft. Ob „8 Commits vor dem lokalen Checkout“ auch gegenüber dem Remote gilt, ist offen.
