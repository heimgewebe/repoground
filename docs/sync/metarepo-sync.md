# Metarepo Sync

**Status:** Beta (v2.4+)
**Quelle:** `metarepo` -> Fleet Repositories

Die `metarepo-sync` Funktion synchronisiert zentrale Konfigurationsdateien (Contracts, Workflows, Policies) aus dem `metarepo` in alle angeschlossenen Fleet-Repositories im Hub.

## Funktionsweise

1.  **Quelle:** Liest das Manifest unter `hub/metarepo/sync/metarepo-sync.yml`.
2.  **Ziel:** Iteriert über alle validen Repositories im Hub (`.git` oder `.ai-context.yml` vorhanden).
3.  **Aktion:** Kopiert definierte Dateien, wenn:
    *   Die Datei im Ziel fehlt (`ADD`).
    *   Die Datei im Ziel existiert UND einen `managed-by: metarepo-sync` Marker enthält (`UPDATE`).
    *   Modus `copy_if_missing` aktiv ist und Datei fehlt.

## Marker-Prinzip (Safety)

Um manuell angepasste Dateien nicht zu überschreiben, prüft der Sync bei existierenden Dateien die ersten 20 Zeilen (max 8KB) auf den Marker:

```yaml
# managed-by: metarepo-sync
```

Fehlt dieser Marker, wird die Datei **nicht** überschrieben (Status: `BLOCKED`).

## Report & Side-Effects

Der Sync erzeugt in jedem Ziel-Repo einen Report:

*   **Pfad:** `.gewebe/out/sync.report.json`
*   **Inhalt:** JSON mit Status, Summary und Details zu jeder Datei.
*   **Wichtig:** Dieses File gehört **nicht** in git! Es sollte in der globalen oder lokalen `.gitignore` stehen.

## Modi

*   `dry_run`: Simuliert den Vorgang, schreibt nur den Report. (Standard)
*   `apply`: Führt Änderungen durch. Erstellt bei `UPDATE` automatisch ein Backup (`.bak.<timestamp>`).

## API

Der Sync wird über den RepoGround service getriggert:

`POST /api/sync/metarepo`

Payload:
```json
{
  "mode": "dry_run",
  "targets": ["wgx", "ci"]
}
```
*   `targets` filtert Einträge im Manifest anhand der ID (Prefix-Match auf Segmente `id/` oder `id:`).
