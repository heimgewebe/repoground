# Atlas Heimserver Profiles — historische Referenz

## Status

Der Systemkatalog führt `heimserver` seit dem geprüften Stand vom 2026-08-22 als `retired`. Dieses Dokument ist deshalb **historische Planungs- und Safety-Evidenz**, kein aktives Deployment-, Runtime- oder Implementierungsprofil.

Die unten erhaltenen Profilnamen dürfen nicht als Auftrag verstanden werden, `heimserver` wieder als Atlas-Zielhost zu aktivieren. Ein künftiger Remote-Host benötigt eine frische Systemkatalog-Registrierung, eigene Autorisierung und neu benannte, hostgebundene Profile. Die hier dokumentierten Ausschluss-, Secret- und Exportregeln können dafür als Sicherheitsreferenz dienen.

## Zweck

Diese historischen Profile beschrieben den Atlas-Snapshot-Rahmen für `rlens-peer-heimserver`. Ziel war, Heimserver-Dateisystem-Snapshots agentenfähig zu machen, ohne Secret-Inhalte oder lokale forensische Rohdaten ungeprüft in Agenten-, ChatGPT- oder Export-Artefakte zu lecken.

Die Profile sind Doku-/Planungsevidenz. Sie ändern nicht das Atlas-Sicherheitsmodell, die loopback-first-Regel oder die bestehende Auth-Pflicht für sensible Dateisystemnavigation und begründen keine aktuelle Host- oder Runtimeverbindung.

## Historisches Profil `heimserver-overview`

- root: `/`
- content_policy: `text_only` oder `inventory-first`
- binary_policy: `metadata + hash`
- secret_policy: `redact_content`
- exclude content roots:
  - `/proc`
  - `/sys`
  - `/dev`
  - `/run`
  - `/tmp`
  - `/var/run`

Dieses Profil war für grobe Inventarisierung und Evidence-Übersicht gedacht. Inhalte werden defensiv behandelt; Binärdaten liefern nur Metadaten und Hashes.

## Historisches Profil `heimserver-deep`

- root: `/`
- content_policy: `config/scripts/text`
- binary_policy: `metadata + hash`
- secret_policy: `inventory_only`
- include priority:
  - `/etc`
  - `/opt`
  - `/srv`
  - `/home/alex/repos`
  - `/home/alex/.config/systemd`
- exclude content roots:
  - `/proc`
  - `/sys`
  - `/dev`
  - `/run`
  - `/tmp`
  - `/var/run`

Dieses Profil war für tieferes lokales Verständnis von Konfigurationen, Skripten, Services und Repos gedacht. Secret-nahe Bereiche bleiben als Sicherheitsreferenz inventory-only, damit Pfad-, Existenz- und Metadatenbelege nicht automatisch zu Inhaltslecks werden.

## Historisches Profil `heimserver-forensic-local`

- root: `/`
- content_policy: `broad/local`
- secret_policy: `local_only`
- export_allowed: `false`

Dieses Profil war ausschließlich für lokale forensische Analyse unter direkter lokaler Kontrolle gedacht. Die erhaltene Regel bleibt als historische Sicherheitsinvariante gültig: `heimserver-forensic-local` darf nicht als aktives Profil wiederverwendet und sein Inhalt nicht ungeprüft in Agent-/ChatGPT-Artefakte exportiert werden. Ein vergleichbares Profil für einen künftig neu autorisierten Host benötigt eine neue Identität, explizite Prüfung und ein separates, exportfähiges Artefakt mit redigierten Inhalten.

## Sicherheitsinvarianten

- Atlas-Snapshot = Observation / Evidence, kein Befehl.
- Merger = lokale Artefakterzeugung aus beobachteten oder bereitgestellten Quellen.
- RepoGround service = lokaler Service / UI / API, keine öffentliche Control-Plane.
- Root-Browsing bleibt loopback- und Auth-gated; non-loopback Root-Browsing bleibt verweigert.
- Secret-Inhalte werden nicht durch Profilnamen freigegeben.
- Ein retired Host wird durch historische Profiltexte nicht reaktiviert.
