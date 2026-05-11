# Lenskit im Heimgewebe-Infra-Modell

## 1. Rolle

Lenskit ist im Heimgewebe-Infra-Modell eine read-only Knowledge Engine und Observation Source für hausKI/hausmAIster. Es sammelt, strukturiert und erschließt vorhandene Repo-, Artefakt- und Atlas-Zustände, ohne daraus selbst operative Maßnahmen abzuleiten.

Atlas ist dabei die Beobachtungs- und Kartierungsschicht. Atlas beschreibt Dateisystem-, Workspace-, Snapshot- und Delta-Zustände als Observation-Artefakte. Diese Artefakte sind Belege über einen beobachteten Zustand, keine Steuerbefehle.

Lenskit/Atlas liefern insbesondere Evidence, Kontext, Retrieval-Ergebnisse, Atlas-Snapshots, Artefaktzustände und Diagnostik. hausKI/hausmAIster konsumiert diese Informationen und erzeugt daraus eigene Findings, Risiken, Pläne und Freigabevorgänge außerhalb von Lenskit.

Kurzform:

- Lenskit liefert Belege.
- hausmAIster erzeugt Bedeutung.
- Commands bleiben außerhalb von Lenskit.

## 2. Nicht-Rolle

Lenskit ist ausdrücklich nicht:

- eine Control-Plane,
- hausmAIster,
- ein Command-Executor,
- ein öffentlicher Agent-Gateway,
- eine ChatGPT-Schnittstelle.

Lenskit entscheidet nicht über Cleanup, Archivierung, Löschung oder Systemänderung. Solche Bewertungen und Freigaben gehören in hausKI/hausmAIster- oder Infra-Schichten außerhalb des Lenskit-Core.

## 2.1 Namensstrategie

`hausmAIster` ist der sichtbare Rollen- und Produktname in Fließtext, UI und Doku. `hausmaister` ist der technische Namespace für Pfade, Gateway-Namen, Tool-Namen, Events, Module, Profile und Contracts.

Daher sind Bezeichner wie `hausmaister-agent-gateway`, `hausmaister-task-request` oder `hausmaister_read_only` absichtlich lowercase/ASCII. Sie benennen dieselbe Domäne, aber auf der technischen Namespace-Ebene.

## 3. Bereitgestellte Quellartefakte

Lenskit darf als read-only Quelle folgende Artefakte und Sichten bereitstellen:

- repo maps,
- retrieval context,
- evidence refs,
- architecture snapshots,
- atlas snapshots,
- atlas inventory / delta,
- service health endpoint,
- `output-health`,
- diagnostics lookup,
- context bundle lookup,
- artifact lookup,
- query results.

Diese Artefakte beschreiben beobachtete oder berechnete Wissenszustände. Sie tragen Kontext und Belegkraft, aber keine Ausführungsautorität.

## 4. Konsumenten

Zulässige Konsumenten sind:

- hausKI / hausmAIster über read-only Adapter,
- interne Tailnet-Clients, sofern der Zugriff über autorisierte lokale oder Tailscale-Pfade erfolgt,
- später ein `hausmaister-agent-gateway`, aber nur als separates Gateway außerhalb des Lenskit-Core.

Nicht zulässig sind:

- externe Agents direkt auf Lenskit,
- ChatGPT direkt auf Lenskit,
- öffentliche Lenskit-Core-Exposition,
- rohe Dateisystemfreigabe.

Lenskit bleibt Quelle innerhalb kontrollierter Heimgewebe-Pfade. Direkte externe Agenten- oder ChatGPT-Anbindung ist keine Lenskit-Core-Aufgabe.

## 5. Deployment-Grenze

Lenskit Core läuft bevorzugt auf `heim-pc`, weil dort Repos, Dumps und Atlas-Zielpfade liegen. Damit bleibt Lenskit nahe an den lokalen Quellartefakten und muss keine eigenständige öffentliche Infrastrukturrolle übernehmen.

`rLens` ist ein lokaler Service und bleibt loopback-first. Tailscale Serve darf internen Tailnet-Zugriff auf autorisierten Pfaden ermöglichen. Tailscale Funnel ist kein Lenskit-Core-Dauerpfad.

Öffentlicher Zugriff darf später nur über ein getrenntes `hausmaister-agent-gateway` laufen. Dieses Gateway ist nicht Teil des Lenskit-Core und darf keine Lenskit-Runtime in eine öffentliche Control-Plane verwandeln.

## 6. API-Grenze

hausmAIster darf nur read-only Endpunkte oder gespeicherte Artefakte konsumieren. Quellflächen sind insbesondere:

- `POST /api/context_lookup`,
- `POST /api/artifact_lookup`,
- `GET /api/diagnostics`,
- `POST /api/trace_lookup`,
- read-only Query- und Lookup-Pfade, sofern sie keine Scan-, Sync-, Rebuild-, Apply- oder Mutationslogik auslösen.

Sync-, rebuild-, apply-, scan-trigger- oder mutation-nahe Pfade dürfen nicht als externe Agent-Tools gelten. Falls ein Endpunkt ambivalent ist, muss er für hausmAIster/Agents standardmäßig gesperrt bleiben.

Diese Grenze schützt Lenskit davor, von einer Knowledge Engine zu einer verdeckten Operationsschicht zu werden.

## 7. Contract-Grenze

Lenskit-owned sind nur Lenskit-native Wissens-, Lookup-, Snapshot- und Health-Contracts, insbesondere:

- `query-result`,
- `query-context-bundle`,
- `artifact-lookup`,
- `diagnostics-lookup`,
- `trace-lookup`,
- `atlas-snapshot`,
- `atlas-inventory`,
- `atlas-delta`,
- `bundle-manifest`,
- `output-health`.

Nicht Lenskit-owned sind hausmAIster-, Infra-, Command- oder Chronik-Contracts, insbesondere:

- `hausmaister-task-request`,
- `hausmaister-observation-report`,
- `hausmaister-finding`,
- `hausmaister-plan`,
- `hausmaister-command-proposal`,
- `hausmaister-command-approval`,
- infra runtime gates,
- chronik event contracts.

Lenskit darf diese fremden Contracts nicht als kanonische Lenskit-Core-Contracts definieren. Lenskit-native Contracts bleiben Lenskit-owned; hausmAIster-/Infra-/Command-Contracts gehören nicht in Lenskit.

## 8. Events vs Commands

Lenskit-Artefakte können Events oder ObservationReports außerhalb von Lenskit auslösen. Lenskit-Artefakte sind aber keine Commands.

Daraus folgen die Invarianten:

- Ein QueryResult ist kein Handlungsauftrag.
- Ein Atlas-Signal oder Atlas-Analyseergebnis ist kein Löschvorschlag.
- Ein stale bundle ist ein Signal, keine Mutation.

Die Bedeutung, Priorisierung und Freigabe eines Signals entsteht erst in den konsumierenden hausKI/hausmAIster-Schichten.

## 9. Sicherheitsprinzipien

Für die Rolle von Lenskit im Heimgewebe-Infra-Modell gelten folgende Sicherheitsprinzipien:

- read-only first,
- no direct public exposure,
- no raw filesystem authority for external agents,
- no command execution,
- no cleanup actions,
- no secret/profile access,
- no bypass of hausmAIster approval gates.

Diese Prinzipien sind Rollengrenzen, keine optionalen Betriebsmodi. Ein Lenskit-Pfad, der diese Prinzipien nicht eindeutig einhält, ist für hausmAIster-/Agent-Konsum standardmäßig nicht freigegeben.

## 10. Folgearbeiten

Geplante Folgearbeiten außerhalb dieses PRs:

- hausmAIster read-only adapter in hausKI,
- optionales Lenskit service profile `hausmaister_read_only`,
- optionale Ergänzung von `docs/service-api.md` zu erlaubten read-only Konsumpfaden,
- optionale Tests für ein späteres Policy-Profil.

Nicht in diesem PR:

- kein Adapter-Code,
- kein Gateway-Code,
- kein MCP,
- kein Tailscale Funnel,
- keine Contracts,
- kein Executor.
