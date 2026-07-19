# PR-Schau Manual QA & Smoke Test Checklist (iPad + Working Copy)

Ziel: Sicherstellen, dass PR-Schau-Bundle zuverlässig entsteht, bevor alte Ordner gelöscht werden, und dass repolens.py es per Button findet und öffnen kann.

## A) Setup (1×)
- [ ] Auf iPad / Pythonista: `repolens.py` läuft auf dem aktuellen Branch (mit PR-Schau).
- [ ] WC-Hub Root existiert.
- [ ] Pfad `wc-hub/.repoground/pr-schau/` existiert oder wird automatisch angelegt.

**Pass-Kriterium**: `repolens` startet ohne ImportError.

## B) Positivfall 1: „Standard-PR-Schau entsteht beim Import + Löschen passiert danach“
- [ ] Lege im Hub einen Repo-Ordner an (z. B. `wc-hub/<repo_name>/`) mit Dateien.
- [ ] Importiere eine neue ZIP mit demselben `repo_name` (Update-Szenario).
- [ ] Beobachte Konsole/Log:
    - „Erzeuge PR-Review-Bundle …“
    - „PR-Review-Bundle erfolgreich erstellt.“
    - „Alter Ordner gelöscht“
- [ ] Prüfe Dateien:
    - `wc-hub/.repoground/pr-schau/<repo_name>/<timestamp>/delta.json`
    - `.../review.md`
    - `.../bundle.json`

**Pass-Kriterien**:
- Bundle existiert.
- Alter Repo-Ordner wurde erst *nach* Bundle-Erstellung gelöscht.
- `review.md` enthält Summary und Details.

## C) Positivfall 2: UI-Button findet Bundles und öffnet review.md
- [ ] Öffne `repolens` UI.
- [ ] Tippe „PR-Schau (Reviews)“.
- [ ] Liste erscheint (Einträge wie `<repo> @ <timestamp>`).
- [ ] Tippe einen Eintrag.

**Pass-Kriterium**: `review.md` öffnet sich (Editor oder Quicklook) ohne Crash. Neuester Timestamp oben.

## D) Positivfall 3: „Hotspots erscheinen“
- [ ] Importiere Änderungen in Hotspot-Pfaden: `.github/workflows/`, `contracts/`, `*.schema.json`, `scripts/`, `config/`.

**Pass-Kriterium**: Abschnitt „🔥 Hotspots“ in `review.md` listet diese Dateien.

## E) Negativfall 1: Redaction greift (Secrets nicht im Klartext)
- [ ] Importiere Datei mit Secret-Namen: `.env`, `id_rsa`, `*.pem`.
- [ ] Importiere Datei mit Secret-Inhalt: z.B. `config.yml` mit Inhalt `ghp_SECRETTOKEN`.

**Pass-Kriterium**:
- In `review.md` steht bei Secret-Namen: `REDACTED (filename rule)`.
- In `review.md` steht bei Secret-Inhalt: `REDACTED (content rule)`.
- Kein Klartext-Secret sichtbar.

## F) Negativfall 2: Bundle-Fehler stoppt Löschung (Datenverlustschutz)
- [ ] (Simuliert) Bringe `generate_review_bundle` zum Scheitern (z.B. temporärer Code-Fehler oder Dateisystem-Fehler).

**Pass-Kriterium**:
- Log: „❌ FEHLER bei PR-Bundle-Erstellung… ABBRUCH: Alter Ordner wird NICHT gelöscht“.
- Alter Repo-Ordner ist noch vorhanden.

## G) Grenzfälle
- [ ] Große Datei (>200KB) in added/changed -> `review.md` zeigt „Omitted (Size …)“.
- [ ] Binary File (enthält NULL-Bytes) -> `review.md` zeigt „Binary File“.
- [ ] Encoding-Probleme -> Inhalt wird mit `errors="replace"` gelesen (kein Crash).
- [ ] Mehrere Imports -> Mehrere Timestamp-Ordner, UI listet alle.
