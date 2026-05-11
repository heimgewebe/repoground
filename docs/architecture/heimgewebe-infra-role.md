# Lenskit im Heimgewebe-Infra-Modell

## 1. Rolle

Lenskit ist im Heimgewebe-Infra-Modell eine read-only Knowledge Engine und Observation Source fuer hausKI/hausmAIster. Es sammelt, strukturiert und erschliesst vorhandene Repo-, Artefakt- und Atlas-Zustaende, ohne daraus selbst operative Massnahmen abzuleiten.

Atlas ist dabei die Beobachtungs- und Kartierungsschicht. Atlas beschreibt Dateisystem-, Workspace-, Snapshot- und Delta-Zustaende als Observation-Artefakte. Diese Artefakte sind Belege ueber einen beobachteten Zustand, keine Steuerbefehle.

Lenskit/Atlas liefern insbesondere Evidence, Kontext, Retrieval-Ergebnisse, Atlas-Snapshots, Artefaktzustaende und Diagnostik. hausKI/hausmAIster konsumiert diese Informationen und erzeugt daraus eigene Findings, Risiken, Plaene und Freigabevorgaenge ausserhalb von Lenskit.

Kurzform:

- Lenskit liefert Belege.
- hausmAIster erzeugt Bedeutung.
- Commands bleiben ausserhalb von Lenskit.

## 2. Nicht-Rolle

Lenskit ist ausdruecklich nicht:

- eine Control-Plane,
- hausmAIster,
- ein Command-Executor,
- ein oeffentlicher Agent-Gateway,
- eine ChatGPT-Schnittstelle.

Lenskit entscheidet nicht ueber Cleanup, Archivierung, Loeschung oder Systemaenderung. Solche Bewertungen und Freigaben gehoeren in hausKI/hausmAIster- oder Infra-Schichten ausserhalb des Lenskit-Core.

## 3. Bereitgestellte Quellartefakte

Lenskit darf als read-only Quelle folgende Artefakte und Sichten bereitstellen:

- repo maps,
- retrieval context,
- evidence refs,
- architecture snapshots,
- atlas snapshots,
- atlas inventory / delta,
- bundle health,
- output health,
- diagnostics lookup,
- context bundle lookup,
- artifact lookup,
- query results.

Diese Artefakte beschreiben beobachtete oder berechnete Wissenszustaende. Sie tragen Kontext und Belegkraft, aber keine Ausfuehrungsautoritaet.

## 4. Konsumenten

Zulaessige Konsumenten sind:

- hausKI / hausmAIster ueber read-only Adapter,
- interne Tailnet-Clients, sofern der Zugriff ueber autorisierte lokale oder Tailscale-Pfade erfolgt,
- spaeter ein `hausmaister-agent-gateway`, aber nur als separates Gateway ausserhalb des Lenskit-Core.

Nicht zulaessig sind:

- externe Agents direkt auf Lenskit,
- ChatGPT direkt auf Lenskit,
- oeffentliche Lenskit-Core-Exposition,
- rohe Dateisystemfreigabe.

Lenskit bleibt Quelle innerhalb kontrollierter Heimgewebe-Pfade. Direkte externe Agenten- oder ChatGPT-Anbindung ist keine Lenskit-Core-Aufgabe.

## 5. Deployment-Grenze

Lenskit Core laeuft bevorzugt auf `heim-pc`, weil dort Repos, Dumps und Atlas-Zielpfade liegen. Damit bleibt Lenskit nahe an den lokalen Quellartefakten und muss keine eigenstaendige oeffentliche Infrastrukturrolle uebernehmen.

`rLens` ist ein lokaler Service und bleibt loopback-first. Tailscale Serve darf internen Tailnet-Zugriff auf autorisierten Pfaden ermoeglichen. Tailscale Funnel ist kein Lenskit-Core-Dauerpfad.

Oeffentlicher Zugriff darf spaeter nur ueber ein getrenntes `hausmaister-agent-gateway` laufen. Dieses Gateway ist nicht Teil des Lenskit-Core und darf keine Lenskit-Runtime in eine oeffentliche Control-Plane verwandeln.

## 6. API-Grenze

hausmAIster darf nur read-only Endpunkte oder gespeicherte Artefakte konsumieren. Quellflaechen sind insbesondere:

- `context_lookup`,
- `artifact_lookup`,
- `diagnostics_lookup`,
- `trace_lookup`,
- read-only Query- und Lookup-Pfade, sofern sie keine Scan-, Sync-, Rebuild-, Apply- oder Mutationslogik ausloesen.

Sync-, rebuild-, apply-, scan-trigger- oder mutation-nahe Pfade duerfen nicht als externe Agent-Tools gelten. Falls ein Endpunkt ambivalent ist, muss er fuer hausmAIster/Agents standardmaessig gesperrt bleiben.

Diese Grenze schuetzt Lenskit davor, von einer Knowledge Engine zu einer verdeckten Operationsschicht zu werden.

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

Lenskit darf diese fremden Contracts nicht als kanonische Lenskit-Core-Contracts definieren. Lenskit-native Contracts bleiben Lenskit-owned; hausmAIster-/Infra-/Command-Contracts gehoeren nicht in Lenskit.

## 8. Events vs Commands

Lenskit-Artefakte koennen Events oder ObservationReports ausserhalb von Lenskit ausloesen. Lenskit-Artefakte sind aber keine Commands.

Daraus folgen die Invarianten:

- Ein QueryResult ist kein Handlungsauftrag.
- Ein Atlas-Signal oder Atlas-Analyseergebnis ist kein Loeschvorschlag.
- Ein stale bundle ist ein Signal, keine Mutation.

Die Bedeutung, Priorisierung und Freigabe eines Signals entsteht erst in den konsumierenden hausKI/hausmAIster-Schichten.

## 9. Sicherheitsprinzipien

Fuer die Rolle von Lenskit im Heimgewebe-Infra-Modell gelten folgende Sicherheitsprinzipien:

- read-only first,
- no direct public exposure,
- no raw filesystem authority for external agents,
- no command execution,
- no cleanup actions,
- no secret/profile access,
- no bypass of hausmAIster approval gates.

Diese Prinzipien sind Rollengrenzen, keine optionalen Betriebsmodi. Ein Lenskit-Pfad, der diese Prinzipien nicht eindeutig einhaelt, ist fuer hausmAIster-/Agent-Konsum standardmaessig nicht freigegeben.

## 10. Folgearbeiten

Geplante Folgearbeiten ausserhalb dieses PRs:

- hausmAIster read-only adapter in hausKI,
- optionales Lenskit service profile `hausmaister_read_only`,
- optionale Ergaenzung von `docs/service-api.md` zu erlaubten read-only Konsumpfaden,
- optionale Tests fuer ein spaeteres Policy-Profil.

Nicht in diesem PR:

- kein Adapter-Code,
- kein Gateway-Code,
- kein MCP,
- kein Tailscale Funnel,
- keine Contracts,
- kein Executor.
