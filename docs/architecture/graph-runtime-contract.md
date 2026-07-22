# Graph Runtime Contract

**Status:** Verbindlich ab Phase 3
**Geltungsbereich:** Definiert die semantische Bedeutung des Architecture Graphs für die Query- und Eval-Runtime in RepoGround.

---

## 1. Zweck

Der RepoGround-Architekturgraph (`graph_index.json`) dient nicht nur der Visualisierung, sondern fließt als formales, berechenbares Signal in die Such- und Evaluierungspipeline ein. Dieses Dokument definiert die Semantik der Graphelemente und deren exakte Wirkung auf das Retrieval-Ranking.

---

## 2. Ontologie und Semantik

### 2.1 Node (Knoten)
* **Bedeutung:** Ein Knoten repräsentiert eine strukturelle Code-Einheit. Im Standardfall entspricht dies einer Datei (File-Node). Die Granularität kann später auf Module oder Klassen erweitert werden.
* **Identität (`node_id`):** Eindeutiger Identifier. Für Dateien wird üblicherweise `file:<path>` oder der reine `<path>` verwendet.
* **Erreichbarkeit:** Ein Knoten gilt als erreichbar, wenn ein Pfad von mindestens einem Entrypoint zu ihm existiert.
* **Inventarknoten:** Datei-Knoten für nicht-Pythonische Quellen können reine Inventar- und Navigationsknoten sein. Ihre Existenz belegt die Datei im gebundenen Retrieval-Snapshot, aber keine Abhängigkeit, Laufzeitkausalität oder Erreichbarkeit.

### 2.2 Edge (Kante)
* **Bedeutung:** Eine gerichtete Kante (`src` → `dst`) repräsentiert eine Abhängigkeit.
* **Beispiel:** `src` importiert oder ruft `dst` auf. Wenn `A` von `B` abhängt (z.B. `A` importiert `B`), zeigt die Kante von `A` nach `B`.
* **Traversierung:** Die Traversierung für die Distanzberechnung erfolgt entlang dieser gerichteten Kanten (von den Entrypoints in die Tiefe der Abhängigkeiten).
* **Producer-Grenze:** Der aktuelle `architecture.graph.v1`-Producer erzeugt statische Importkanten ausschließlich aus geparstem Python-AST. Cross-Language-Dateiknoten werden nicht still zu Kanten hochgestuft. Das Fehlen einer Kante für Rust, TypeScript, Svelte, SQL, YAML oder andere Inventarsprachen ist daher kein Beleg für das Fehlen einer fachlichen Abhängigkeit.

### 2.3 Entrypoint
* **Bedeutung:** Entrypoints sind definierte Einstiegspunkte in das System (z.B. `main.py`, API-Routen, CLI-Befehle).
* **Funktion:** Sie dienen als Ausgangspunkte (Wurzeln) für die Distanzberechnung. Entrypoints haben per Definition die Distanz `0`.

### 2.4 Distance (Distanz)
* **Bedeutung:** Die minimale Anzahl von Kanten (Hops) von einem beliebigen Entrypoint zu einem Knoten.
* **Gerichtetheit:** Die Distanz ist gerichtet. Ein Modul, das von einem Entrypoint importiert wird, hat Distanz 1. Ein Modul, das den Entrypoint importiert (was meist architektonisch vermieden wird), hat keine automatische Erreichbarkeit aus dieser Richtung.
* **Unreachable (Nicht erreichbar):** Knoten, zu denen kein Pfad von einem Entrypoint existiert, erhalten intern den Distanzwert `-1` (oder werden nicht im Distanz-Mapping geführt). Sie erhalten keinen Graph-Bonus.

---

## 3. Runtime-Wirkung (Scoring)

Das Graph-Signal wird als additiver Bonus in die Score-Komponenten integriert. Es darf lexikalische und semantische Signale unterstützen, aber nicht vollständig überstimmen (Tie-Breaker und Verstärker).

### 3.1 Score-Formel

```python
graph_proximity = f(distance)
entrypoint_boost = g(distance)

raw_graph_bonus = (w_graph * graph_proximity) + (w_entry * entrypoint_boost)

cap = w_graph + w_entry
graph_bonus = min(raw_graph_bonus, cap)

score_pre = (w_bm25 * bm25_norm) + graph_bonus
final_score = score_pre * current_penalty
```

*Hinweis:* Der Graph-Bonus wird implizit durch die Summe der eigenen Gewichte (`w_graph + w_entry`) gecappt. Penalties (z.B. für Tests) wirken multiplikativ auf den Gesamtscore. Der Graph dient primär als Verstärker / Tie-Breaker.

### 3.2 Definition der Bonus-Werte

* **Distanz 0 (Entrypoint):**
  * `graph_proximity = 1.0`
  * `entrypoint_boost = 1.0`
* **Distanz > 0 (Reachable):**
  * `graph_proximity = 1.0 / (distance + 1.0)`
  * `entrypoint_boost = 0.0`
* **Distanz -1 / Unreachable:**
  * `graph_proximity = 0.0`
  * `entrypoint_boost = 0.0`

### 3.3 Caps und Begrenzungen
* Der Producer begrenzt den verarbeiteten Repository-Snapshot deterministisch auf maximal 50.000 Quelldateien und 512 MiB Quellmaterial. `coverage.repository_truncated` zeigt eine gekappte Auswahl explizit an; `repository_files_*` und `repository_bytes_*` machen Umfang und Grenze sichtbar.
* Der Graph-Bonus ist durch die Gewichtungsfaktoren (`w_graph`, `w_entry`) strikt nach oben begrenzt.
* Ein lexikalischer "perfect match" ohne Graph-Verbindung wird typischerweise immer noch höher gerankt als ein schwacher lexikalischer Treffer mit perfekter Graph-Verbindung, abhängig von der exakten Parameterisierung der Gewichte.

---

## 4. Fehlerpfade und Diagnose

Fehlt das Artefakt `graph_index.json`, ist es ungültig, kann es nicht validiert werden oder verweist es auf einen anderen Dump-Index, bricht die Query-Runtime nicht hart ab. Stattdessen:
* Die Suche wird im "Baseline"-Modus ohne Graph-Bonus und ohne graph-bedingte Penalty ausgeführt.
* Der erkannte Graph-Status bleibt im `explain`-Objekt sichtbar.

Das `explain`-Objekt der Query enthält Diagnoseinformationen zur Graph-Nutzung.

### 4.1 `graph_used`

Gibt an, ob ein geladener Graph tatsächlich in das Ranking eingeflossen ist:
* `true` → Nur ein Graph mit `graph_status = "ok"` wurde im Scoring verwendet.
* `false` → Es wurde kein Graph im Scoring verwendet, z. B. bei `graph_status = "not_found"`, `"invalid_json"`, `"invalid_schema"`, `"validation_unavailable"`, `"stale_or_mismatched"`, `"unreadable"` oder `"invalid_path"`.

Ein `stale_or_mismatched` Graph bleibt ein Diagnoseartefakt. Er darf weder Graph-Proximity noch Entrypoint-Bonus, Graph-Gewichte oder eine graph-bedingte Test-Penalty in den finalen Score einbringen.

### 4.2 `graph_status`

Gibt detailliert Auskunft über den Zustand des geladenen Graphen. Folgende Werte sind definiert:

* `ok` → Graph erfolgreich geladen, validiert und an denselben Dump-Index gebunden.
* `not_found` → Datei nicht gefunden.
* `invalid_json` → Datei konnte nicht als JSON geparst werden.
* `invalid_schema` → JSON entspricht nicht dem `architecture.graph_index` Contract.
* `validation_unavailable` → Validierungsbibliothek oder Schema fehlt; der Graph bleibt diagnostisch und wird nicht gerankt.
* `stale_or_mismatched` → Graph verweist auf einen anderen Dump-Index (Hash-Mismatch); Diagnose bleibt sichtbar, Ranking fällt auf Baseline zurück.
* `unreadable` → IO-Fehler (z.B. fehlende Leserechte).
* `invalid_path` → Der relative Artefaktpfad verletzt die Root-Grenze; der Graph wird nicht geladen.

## 5. Pfad-Sicherheitsgrenze

Ein explizit gewählter Graph Index muss entweder als einfacher Geschwister-Dateiname angegeben werden oder als absoluter Pfad, dessen lexikalischer Elternordner dem Ordner des SQLite-Index entspricht. Die Query-Runtime löst den nutzerbestimmten Graph-Pfad nicht im Dateisystem auf. Sie übergibt ausschließlich den geprüften Dateinamen an den root-gebundenen Loader, der den gemeinsamen Pfad-Sicherheitshelfer verwendet.

Ein Verstoß gegen diese Ortsgrenze ist ein harter Aufruferfehler. Ein vom Loader abgewiesener relativer Pfad erhält den Status `invalid_path`. In keinem dieser Fälle darf der Graph in das Ranking einfließen.
