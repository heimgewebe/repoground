# Atlas Heimserver Profiles

## Zweck

Diese Profile beschreiben den Atlas-Snapshot-Rahmen für `rlens-peer-heimserver`. Ziel ist, Heimserver-Dateisystem-Snapshots agentenfähig zu machen, ohne Secret-Inhalte oder lokale forensische Rohdaten ungeprüft in Agenten-, ChatGPT- oder Export-Artefakte zu lecken.

Die Profile sind Doku-/Planungsprofile. Sie ändern nicht das Atlas-Sicherheitsmodell, die loopback-first-Regel oder die bestehende Auth-Pflicht für sensible Dateisystemnavigation.

## `heimserver-overview`

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

Dieses Profil ist für grobe Inventarisierung und Evidence-Übersicht gedacht. Inhalte werden defensiv behandelt; Binärdaten liefern nur Metadaten und Hashes.

## `heimserver-deep`

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

Dieses Profil ist für tieferes lokales Verständnis von Konfigurationen, Skripten, Services und Repos gedacht. Secret-nahe Bereiche bleiben inventory-only, damit Pfad-, Existenz- und Metadatenbelege nicht automatisch zu Inhaltslecks werden.

## `heimserver-forensic-local`

- root: `/`
- content_policy: `broad/local`
- secret_policy: `local_only`
- export_allowed: `false`

Dieses Profil ist nur für lokale forensische Analyse unter direkter lokaler Kontrolle gedacht. `heimserver-forensic-local` darf nicht ungeprüft in Agent-/ChatGPT-Artefakte exportiert werden. Ein Export benötigt eine explizite menschliche Prüfung und ein separates, exportfähiges Artefakt mit redigierten Inhalten.

## Sicherheitsinvarianten

- Atlas-Snapshot = Observation / Evidence, kein Befehl.
- Merger = lokale Artefakterzeugung aus beobachteten oder bereitgestellten Quellen.
- RepoGround service = lokaler Service / UI / API, keine öffentliche Control-Plane.
- Root-Browsing bleibt loopback- und Auth-gated; non-loopback Root-Browsing bleibt verweigert.
- Secret-Inhalte werden nicht durch Profilnamen freigegeben.
