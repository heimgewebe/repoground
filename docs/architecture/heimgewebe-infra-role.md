# RepoGround im Heimgewebe-Infra-Modell

## 1. Rolle

RepoGround ist im Heimgewebe-Infra-Modell eine read-only Knowledge Engine und Observation Source für hausKI/hausmAIster. Es sammelt, strukturiert und erschließt vorhandene Repo-, Artefakt- und Atlas-Zustände, ohne daraus selbst operative Maßnahmen abzuleiten.

Atlas ist dabei die Beobachtungs- und Kartierungsschicht. Atlas beschreibt Dateisystem-, Workspace-, Snapshot- und Delta-Zustände als Observation-Artefakte. Diese Artefakte sind Belege über einen beobachteten Zustand, keine Steuerbefehle.

RepoGround/Atlas liefern insbesondere Evidence, Kontext, Retrieval-Ergebnisse, Atlas-Snapshots, Artefaktzustände und Diagnostik. hausKI/hausmAIster konsumiert diese Informationen und erzeugt daraus eigene Findings, Risiken, Pläne und Freigabevorgänge außerhalb von RepoGround.

Kurzform:

- RepoGround liefert Belege.
- hausmAIster erzeugt Bedeutung.
- Commands bleiben außerhalb von RepoGround.

## 2. Nicht-Rolle

RepoGround ist ausdrücklich nicht:

- eine Control-Plane,
- hausmAIster,
- ein Command-Executor,
- ein öffentlicher Agent-Gateway,
- eine ChatGPT-Schnittstelle.

RepoGround entscheidet nicht über Cleanup, Archivierung, Löschung oder Systemänderung. Solche Bewertungen und Freigaben gehören in hausKI/hausmAIster- oder Infra-Schichten außerhalb des RepoGround-Core.

## 2.1 Namensstrategie

`hausmAIster` ist der sichtbare Rollen- und Produktname in Fließtext, UI und Doku. `hausmaister` ist der technische Namespace für Pfade, Gateway-Namen, Tool-Namen, Events, Module, Profile und Contracts.

Daher sind Bezeichner wie `hausmaister-agent-gateway`, `hausmaister-task-request` oder `hausmaister_read_only` absichtlich lowercase/ASCII. Sie benennen dieselbe Domäne, aber auf der technischen Namespace-Ebene.

## 3. Bereitgestellte Quellartefakte

RepoGround darf als read-only Quelle folgende Artefakte und Sichten bereitstellen:

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
- später ein `hausmaister-agent-gateway`, aber nur als separates Gateway außerhalb des RepoGround-Core.

Nicht zulässig sind:

- externe Agents direkt auf RepoGround,
- ChatGPT direkt auf RepoGround,
- öffentliche RepoGround-Core-Exposition,
- rohe Dateisystemfreigabe.

RepoGround bleibt Quelle innerhalb kontrollierter Heimgewebe-Pfade. Direkte externe Agenten- oder ChatGPT-Anbindung ist keine RepoGround-Core-Aufgabe.

## 5. Deployment-Grenze

Der aktive Zielzustand setzt RepoGround lokal auf `heim-pc` ein, nah an den dortigen Repositories, Dumps und Atlas-Zielpfaden. Dirty- und untracked-Zustände bleiben lokale Evidenz und werden nicht durch einen entfernten Peer ersetzt.

Das frühere Zielmodell `rlens-peer-heimserver` ist superseded. `heimserver` ist außer Betrieb und darf nicht als aktiver RepoGround-Peer, Service-Ziel, Proxy oder Recovery-Abhängigkeit vorausgesetzt werden. Historische Heimserver-Snapshots und Runtime-Dokumente bleiben als historische Evidenz lesbar, begründen aber keine aktuelle RepoGround-Rolle.

RepoGround auf `heim-pc` bleibt loopback-first. Tailscale Serve darf internen Tailnet-Zugriff auf ausdrücklich autorisierten Pfaden ermöglichen. Tailscale Funnel ist kein RepoGround-Core-Dauerpfad.

Öffentlicher Zugriff darf später nur über ein getrenntes `hausmaister-agent-gateway` laufen. Dieses Gateway ist nicht Teil des RepoGround-Core und darf keine RepoGround-Runtime in eine öffentliche Control-Plane verwandeln.

## 5.1 Bounded Repo-Sync / Omnipull

Omnipull ist in RepoGround-Terminologie keine allgemeine Command-Ausführung, sondern eine eng begrenzte Repo-Sync-Vorbereitung für lokale Evidence- und Merger-Arbeit. Es dient dazu, lokale Repository-Bestände für Beobachtung, Atlas-Snapshots und Merger-Artefakte bereitzustellen, ohne RepoGround in einen Command-Executor zu verwandeln.

Erlaubt ist ausschließlich:

- `plan`: vorhandene und fehlende Repos prüfen und einen Report schreiben, ohne Repos zu verändern.
- `apply`: fehlende Repos klonen.
- `apply`: vorhandene Repos per fetch/prune aktualisieren.
- `apply`: vorhandene Repos nur dann aktualisieren, wenn der Arbeitsbaum clean ist und ein Fast-Forward möglich ist.
- ein Statusartefakt schreiben.

Verboten bleibt ausdrücklich:

- `reset --hard`,
- automatisches `stash`,
- automatisches `rebase`,
- Branch-Wechsel,
- Löschen untracked files,
- Verwerfen lokaler Änderungen,
- beliebige Shell-Commands.

Ein Omnipull-Report ist Evidence. Er ist kein Command-Freibrief, kein hausmAIster-Approval und keine implizite Berechtigung für weitere Mutationen.

## 6. API-Grenze

hausmAIster darf nur read-only Endpunkte oder gespeicherte Artefakte konsumieren. Quellflächen sind insbesondere:

- `POST /api/context_lookup`,
- `POST /api/artifact_lookup`,
- `GET /api/diagnostics`,
- `POST /api/trace_lookup`,
- read-only Query- und Lookup-Pfade, sofern sie keine Scan-, Sync-, Rebuild-, Apply- oder Mutationslogik auslösen.

Sync-, rebuild-, apply-, scan-trigger- oder mutation-nahe Pfade dürfen nicht als externe Agent-Tools gelten. Falls ein Endpunkt ambivalent ist, muss er für hausmAIster/Agents standardmäßig gesperrt bleiben.

Diese Grenze schützt RepoGround davor, von einer Knowledge Engine zu einer verdeckten Operationsschicht zu werden.

## 7. Contract-Grenze

RepoGround-owned sind nur RepoGround-native Wissens-, Lookup-, Snapshot- und Health-Contracts, insbesondere:

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

Nicht RepoGround-owned sind hausmAIster-, Infra-, Command- oder Chronik-Contracts, insbesondere:

- `hausmaister-task-request`,
- `hausmaister-observation-report`,
- `hausmaister-finding`,
- `hausmaister-plan`,
- `hausmaister-command-proposal`,
- `hausmaister-command-approval`,
- infra runtime gates,
- chronik event contracts.

RepoGround darf diese fremden Contracts nicht als kanonische RepoGround-Core-Contracts definieren. RepoGround-native Contracts bleiben RepoGround-owned; hausmAIster-/Infra-/Command-Contracts gehören nicht in RepoGround.

## 8. Events vs Commands

RepoGround-Artefakte können Events oder ObservationReports außerhalb von RepoGround auslösen. RepoGround-Artefakte sind aber keine Commands.

Daraus folgen die Invarianten:

- Ein QueryResult ist kein Handlungsauftrag.
- Ein Atlas-Signal oder Atlas-Analyseergebnis ist kein Löschvorschlag.
- Ein stale bundle ist ein Signal, keine Mutation.

Die Bedeutung, Priorisierung und Freigabe eines Signals entsteht erst in den konsumierenden hausKI/hausmAIster-Schichten.

## 9. Sicherheitsprinzipien

Für die Rolle von RepoGround im Heimgewebe-Infra-Modell gelten folgende Sicherheitsprinzipien:

- read-only first,
- no direct public exposure,
- no raw filesystem authority for external agents,
- no command execution,
- no cleanup actions,
- no secret/profile access,
- no bypass of hausmAIster approval gates.

Diese Prinzipien sind Rollengrenzen, keine optionalen Betriebsmodi. Ein RepoGround-Pfad, der diese Prinzipien nicht eindeutig einhält, ist für hausmAIster-/Agent-Konsum standardmäßig nicht freigegeben.

## 10. Folgearbeiten

Geplante Folgearbeiten außerhalb dieses PRs:

- hausmAIster read-only adapter in hausKI,
- optionales RepoGround service profile `hausmaister_read_only`,
- optionale Ergänzung von `docs/service-api.md` zu erlaubten read-only Konsumpfaden,
- optionale Tests für ein späteres Policy-Profil.

Nicht in diesem PR:

- kein Adapter-Code,
- kein Gateway-Code,
- kein MCP,
- kein Tailscale Funnel,
- keine Contracts,
- kein Executor.
