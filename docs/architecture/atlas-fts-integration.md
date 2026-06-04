# Atlas FTS Integration Design

Dieses Dokument definiert das Integrationsdesign für SQLite FTS5 in den Atlas-Bounded-Context. Um falsche Finalität zu vermeiden, trennt es explizit zwischen dem belegten Ist-Zustand, dem architektonisch präferierten Zielbild und den noch offenen Implementierungsentscheidungen.

## 1. Ausgangslage und Abgrenzung (Belegter Ist-Zustand)
- **Technologische Basis:** Gemäß der Atlas-Blaupause (Phase 4) und ADR-005 ist SQLite FTS5 als Suchtechnologie vorgesehen und im Repo für Lenskit-Chunks (`chunks_fts`) bereits technologisch etabliert.
- **Aktueller Atlas-Suchmechanismus:** Der aktuelle Suchmechanismus in Atlas (`merger/lenskit/atlas/search.py`) nutzt iteratives, zeilenweises Scannen von JSONL-Inventaren und (für Inhalte) das direkte Lesen vom Live-Dateisystem (`is_text`-Heuristik).
- **Einordnung:** Dieser aktuelle lineare Ansatz ist ein belegter Best-Effort-Übergangszustand, der für kleine Roots ausreicht, aber bei großen Datenmengen als Suchschicht nicht skaliert. Eine explizite FTS-Integration in die Atlas-Artefakte fehlt derzeit.

## 2. Präferiertes Integrationsmodell

Die folgenden Punkte beschreiben die architektonisch präferierte Richtung für die FTS-Integration, basierend auf den bestehenden Invarianten der Blaupause (Zustandsbehaftung, Pipeline-Architektur).

### 2.1 Index-Inhalt
Was sollte in den FTS-Index überführt werden?
*   **Pfade und Metadaten:** `rel_path`, `name`, `ext` und potenziell aufbereitete Zeitstempel/Größen zur gefilterten Volltextsuche.
*   **Dateiinhalte (Content-Search):** Die Indizierung von Dateiinhalten sollte konzeptionell an den `content`-Scan-Modus gebunden sein. Die Text-Extraktion (insbesondere für große Dateien oder non-UTF8) sollte sich an der `TEXT_DETECTION_MAX_BYTES`-Grenze orientieren.
*   **Kombination:** Die FTS-Struktur sollte eine kombinierte Suche über Pfad, Name und Inhalte (z. B. via `content_snippet`-Feld) zulassen, ohne Metadaten-Filterung (z. B. Dateigröße) zu brechen.

### 2.2 Snapshot-Bindung
Wie sollte der Index an die maschinenweite Atlas-Historie gekoppelt sein?
*   **Identität:** Jeder FTS-Eintrag sollte zwingend über `machine_id`, `root_id` und `snapshot_id` eindeutig referenzierbar sein.
*   **Globaler Index (Präferenz):** Ein globaler Index innerhalb der Atlas-Registry (`fts.sqlite`) mit expliziten Snapshot-Referenzen ist aktuell naheliegend, um maschinen- und root-übergreifende Abfragen effizient zu gestalten. (Eine per-Snapshot-Lösung wäre nur bei massiven Isolationsanforderungen geboten).
*   **Historische Suche:** Die Struktur sollte zwischen Suchtreffern aus dem *aktuellsten* Snapshot und historischen Suchanfragen differenzieren können.

### 2.3 Update-Strategie
Wann und wie sollte indexiert werden?
*   **Nachgelagerte Indizierung (Präferenz):** Um den initialen Discovery-Scan (`inventory.jsonl`) nicht zu blockieren, sollte die FTS-Indizierung als nachgelagerter Schritt (z. B. entsprechend der in ADR-003 beschriebenen Derivation Stage oder über einen dedizierten Worker-Prozess) erfolgen. (Eine Inline-Indizierung direkt beim Content-Scan wäre alternativ zu prüfen).
*   **Inkrementelle Updates:** Ein inkrementelles Update basierend auf Delta-Artefakten ist präferiert. Ein vollständiger Rebuild aus `inventory.jsonl` sollte als Fehlerbehebungs-Fallback existieren.

### 2.4 Invalidierung
Wann wird der Index als veraltet betrachtet?
*   **Kaskadierende Löschung:** Wenn ein Snapshot aus der Registry entfernt wird, sollten die zugehörigen FTS-Einträge entfernt oder ungültig markiert werden.
*   **Überschreibung bei Inkrementen:** Bei inkrementellen Updates überschreibt der neue Snapshot logisch die "Latest"-Gültigkeit der alten Datensätze für denselben `rel_path` im selben Root.

### 2.5 Query-Modell
Wie sollte die Suche (`atlas search`) interagieren?
*   **SQL-Translation:** Metadaten-Filter (`--min-size`, `--ext`) und Scope-Filter (`machine_id`, `root_id`) sollten in reguläre `WHERE`-Klauseln übersetzt werden, während `content_query` und `path_pattern` an FTS-Operatoren (`MATCH`) delegiert werden.
*   **Cross-Machine Queries:** Sofern die Snapshots in der Registry verankert sind, sind systemweite Abfragen über die `machine_id` als Index-Dimension nativ möglich.
*   **Hybrider Fallback (Präferenz):** Falls ein Root ohne Content-Enrichment gescannt wurde (oder der Index unvollständig ist), sollte als Fallback auf das direkte Lesen vom Live-Dateisystem (wie in der aktuellen `search.py`) zurückgegriffen werden.

## 3. Architekturentscheidungen (Entschieden — siehe ADR-009)

Die folgenden vier epistemischen Leerstellen wurden vor der Implementierung verbindlich entschieden und in **ADR-009 (`docs/adr/009-atlas-fts-search-index.md`)** dokumentiert. Die Umsetzung liegt in `merger/lenskit/atlas/index.py`.

1.  **Index-Schnitt (Global vs. Per-Snapshot): → GLOBAL.**
    `fts.sqlite` ist ein einziger globaler Atlas-Index unter `<atlas_base>/indexes/fts.sqlite`. Jede Zeile referenziert ihren Ursprung über `machine_id`/`root_id`/`snapshot_id`; cross-machine-Abfragen sind damit nativ. Keine isolierten Per-Snapshot-Dateien.
2.  **Write-Path (Inline vs. Derive): → DERIVE.**
    Die Indizierung erfolgt als nachgelagerter Derivation-Schritt, nachdem der Snapshot geschrieben und als `complete` markiert wurde. Sie ist *best-effort*: ein Indizierungsfehler invalidiert niemals einen ansonsten vollständigen Snapshot, da die Suche transparent auf den linearen Inventar-Scan zurückfällt. `atlas index rebuild` ist der kanonische Vollaufbau-/Reparaturpfad.
3.  **Deletion- und Tombstone-Modell: → HARD DELETE per snapshot_id.**
    Re-Indizierung löscht zuerst die bestehenden Zeilen des Snapshots (idempotent). Keine weichen Tombstones: eine in N+1 gelöschte Datei erscheint schlicht nicht in den Zeilen des neueren Snapshots. Registry-Konsistenz wird durch `atlas index rebuild` (Clear + Re-Derive aus `complete`-Snapshots) und durch die Suchschicht (fragt nur registry-aufgelöste Snapshot-IDs ab) garantiert.
4.  **Default-Query-Semantik (Latest-Only vs. Historisch): → LATEST-ONLY.**
    `atlas search` löst standardmäßig auf den neuesten indizierten Snapshot pro `(machine_id, root_id)` auf (spiegelt das bisherige Verhalten). Historische Suche über alle Snapshots via `--all-snapshots`; ein fixer Zeitpunkt via `--snapshot-id`.

### 3.1 Content-Suche: konservatives FTS-Narrow + Live-Confirm (Hybrid)
Für content-Modus-Snapshots wird der Dateitext in die FTS-`content`-Spalte indiziert. Eine `--content-query` *kann* per FTS-Prefix-`MATCH` die Kandidaten *eingrenzen*; anschließend wird **immer** die Live-Datei gelesen, um den exakten zusammenhängenden Substring-Treffer samt Snippet zu *bestätigen*. Die Live-Bestätigung — nicht FTS — bleibt die Wahrheitsquelle; die bisherige Content-Semantik (case-insensitive Substring, erste Trefferzeile, 200-Zeichen-Snippet) bleibt damit exakt erhalten.

**FTS-Narrowing ist konservativ und nur Beschleuniger.** Da FTS5 tokenbasiert ist, der Legacy-Match aber eine case-insensitive Substring-Suche, grenzt `fts_content_candidates` die Kandidaten nur dann ein, wenn die Einschränkung beweisbar ein *Superset* der echten Substring-Treffer ist: es nutzt Prefix-Queries ausschließlich aus „left-bounded" ASCII-Tokens (ein alphanumerischer Lauf, dem innerhalb der Query ein nicht-alphanumerisches Zeichen vorausgeht und der daher in jedem Treffer-Dokument garantiert einen Token *beginnt*). Für nicht sicher eingrenzbare Queries — Subtoken-Substrings (`oob` ⊂ `foobar`), Nicht-ASCII/Unicode (der `unicode61`-Tokenizer behandelt Akzentbuchstaben als Token-Zeichen), Einzelwort-/Nur-führende-/operatorartige Queries — signalisiert es dem Aufrufer **Live-Scan aller metadaten-gefilterten Kandidaten** (Rückgabe `None`, nicht `[]`). Performanceverlust ist hier akzeptiert; Trefferverlust nicht. **Invariante:** `search(use_index=True, content_query=…)` liefert nie weniger Ergebnis-Keys als `search(use_index=False, …)`.

Snapshots ohne Content-Enrichment fallen für Content-Queries auf das Scannen der (bereits metadaten-eingegrenzten) Kandidaten gegen das Live-Dateisystem zurück.

### 3.2 Was FTS bedient — und was nicht
SQLite ersetzt das erneute JSONL-Parsen und liefert metadaten-gefilterte Kandidaten (Scope, `ext`, Größe, Datum aus indizierten Spalten). Glob-/Name-/Path-Exaktheit sowie die generische `query`-Substring-Prüfung bleiben als Python-Postfilter über den SQL-eingegrenzten Kandidatenzeilen erhalten und werden **nicht** an FTS delegiert; ihre Semantik ist damit byte-genau identisch zum linearen Pfad.
