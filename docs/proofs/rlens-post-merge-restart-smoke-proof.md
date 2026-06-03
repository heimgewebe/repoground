# rlens Post-Merge Restart & Surface Smoke — Proof

> Erstellt am 2026-06-03.
> Scope: kleiner Betriebs-/Doku-Slice. **Keine** Änderungen an `bundle_surface_validate.py`,
> `runtime_provenance.py`, `merge.py` oder `claim_evidence_map.py`. Keine CI- oder Systemd-Automation.
> Ziel: einen wiederkehrenden Klassenfehler (laufender `rlens.service` läuft mit altem
> Python-Modul-Snapshot) reproduzierbar diagnostizierbar machen.

## 1. Problem

Python lädt Module beim Prozessstart. Ein laufender `rlens.service` (`systemd --user`)
übernimmt nach `git pull` oder einem Merge **nicht** automatisch neue Module aus dem
Working-Tree. Solange der Service nicht neu gestartet wird, emittiert er Dumps aus der
zum Startzeitpunkt eingefrorenen Code-Sicht.

## 2. Befund (2026-06-03)

Der reale `rlens`-Dump nach Merge #737 zeigte zunächst keine Surface-Felder
(`generator.runtime`, `links.post_emit_health_path`, `links.bundle_surface_validation_path`,
`links.bundle_surface_validation_status`, `claim_evidence_map_json`). Diagnose:

- Working-Tree war clean und HEAD = `af3f2017` (Merge #737).
- `merger/lenskit/core/merge.py`, `runtime_provenance.py` und `bundle_surface_validate.py`
  waren im Working-Tree vorhanden und mtime von 2026-06-03.
- `systemctl --user status rlens` zeigte: `active (running) since Tue 2026-05-26 …`,
  `Main PID: 808130`, `cwd → /home/alex/repos/lenskit`. Der Prozess hatte die damalige
  `merge.py` **vor** dem Surface-Merge geladen — `build_runtime_provenance`,
  `write_bundle_surface_validation` und `post_emit_health` waren in seinem Speicher
  unsichtbar.
- Faithful Reproduktion (gleicher `write_reports_v2`-Aufruf wie `runner.py:284`) im
  aktuellen Working-Tree erzeugte **alle** erwarteten Felder (siehe `real-dump-surface-self-check-proof.md`,
  Abschnitt 4). Der Bug saß also nicht im Code, sondern in der eingefrorenen Service-Instanz.

Nach `systemctl --user restart rlens` (neue Main-PID, frische Modulladung) erzeugte ein
anschließender Dump genau die erwartete Surface:

- `generator.runtime` vorhanden
- `links.post_emit_health_path` vorhanden
- `links.bundle_surface_validation_path` vorhanden
- `links.bundle_surface_validation_status` = `pass`
- `claim_evidence_map_json` als Artefakt-Rolle vorhanden
- Sidecars (`<stem>.bundle_health.post.json`, `<stem>.bundle_surface_validation.json`)
  existieren neben dem Manifest
- Agent Reading Pack enthält **keine** Legacy-Zeile `claim_evidence_map is not yet produced`

## 3. Runbook

Nach jedem Pull oder Merge in `repos/lenskit` muss der User-Service neu gestartet und ein
frischer Dump geprüft werden — sonst entsteht der oben dokumentierte Klassenfehler.

1. Repo aktualisieren (`git pull` bzw. Merge abschließen).
2. `systemctl --user restart rlens`
3. Neuen Dump auslösen (über die rLens-Web-UI oder direkt per Runner).
4. Neueste `<stem>_merge.bundle.manifest.json` prüfen.
5. Alte Dumps **nicht** als Beleg für aktuellen Codezustand verwenden.

Maschinenlesbare Prüfung:

```bash
bash scripts/rlens-post-merge-surface-smoke.sh /home/alex/lenskit-out
```

## 4. Was diese Doku bewusst **nicht** vorschlägt

- Kein `ExecStartPre=/usr/bin/git …` in `rlens.service`: das wäre eine versteckte
  Schreibaktion im Repo-Working-Tree zur Service-Startzeit und koppelt Service-Start
  an Netzwerk-/Remote-Verfügbarkeit.
- Kein Git-Post-Merge-Hook mit automatischem `systemctl --user restart rlens`: Hooks
  feuern auch in schreibgeschützten Kontexten (CI, Submodule, Read-Only-Klone) und
  würden dort nur Lärm oder Fehler erzeugen.
- Kein Hard-Fail beim Service-Start bei „veraltetem" Code: es gibt keine zuverlässige
  Heuristik, die im Service-Prozess selbst entscheiden kann, ob der Working-Tree neuer
  ist als die eingefrorenen Module — der `cwd` reicht dafür nicht.

Stattdessen: ein **expliziter**, vom Operator ausgelöster Schritt plus ein Smoke-Script,
das jeden frischen Dump gegen die Erwartung prüft.

## 5. Validierung dieses Slices

- `python3 -m scripts.docmeta.check_planning_registration` muss grün sein (TASK-SERVICE-001
  ist registriert).
- `bash scripts/rlens-post-merge-surface-smoke.sh <merges_dir>` läuft gegen den
  realen `merges/`-Pfad und druckt ein JSON-Snapshot des neuesten Manifests.
- `git diff --check` ist sauber.
- `shellcheck scripts/rlens-post-merge-surface-smoke.sh` (optional) ist sauber,
  sofern `shellcheck` installiert ist.

## 6. Abgrenzung

Diese Doku gehört zum operativen Handring und ändert **keine** Bundle-/Surface-Logik.
Die technischen Garantien der Surface-Selbstprüfung leben in
`merger/lenskit/core/bundle_surface_validate.py` und `merger/lenskit/core/runtime_provenance.py`
und sind in `docs/proofs/real-dump-surface-self-check-proof.md` bewiesen.
