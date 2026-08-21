# RepoGround im Heimgewebe-Infra-Modell

## 1. Rolle

RepoGround ist im Heimgewebe-Infra-Modell die read-only Knowledge Engine für verifizierbaren, zitierfähigen Repository-Kontext. Es sammelt, strukturiert und erschließt vorhandene Repo-, Artefakt- und Atlas-Zustände, ohne daraus selbst operative Maßnahmen, Agentenauswahl oder Freigaben abzuleiten.

Der Systemkatalog ordnet RepoGround die stabile Wahrheitsdomäne `repository_context_citations` zu. RepoGround besitzt dagegen weder `agent_routing` noch lokale oder repositorybezogene Ausführungsautorität. Diese Zuständigkeiten liegen bei Grabowski; Aufgaben-, PR-, Check- und Runtime-Wahrheit bleiben bei ihren jeweiligen Primärquellen.

Atlas ist dabei die Beobachtungs- und Kartierungsschicht. Atlas beschreibt Dateisystem-, Workspace-, Snapshot- und Delta-Zustände als Observation-Artefakte. Diese Artefakte sind Belege über einen beobachteten Zustand, keine Steuerbefehle.

Kurzform:

- RepoGround liefert verifizierbaren Kontext und Belege.
- Grabowski bindet Livezustand, Agent-Routing und freigegebene Ausführung.
- Bureau, GitHub, CI und Runtime behalten ihre jeweilige Primärwahrheit.
- Kein weiterer Vermittler ist für diesen Operatorpfad erforderlich.

## 2. Nicht-Rolle

RepoGround ist ausdrücklich nicht:

- eine Control-Plane,
- ein Agent-Router,
- ein Command-Executor,
- eine Task- oder Claim-Autorität,
- eine Merge-Autorität,
- ein öffentlicher Agent-Gateway,
- eine ChatGPT-Control-Plane.

RepoGround entscheidet nicht über Cleanup, Archivierung, Löschung, Merge, Deployment oder Systemänderung. Solche Entscheidungen und Wirkungen bleiben bei den zuständigen Primärsystemen: Bureau für Aufgaben- und Claimzustand, Grabowski für freigegebene lokale und repositorybezogene Ausführung sowie Agent-Routing, GitHub für PR- und Mergezustand, CI für Checks und die jeweilige Runtime für laufenden Dienstzustand.

## 2.1 Konsumenten- und Autoritätssemantik

HausKI ist ein eigenständiges Heimgewebe-System und darf RepoGround-Kontext optional über einen ausdrücklich autorisierten read-only Adapter konsumieren. HausKI ist jedoch kein erforderlicher Vermittler zwischen RepoGround und Grabowski, kein RepoGround-Gateway und keine Quelle von Grabowskis Ausführungs- oder Agent-Routing-Autorität.

Historische oder geplante Bezeichner wie `hausmAIster`, `hausmaister-agent-gateway` oder `hausmaister_read_only` begründen für sich keinen aktiven Runtimepfad, keine Freigabekette und keine aktuelle Operatorarchitektur. Ein solcher Adapter oder Gateway darf nur dann als aktiv beschrieben werden, wenn seine eigene Primärquelle und ein frischer Runtime-Readback das belegen.

Die frühere Kurzform „hausmAIster erzeugt Bedeutung“ ist deshalb keine aktuelle Autoritätsbeschreibung. Bedeutung kann bei unterschiedlichen Konsumenten entstehen; operative Wirkung entsteht ausschließlich über die dafür zuständigen, frisch geprüften Autoritätspfade.

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

Zulässige Konsumenten sind insbesondere:

- Grabowski über gebundene RepoGround-Kontext-, Evidence- oder Handoff-Pfade,
- Menschen und AI-Systeme über ausdrücklich autorisierte read-only Oberflächen,
- HausKI optional über einen ausdrücklich autorisierten read-only Adapter,
- interne Tailnet-Clients, sofern der Zugriff über autorisierte lokale oder Tailscale-Pfade erfolgt.

Nicht zulässig sind:

- direkte Mutationsautorität für externe Agents aus einem RepoGround-Ergebnis,
- Ableitung von Task-, Claim-, Merge-, Deploy- oder Runtime-Freigaben aus RepoGround-Kontext,
- öffentliche RepoGround-Core-Exposition ohne getrennte Autorisierung,
- rohe Dateisystemfreigabe.

RepoGround bleibt Quelle innerhalb kontrollierter Heimgewebe-Pfade. Eine konkrete ChatGPT-, Agenten- oder Produktintegration ist eine Consumer- beziehungsweise Operatoraufgabe und keine RepoGround-Core-Autorität.

## 5. Deployment-Grenze

Der aktive Zielzustand setzt RepoGround lokal auf `heim-pc` ein, nah an den dortigen Repositories, Dumps und Atlas-Zielpfaden. Dirty- und untracked-Zustände bleiben lokale Evidenz und werden nicht durch einen entfernten Peer ersetzt.

Das frühere Zielmodell `rlens-peer-heimserver` ist superseded. `heimserver` ist außer Betrieb und darf nicht als aktiver RepoGround-Peer, Service-Ziel, Proxy oder Recovery-Abhängigkeit vorausgesetzt werden. Historische Heimserver-Snapshots und Runtime-Dokumente bleiben als historische Evidenz lesbar, begründen aber keine aktuelle RepoGround-Rolle.

RepoGround auf `heim-pc` bleibt loopback-first. Tailscale Serve darf internen Tailnet-Zugriff auf ausdrücklich autorisierten Pfaden ermöglichen. Tailscale Funnel ist kein RepoGround-Core-Dauerpfad.

Öffentlicher Zugriff ist keine RepoGround-Core-Eigenschaft. Falls später ein öffentlicher Consumerpfad nötig wird, muss er über eine getrennt autorisierte Gateway- oder Control-Plane laufen. Ein solches Gateway ist nicht Teil des RepoGround-Core und erbt aus RepoGround-Kontext keinerlei Ausführungsautorität.

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

Ein Omnipull-Report ist Evidence. Er ist kein Command-Freibrief, kein Approval-Beleg und keine implizite Berechtigung für weitere Mutationen.

## 6. API-Grenze

Externe Konsumenten dürfen nur read-only Endpunkte oder gespeicherte Artefakte als Kontextquelle verwenden. Quellflächen sind insbesondere:

- `POST /api/context_lookup`,
- `POST /api/artifact_lookup`,
- `GET /api/diagnostics`,
- `POST /api/trace_lookup`,
- read-only Query- und Lookup-Pfade, sofern sie keine Scan-, Sync-, Rebuild-, Apply- oder Mutationslogik auslösen.

Sync-, rebuild-, apply-, scan-trigger- oder mutation-nahe Pfade dürfen nicht allein aufgrund ihrer Erreichbarkeit als Agent-Tools gelten. Falls ein Endpunkt ambivalent ist, muss er für externe Consumer standardmäßig gesperrt bleiben.

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

Nicht RepoGround-owned sind insbesondere:

- Grabowski-Work-, Lease-, Agent-Routing-, Verification- oder Integration-Contracts,
- Bureau-Task-, Claim-, Reservation- oder Closeout-Contracts,
- Systemkatalog-Authority- und Ecosystem-Contracts,
- GitHub-, CI- oder Runtime-Wahrheit,
- Chronik-Event-Contracts,
- HausKI- oder historische `hausmaister-*`-Contracts.

RepoGround darf fremde Contracts nicht als kanonische RepoGround-Core-Contracts definieren. Die bloße Erwähnung oder Konsumierbarkeit eines fremden Contracts überträgt keine Autorität auf RepoGround.

## 8. Events vs Commands

RepoGround-Artefakte können außerhalb von RepoGround als Eingabe für Events, Findings oder weitere Analyse dienen. RepoGround-Artefakte sind aber keine Commands.

Daraus folgen die Invarianten:

- Ein QueryResult ist kein Handlungsauftrag.
- Ein Atlas-Signal oder Atlas-Analyseergebnis ist kein Löschvorschlag.
- Ein stale bundle ist ein Signal, keine Mutation.
- Ein guter Kontext- oder Retrieval-Score ist keine Merge-, Test- oder Deploy-Freigabe.

Bedeutung und Priorisierung können beim jeweiligen Konsumenten entstehen. Operative Entscheidungen werden anschließend nur über die zuständigen Autoritätspfade getroffen und gegen deren Primärquellen zurückgelesen.

## 9. Sicherheitsprinzipien

Für die Rolle von RepoGround im Heimgewebe-Infra-Modell gelten folgende Sicherheitsprinzipien:

- read-only first,
- no direct public exposure,
- no raw filesystem authority for external agents,
- no general command execution,
- no cleanup authority,
- no secret/profile access,
- no execution permission inferred from context,
- no bypass of Bureau-, Grabowski-, GitHub-, CI- oder Runtime-Autorität.

Diese Prinzipien sind Rollengrenzen, keine optionalen Betriebsmodi. Ein Consumerpfad, der sie nicht eindeutig einhält, ist standardmäßig nicht freigegeben.

## 10. Aktiver Operatorpfad

Für repositorybezogene Operatorarbeit gilt aktuell folgende Rollenfolge:

```text
RepoGround Evidence / zitierfähiger Kontext
        ↓
Grabowski Live-State + Context Fabric / Controller
        ↓ optional
Coding-Agent- oder Reviewer-Lane
        ↓
Grabowski Verification / Integration
        ↓
GitHub / CI / Runtime Readback
```

Bureau kann die Aufgabenquelle für diesen Pfad sein; eine explizit autorisierte direkte Operatoraufgabe kann ebenfalls Quelle sein. RepoGround entscheidet in beiden Fällen weder über die Aufgabe noch über den Writer oder den Abschluss.

HausKI ist nicht Bestandteil dieses erforderlichen Operatorpfads. Eine spätere HausKI-Integration darf RepoGround read-only konsumieren, muss aber als unabhängiger Consumerpfad belegt und betrieben werden.

## 11. Folgearbeiten

Sinnvolle Folgearbeiten entstehen nur aus einem konkreten Consumerbedarf. Mögliche Beispiele sind:

- eine Ergänzung von `docs/service-api.md` für tatsächlich verwendete read-only Konsumpfade,
- ein separates, produktgebundenes read-only Profil, wenn ein realer Consumer es benötigt,
- zusätzliche Drift-Guards, falls weitere aktive Dokumente wieder eine fremde Operatorautorität behaupten.

Nicht allein aus dieser Rollenbeschreibung abzuleiten sind:

- ein HausKI-Adapter,
- ein hausmAIster-/hausmaister-Gateway,
- ein öffentlicher MCP- oder Funnel-Pfad,
- neue Fremdcontracts,
- ein zusätzlicher Executor.
