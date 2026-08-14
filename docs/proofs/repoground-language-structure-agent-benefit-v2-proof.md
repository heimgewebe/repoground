# RepoGround language_structure Agent-Benefit Evidence v2

## Ausgangspunkt

T027 hat den bereits vorhandenen Rust-/Bash-`language_structure`-Sidecar in der internen Fleet-Publikation verfügbar gemacht, ohne ihn als globalen Default oder als automatische Consumer-Route zu aktivieren.

Der danach verbleibende Promotion-Vertrag war jedoch schwächer als die übrige Evidence-Kette: `decide_language_adapter_promotion()` akzeptierte ein extern geliefertes `agent_benefit`-Objekt, dessen Nutzenbeleg im Wesentlichen aus zwei aggregierten Erfolgsraten bestand. Quelle, Goldset und Fallzahl waren gebunden, aber die einzelnen Fallback-/Candidate-Ergebnisse waren nicht Bestandteil der Evidenz. Ein syntaktisch passendes Dokument konnte daher z. B. `0.7` gegen `0.8` behaupten, ohne die zehn zugrunde liegenden Paarbeobachtungen zu liefern.

Basis dieser Änderung ist RepoGround `daa8c53744c9963741426c7775d79bc1f0b9c766` (Merge von PR #1196).

## Entscheidung

Der Promotion-Pfad bleibt fail-closed und erhält eine neue, strengere Evidenzgrenze:

`language-structure-agent-benefit.v2`.

Für Dummies: Statt nur zu sagen „mit der Zusatzinformation war der Agent in 80 % der Fälle erfolgreich und ohne sie in 70 %“, muss die Messung nun jeden einzelnen Vergleichsfall liefern. RepoGround zählt die Erfolge anschließend selbst nach.

Ein gültiger Benefit-Beleg bindet mindestens:

- exakte Source-Revision;
- exakten Goldset-SHA-256;
- exakt dieselbe Fallmenge wie der Strukturbenchmark;
- pro Fall eine eindeutige `task_sha256`, also die Identität der verglichenen Agentenaufgabe; doppelte Task-Hashes werden abgelehnt, damit derselbe Testfall nicht mehrfach gewichtet werden kann;
- getrennte Fallback- und Candidate-Ergebnisse;
- mindestens eine gebundene Evidence-Referenz pro Ergebnis;
- identische Modell-, Prompt-, Budget-, Source- und Grader-Bedingungen;
- Hash-Identitäten für Modell, Harness, Umgebung und Grader;
- als einzige Treatment-Variable `language_structure_json`: Fallback ohne, Candidate mit Sidecar.

Die aggregierten Erfolgsraten, Candidate-Wins, Fallback-Wins und Ties werden aus diesen Paaren deterministisch neu berechnet. Ein mitgeliefertes Summary, das davon abweicht, wird abgelehnt.

## Promotion-Semantik

Der bestehende T021-Gate bleibt unverändert streng:

- Agent-Erfolgsdelta mindestens 5 Prozentpunkte;
- Symbol-Recall mindestens 0,8;
- Relations-Precision mindestens 0,9;
- Relations-Recall mindestens 0,8;
- Range-Recall mindestens 0,9;
- mindestens zwei True-Null-Fälle, alle sauber und ohne False Positives;
- deterministische semantische Projektion;
- erwartete Degradationen exakt;
- p95-Latenz höchstens 500 ms;
- Peak-Memory höchstens 64 MiB;
- maximales Einzelindex-Artefakt höchstens 16 MiB.

Auch wenn alles erfüllt ist, lautet das Ergebnis nur `eligible_for_explicit_promotion_review`. `default_promoted` bleibt immer `false`; eine tatsächliche Default-/Consumer-Änderung benötigt weiterhin eine separate geprüfte Entscheidung.

Legacy-v1-Dokumente mit bloßen aggregierten `fallback_success_rate`-/`candidate_success_rate`-Feldern werden nicht als Promotion-Beleg akzeptiert. Sie führen fail-closed zu `keep_optional` statt zu einer Hochstufung.

## Producer für externe Messungen

Das neue Modul

`merger.repoground.core.language_structure_agent_benefit`

kann aus einem revisionsgebundenen Benchmark-Report und einem extern erzeugten Paar-Receipt ein normalisiertes v2-Dokument erzeugen. Es führt selbst keine Agenten aus und bewertet keine freie Textantwort semantisch. Dadurch bleibt die Grenze klar: externe Ausführung/Grading liefert Primärevidenz; RepoGround bindet und aggregiert sie, erfindet sie aber nicht.

## Verifikation

Die fokussierten Tests decken insbesondere ab:

- gültigen Builder + Validator + JSON-Schema;
- deterministische Normalisierung auf Benchmark-Fallreihenfolge;
- fehlende oder doppelte Fall-IDs;
- fehlende Evidence-Referenzen;
- abweichende Treatment-Variable;
- ungleiche Modellbedingungen;
- Source-/Goldset-Mismatch;
- manipuliertes Summary;
- Ablehnung des alten aggregate-only-v1-Belegs;
- CLI-Erzeugung aus Benchmark + Pair-Receipt;
- den bestehenden Promotion-Pfad mit einem v2-Paarbeleg.

Der Graph-/Komplexitäts-Ratchet zeigte nach Einführung des neuen Moduls keine neue C901-Komplexitätsverletzung.

## Aktuell nicht belegt

Diese Änderung liefert **noch keinen real gemessenen Agentennutzen** von `language_structure`.

Es fehlt weiterhin eine echte, revisionsgebundene Serie gepaarter Agentenläufe mit denselben Aufgaben, demselben Modell, demselben Budget und demselben Grader, bei der ausschließlich das Vorhandensein des `language_structure_json`-Kontexts variiert. Bis solche Primärevidenz vorliegt, ist `keep_optional` die sachlich richtige Produktentscheidung.

Insbesondere etabliert dieses v2-Format nicht:

- Default-Aktivierung;
- allgemeine kausale Überlegenheit außerhalb der gebundenen Fälle;
- vollständige Rust-/Bash-Semantik;
- Qualität eines externen Graders allein aufgrund seiner Hash-Bindung;
- statistische Signifikanz einer späteren kleinen Stichprobe;
- Merge- oder Deployment-Reife ohne die üblichen RepoGround-Gates.
