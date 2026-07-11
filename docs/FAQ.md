# FAQ

> Aktualisiert am 2026-05-31.
> Praxisfragen rund um Lenskit. Einstieg: [Getting Started](GETTING_STARTED.md);
> Begriffe: [Glossar](glossary.md).

## Bedienung

### Welches Frontend nehme ich — repoLens oder rLens?
- **repoLens** (`python3 -m merger.lenskit.frontends.pythonista.repolens …`) für
  lokale/iPad-/Pythonista-Aufrufe und CLI-Dumps.
- **rLens** (Service/Web-UI) als Heim-PC/Server-Schicht. Beide sind
  funktionsgleich — neue Features müssen in beiden existieren (Parität).

### Wie scanne ich nur bestimmte Ordner oder Dateitypen?
Über Filter-Flags von repoLens:

```bash
# Nur docs/
python3 -m merger.lenskit.frontends.pythonista.repolens . --path-filter docs/

# Nur Markdown + Python
python3 -m merger.lenskit.frontends.pythonista.repolens . --extensions .md,.py

# Nur Code/Test/Config/Contract-Kategorien
python3 -m merger.lenskit.frontends.pythonista.repolens . --code-only
```

> Sobald ein Filter aktiv ist, schaltet `--meta-density auto` automatisch auf
> `standard` (weniger Overhead).

### Was bedeutet `--meta-density auto`?
`auto` wählt automatisch: **`full`** bei vollständigem Dump ohne Filter,
**`standard`** sobald ein Pfad-/Endungsfilter aktiv ist. Explizit überschreibbar
mit `min` | `standard` | `full`.

### Welche Datei sollte ein LLM-Agent zuerst lesen?
`*.agent_reading_pack.md`. Es ist **Navigation, nicht Wahrheit**: Lese-Policy,
Artefaktrollen, Suchanleitung (CLI-Befehle), Health-Verdict und Top-Chunk-Spans.
Zitiert wird danach gegen `canonical_md` (`*.merge.md`).

### Wie regeneriere ich Agent-Pack / Citation-Map / Health?
```bash
python3 -m merger.lenskit.cli.main agent-pack produce <bundle.manifest.json> --json
python3 -m merger.lenskit.cli.main citation produce <bundle.manifest.json> --json
python3 -m merger.lenskit.cli.main bundle-health post <bundle.manifest.json>
```

## Fehlerbehebung

### Was tun bei Range-Ref-Fehlern?
Häufige Meldungen aus dem Range-Resolver:

- **`range_ref failed schema: …`** — der `range_ref` erfüllt das Schema nicht
  (Pflichtfeld fehlt, leerer/ungültiger `content_sha256`). Ref nicht von Hand
  bauen; aus dem aktuellen Bundle beziehen.
- **`Hash mismatch` / `Artifact content hash mismatch` / `Range content hash
  mismatch`** — der referenzierte Inhalt passt nicht mehr zum Bundle (meist:
  Bundle veraltet oder Datei geändert). **Bundle neu erzeugen** und den Ref aus
  dem neuen Lauf nehmen.
- **`out of bounds for file size`** — Byte-Bereich liegt außerhalb der Datei;
  Ref stammt aus einem anderen Lauf.
- **`attempts to escape the repository/manifest directory` / `must be a relative
  path`** — Pfad-Traversal-Schutz: `range_ref`-Pfade müssen relativ und
  bundle-/repo-intern sein.

Auflösung testen:
```bash
python3 -m merger.lenskit.cli.main range get --manifest <bundle.manifest.json> --ref ref.json
```

### Der FTS-Index ist leer — warum?
Entweder enthält das Repo keinen indexierbaren Text (dann ist leere FTS ein
*Diagnose*-/Profil-Zustand, kein Content-Fehler), oder es wurde mit
`--output-mode archive` (nur Markdown, kein Index) gebaut. Für Suche mit
`--output-mode dual` oder `retrieval` neu erzeugen.

### `output_health` meldet einen Fail — was prüft es?
U. a. `fts_content_non_empty`, `range_ref_resolution_ok`, `canonical_md_hash_ok`.
Ein Fail zeigt, dass das Bundle seine eigenen Konsistenz-Checks nicht besteht
(z. B. Hash-Mismatch des kanonischen Markdowns). Bundle neu erzeugen und Quelle
des Fails im JSON ansehen.

### „Forensic strict" ist nicht verfügbar.
`forensic_strict` ist die strengste Evidence-Stufe und erfordert eine vorhandene
`claim_evidence_map`. Dieses Artefakt ist noch nicht implementiert (geplant:
output-optimierung Arbeitspaket F), daher ist die Stufe aktuell „blocked until
available". Niedrigere Evidence-Stufen funktionieren normal.

### Atlas verweigert einen Pfad.
Atlas akzeptiert nur `preset`, server-signierte `token` oder absolute Pfade
(`abs_path`). Relative Pfade und `..`-Traversal werden strikt abgewiesen.

## Entwicklung

### Wie führe ich Tests und Lint lokal aus?
```bash
python3 -m pip install --require-hashes -r requirements/repobrief-dev.lock.txt
python3 -m pytest
ruff check --select=F401,F811 --exclude='**/fixtures/**' .
```

### Ich habe `JobRequest` oder die UI geändert — was nun?
Parität sicherstellen:
```bash
python3 tools/parity_guard.py
```
Das Feld muss in repoLens-CLI **und** rLens-WebUI existieren. Siehe
[CONTRIBUTING](../CONTRIBUTING.md) und [PARITY_GUARD](PARITY_GUARD.md).

### Wo ist „die Wahrheit"?
Immer `canonical_md` (`*.merge.md`). Index, Citation-Map, Agent-Pack, Graph und
Health sind Navigation/Diagnose und ersetzen den kanonischen Dump nie.

### Ein Feature im „Plan" fehlt angeblich — stimmt das?
Wahrscheinlich nicht. Viele extern als „fehlend" gelistete Features sind bereits
umgesetzt; siehe
`docs/proofs/weiterentwicklungsplan-2026-05-reconciliation-proof.md`. Vor dem
Bauen mit `rg`/`test -f` prüfen (Diagnose-first).
