# RepoGround language_structure Agent-Benefit Evidence v2

## Ausgangspunkt

T027 hat den bereits vorhandenen Rust-/Bash-`language_structure`-Sidecar in der internen Fleet-Publikation verfügbar gemacht, ohne ihn als globalen Default oder als automatische Consumer-Route zu aktivieren.

Der danach verbleibende Promotion-Vertrag war jedoch schwächer als die übrige Evidence-Kette: `decide_language_adapter_promotion()` akzeptierte ein extern geliefertes `agent_benefit`-Objekt, dessen Nutzenbeleg im Wesentlichen aus zwei aggregierten Erfolgsraten bestand. Quelle, Goldset und Fallzahl waren gebunden, aber die einzelnen Fallback-/Candidate-Ergebnisse waren nicht Bestandteil der Evidenz. Ein syntaktisch passendes Dokument konnte daher z. B. `0.7` gegen `0.8` behaupten, ohne die zugrunde liegenden Paarbeobachtungen zu liefern.

Basis dieser Änderung ist RepoGround `daa8c53744c9963741426c7775d79bc1f0b9c766` (Merge von PR #1196).

## Entscheidung

Der Promotion-Pfad bleibt fail-closed und erhält eine neue, strengere Evidenzgrenze:

`language-structure-agent-benefit.v2`.

Für Dummies: Früher hätte ein Ergebniszettel mit „70 % gegen 80 %“ als Nutzenbeleg ausreichen können. Jetzt braucht RepoGround für jeden Vergleich zwei nachvollziehbar zusammengehörige Laufbelege – einmal ohne und einmal mit dem Sidecar – plus einen Grader-Beleg. RepoGround prüft deren Bindungen und zählt die Erfolge anschließend selbst nach.

Ein gültiger Benefit-Beleg bindet mindestens:

- die exakte Source-Revision und den exakten Goldset-SHA-256 bereits im **eingehenden Paar-Receipt**; der Builder darf diese Identität nicht aus einem neueren Benchmark auf alte Laufdaten stempeln;
- exakt dieselbe Fallmenge wie der Strukturbenchmark;
- pro Fall eine eindeutige `task_sha256`; doppelte Task-Hashes werden abgelehnt, damit derselbe Testfall nicht mehrfach gewichtet werden kann;
- je Route einen eingebetteten Runner-Receipt und einen Grader-Receipt;
- Content-Adressierung des Runner-Receipts: der Grader nennt dessen SHA-256, RepoGround berechnet ihn aus den eingebetteten Bytes neu;
- Output-Bindung: der Grader muss exakt den Output-SHA-256 des zugehörigen Runner-Receipts bewerten;
- Source-, Goldset-, Task- und Route-Bindung in Runner **und** Grader;
- identische Modell-, Harness- und Umgebungsidentität;
- pro Fall identischen Prompt-, Budget- und Nicht-Treatment-Kontext zwischen Fallback und Candidate;
- denselben Grader und dieselbe Grader-Rubrik;
- als einzige Treatment-Variable `language_structure_json`: Fallback mit `treatment_artifact_sha256 = null`, Candidate mit exakt dem gebundenen Sidecar-SHA-256.

Der Caller liefert **kein akzeptiertes `success`-Boolean** im Paar-Receipt. `success` entsteht erst aus dem gebundenen Grader-Verdikt `pass|fail`. Im finalen v2-Dokument bleibt das Bool als kompakte Projektion enthalten, wird beim späteren Promotion-Readback aber erneut gegen den eingebetteten Grader geprüft.

Die aggregierten Erfolgsraten, Candidate-Wins, Fallback-Wins und Ties werden deterministisch aus diesen Paaren neu berechnet. Ein mitgeliefertes Summary, das davon abweicht, wird abgelehnt.

## Review-Härtung

Der erste PR-Stand enthielt bereits paarweise Fälle, hatte aber zwei reale Lücken. Die automatisierte PR-Prüfung hat sie korrekt als P1 markiert:

1. Das eingehende Paar-Receipt selbst trug Source-/Goldset-Bindung nicht. Dadurch hätten stabile Case-IDs alte Agentenläufe unter einem neueren Benchmark wiederverwenden können. Das ist jetzt blockiert.
2. Die erste Fassung akzeptierte pro Route ein behauptetes `success` plus beliebige nichtleere Evidence-Strings. Jetzt sind eingebettete Runner-/Grader-Receipts Pflicht; Runner-Inhalt, Runner-Hash, Output-Bindung und Grader-Verdikt werden strukturell gegengeprüft, und Erfolg wird aus dem Grader abgeleitet.

Wichtig bleibt eine epistemische Grenze: SHA-256 bindet Inhalt gegen nachträgliche Veränderung, attestiert aber nicht kryptographisch, dass ein externer Runner oder Grader ehrlich beziehungsweise unabhängig war. Deshalb ist `receipt_hashes_do_not_attest_runner_or_grader_honesty` eine verpflichtende Nichtaussage des Contracts.

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

kann aus einem revisionsgebundenen Benchmark-Report und extern erzeugten, eingebetteten Runner-/Grader-Paaren ein normalisiertes v2-Dokument erzeugen. Es führt selbst keine Agenten aus und bewertet keine freie Textantwort semantisch. Externe Ausführung und Grading liefern Primärevidenz; RepoGround prüft deren strukturelle und content-addressierte Bindung und aggregiert sie, erfindet aber kein Ergebnis.

Input bleibt begrenzt: maximal 256 Paarfälle und 4 MiB Eingabedokument. Diese Grenze ist eine Betriebsgrenze, kein statistisches Qualitätsurteil.

## Verifikation

Die fokussierten Tests decken insbesondere ab:

- gültigen Builder + Validator + JSON-Schema;
- deterministische Normalisierung auf Benchmark-Fallreihenfolge;
- fehlende oder doppelte Fall-IDs und doppelte Task-Hashes;
- Pair-Source-/Goldset-Mismatch gegen den Benchmark;
- manipulierte Runner-Receipts nach dem Grading;
- Grader-Output, der nicht zum Runner-Output passt;
- caller-assertiertes `success` im Pair-Input;
- Prompt-/Kontrollkontext-Drift zwischen Fallback und Candidate;
- falsches Treatment-Artefakt und Modellidentitätsdrift;
- manipuliertes Summary und manipulierte finale Success-Projektion;
- Ablehnung des alten aggregate-only-v1-Belegs;
- CLI-Erzeugung aus Benchmark + Receipt-Paaren;
- den bestehenden Promotion-Pfad mit einem v2-Paarbeleg.

Der Graph-/Komplexitäts-Ratchet muss weiterhin ohne neue C901-Komplexitätsverletzung passieren.

## Aktuell nicht belegt

Diese Änderung liefert **noch keinen real gemessenen Agentennutzen** von `language_structure`.

Es fehlt weiterhin eine echte, revisionsgebundene Serie gepaarter Agentenläufe mit denselben Aufgaben, demselben Modell, demselben Budget und demselben Grader, bei der ausschließlich das Vorhandensein des `language_structure_json`-Kontexts variiert. Bis solche Primärevidenz vorliegt, ist `keep_optional` die sachlich richtige Produktentscheidung.

Insbesondere etabliert dieses v2-Format nicht:

- Default-Aktivierung;
- allgemeine kausale Überlegenheit außerhalb der gebundenen Fälle;
- vollständige Rust-/Bash-Semantik;
- Ehrlichkeit oder Unabhängigkeit eines externen Runners/Graders allein aufgrund seiner Hash-Bindung;
- statistische Signifikanz einer späteren kleinen Stichprobe;
- Merge- oder Deployment-Reife ohne die üblichen RepoGround-Gates.
