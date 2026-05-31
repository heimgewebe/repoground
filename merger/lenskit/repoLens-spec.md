# REPOLENS SPEC v2.4

(Normative Spezifikation)

## Navigation & Anchors (Renderer Robustness)

Viele iOS/Preview-Renderer erzeugen keine stabilen Heading-IDs und/oder strippen HTML.
Der Report emittiert daher **mehrschichtige Navigation**:

- sichtbare Suchmarker: `§§ <token>` (immer auffindbar, auch wenn Links tot sind)
- HTML Anchor: `<a id="<token>"></a>` (wenn HTML zugelassen ist)
- tokenisierte Headings: `## <token>` (wenn Heading-IDs erzeugt werden)

Alle internen Links verwenden nur Tokens (`#manifest`, `#index`, `#file-...`).

## Render Mode

Der Report weist den Modus explizit aus:
`Render Mode: full | code-only | plan-only`

## 1. Zweck

Der repoLens erzeugt aus Working-Copy-Repositories KI-optimierte, strukturierte Hyper-Merges.
Diese dienen KIs als Navigations- und Arbeitsfläche, ähnlich einer Mini-IDE.

---

## 2. Invariante Struktur des Merges (strict ordering)

Jeder Merge folgt exakt dieser Reihenfolge:
1.  Source & Profile
2.  Profile Description
3.  Reading Plan
4.  Plan
5.  📁 Structure
6.  🧾 Manifest
7.  📄 Content

Fehlt ein Abschnitt → Fehler.

Reihenfolge falsch → Fehler.

---

## 3. Spec-Version-Pinning

Header muss enthalten:

- Spec-Version: 2.4

---

### Super-Merger / Extras — implementiert (2026-05)

> **Status: implementiert.** `ExtrasConfig` und die Extras-Schalter sind in
> `merger/lenskit/core/merge.py` umgesetzt (`class ExtrasConfig`,
> `_build_extras_meta()`, Emission in den `@meta`-Block). Beleg:
> `docs/proofs/weiterentwicklungsplan-2026-05-reconciliation-proof.md` §2 (Zeile 1)
> und `docs/proofs/doc-freshness-registry-v0-proof.md`. Dieser Abschnitt
> dokumentiert daher den **umgesetzten** Extras-Contract; er ist kein offenes TODO
> mehr. Drift wird durch den Doc-Freshness-Eintrag
> `repolens-spec-super-merger-extras` überwacht.

Der Super-Merger-Ausbau umfasst die folgenden, umgesetzten Punkte:

1. **Extras-Schalter in der UI implementieren**
   - Flags in `MergerUI`:
     - Repo Health Checks
     - Organism Index
     - Fleet Panorama (Multi-Repo)
     - Delta Reports (wenn Diff vorhanden)
     - Augment Sidecar (Playground-Block)
     - JSON Sidecar (maschinenlesbarer Zwilling)
     - Heatmap (Alias im CLI akzeptiert: `ai_heatmap` → `heatmap`)
   - Alle Extras müssen rein additive Textblöcke sein.
     Nichts an der Kernstruktur (Source & Profile → … → Content) entfernen oder umsortieren.

   ```python
   @dataclass
   class ExtrasConfig:
       health: bool = False
       organism_index: bool = False
       fleet_panorama: bool = False  # Nur für Multi-Repo-Merges
       augment_sidecar: bool = False
       delta_reports: bool = False
       json_sidecar: bool = False
       heatmap: bool = False  # CLI alias: ai_heatmap
   ```

2. **Header / Meta konsistent machen**
   - `Declared Purpose` je Profil korrekt setzen:
     - overview → `Tools – Index`
     - summary → `Tools – Doku/Kontext`
     - dev → `Tools – Code/Review Snapshot`
      - machine-lean → `Tools – Machine-Lean`
      - max → `Tools – Vollsnapshot`
   - Coverage-Zeile ergänzen, z. B.:
     - `Coverage: 17/35 Dateien mit vollem Inhalt`
   - **Meta-Drosselung (Throttling)** einführen (siehe Abschnitt 3e).
   - Im `@meta`-Block:
     - `merge.extras.*`-Flags für alle aktivierten Extras ergänzen.
     - `merge.meta_density` (min, standard, full, auto) ergänzen.
     - Schema `repolens-report.schema.json` entsprechend erweitern.
     - Beispiel:

       ```yaml
       merge:
         extras:
           health: true
           organism_index: true
           fleet_panorama: true
           augment_sidecar: true
           delta_reports: true
           json_sidecar: true
           heatmap: true
       ```

3. **Multi-Part-Merges klar kennzeichnen**
   - Dateinamen bleiben im bisherigen Schema (`…_part1_merge.md`, `…_part2_merge.md`, …).
   - Im Header jeder Datei:
     - `# WC-Merge Report (Part N/M)` setzen (bei Single-Part-Merges `1/1`).

4. **Validierung**
   - Alle Änderungen strikt gegen `repolens-report.schema.json` und die oben definierte Abschnittsreihenfolge prüfen.
   - Keine neuen Kategorien/Tags einführen, solange die Spec nicht explizit erweitert wird.

---

## 3a. Größenlimits (Size Behaviour)

- Es gibt **kein hartes globales Merge-Size-Limit**.
- `max_file_bytes` begrenzt ausschließlich die **einzelne Datei**
  (Trunkierung bzw. optionales Splitting auf Dateiebene).
- `split_size` steuert optional die **Aufteilung des Merges in mehrere Dateien**:
  - `split_size <= 0` → kein Split (ein einziger Merge).
  - `split_size > 0` → Multi-File-Merge, Inhalt wird nur über mehrere Dateien verteilt,
    aber nicht zusätzlich gekürzt.

Konsequenz:

> „Wenn Inhalt fehlt, liegt das an Profil-/Dateifiltern oder `max_file_bytes`, **nicht** an einem globalen Hard-Limit.“

KIs dürfen davon ausgehen, dass es auf Merge-Ebene keine „unsichtbare Schere“ gibt,
sondern nur explizit deklarierte Filter und Limits.

Optional:

- Spec-Checksum: <sha256>

---

## 3b. Merge-Contract & Rollout (Normative)

Jeder repoLens-Report implementiert einen formalen „Merge-Contract“.
Ziel:

- eindeutige Identifikation des Formats,
- maschinenlesbare Versionierung,
- Basis für externe Validatoren und CI-Checks.

### Compatibility & Rollout Rule

Contracts are strictly versioned. Therefore:

1.  **Paired Change Rule:** Any change that introduces or tightens required fields in a schema **MUST** be merged together with an updated producer implementation and tests.
2.  **No-Legacy Acceptance:** Consumers and validators **MUST NOT** accept legacy flat formats.
3.  **CI as Gate:** The repository CI **MUST** fail if the current producer output does not validate against this schema.

### Mandatory Fields

Im Abschnitt **Source & Profile**:

- `Contract: repolens-report`
- `Contract-Version: 2.4`

Im `@meta`-Block (eingebettet in HTML-Kommentare `<!-- @meta:start -->` ... `<!-- @meta:end -->`):

```yaml
merge:
  contract: "repolens-report"
  contract_version: "2.4"
```

- Es gibt **kein hartes globales Merge-Size-Limit**.
- `max_file_bytes` begrenzt ausschließlich die **einzelne Datei**
  (Trunkierung bzw. optionales Splitting auf Dateiebene).
- `split_size` steuert optional die **Aufteilung des Merges in mehrere Dateien**:
  - `split_size <= 0` → kein Split (ein einziger Merge).
  - `split_size > 0` → Multi-File-Merge, Inhalt wird nur über mehrere Dateien verteilt,
    aber nicht zusätzlich gekürzt.

Konsequenz:

> „Wenn Inhalt fehlt, liegt das an Profil-/Dateifiltern oder `max_file_bytes`, **nicht** an einem globalen Hard-Limit.“

KIs dürfen davon ausgehen, dass es auf Merge-Ebene keine „unsichtbare Schere“ gibt,
sondern nur explizit deklarierte Filter und Limits.

Optional:

- Spec-Checksum: <sha256>

## 3c. Hub Path (Configuration)

repoLens speichert den Hub-Pfad in `.repolens-hub-path.txt` im Skript-Verzeichnis, um Umbenennungen (z. B. `wc-hub` -> `repolens-hub`) robust zu überstehen.

**Hub setzen:**
1. Öffne den gewünschten Hub-Ordner (z. B. `wc-hub`) in Pythonista als Working Directory.
2. Führe `repolens-hub-pathfinder.py` aus.
3. Starte `repolens.py` neu.

## 3d. Profil- und Modus-Flags

- `level` (string)
  - `overview`, `summary`, `dev`, `max`
  - steuert Umfang und Detailgrad des Inhalts

- `path_filter` (string, optional)
  - Wirkt als **harter Include-Filter** für Manifest und Content.
  - Nur Dateien, deren Pfad den Filter-String enthält (Substring), werden aufgenommen.
  - Dies überschreibt auch "Force Include"-Regeln (z. B. README oder .ai-context), falls diese nicht matchen.

- `plan_only` (bool)
  - `false` (Default): Voll-Merge entsprechend Profil (inkl. Structure / Manifest / Content)
  - `true`: PLAN-ONLY-Modus
    - Ausgabe enthält:
      - Header („Source & Profile“)
      - Profilbeschreibung
      - **Reading Plan** (mit explizitem Hinweis auf Plan-Only)
      - `@meta`-Block
    - keine `Structure`-, `Manifest`- oder `Content`-Sektionen

- `meta_none` (bool)
  - `false` (Default): Standardverhalten
  - `true`: META-NONE-Modus
    - **One Knob, Output State:** `meta_none` ist der Eingabeparameter. Das Resultat im Sidecar ist `meta.mode="none"`.
    - Deaktiviert alle epistemischen und interpretativen Meta-Schichten:
      - Keine Epistemic Charter / Declaration
      - Keine Reading Lenses
      - Keine Interpretativen Marker (Augment, Heatmap, Risk)
    - Setzt `@meta.mode = "none"` und `@meta.warning = "interpretation_disabled"` (Felder erscheinen nur im none-Modus).
    - Hält alle strukturellen Sicherheits-Invarianten (Path Security, Contract Version, Manifest) aufrecht.
    - Zweck: Referenz- und Diagnosemodus für Rohsicht auf Inhalte.

### KI-Lesepfad-Minimum (nur Output, keine Configs)

Dieser Abschnitt definiert den minimalen Lesepfad für KIs, die
nur die Merge-Datei sehen – nicht den ausführenden Code und
nicht die Profile/Configs.

- Schritt 1 – @meta lesen:
  - KIs sollen zuerst den merge-Block lesen (Profil, Scope, Limits,
    `generated_at`). Der Block beschreibt, wie der Merge erzeugt wurde,
    ohne dass die KI Zugriff auf die ausführende Umgebung braucht.

- Schritt 2 – Manifest nutzen:
  - Das Manifest ist der zentrale Index über alle Dateien. KIs sollen es
    nutzen, um relevante Dateien zu identifizieren und zielgerichtet in
    die entsprechenden Abschnitte zu springen.

- Schritt 3 – Datei-Blöcke:
  - Jeder Datei-Block ist in Markdown sauber abgegrenzt, inkl. Rücksprung-
    Links zum Manifest. Es gibt keine versteckten Bedeutungen; KIs sollen
    die Inhalte so lesen, wie sie sind – ohne eigene Struktur in den Merge
    „hineinzuphantasieren“.

## 3e. Meta-Drosselung (Meta Density)

Um bei kleinen Merges (z. B. 3 Dateien) den Overhead zu minimieren, wird eine Drosselung (`meta_density`) eingeführt. Diese Tabelle definiert die Block-Sichtbarkeit verbindlich (Contract):

| Feature / Block | `min` | `standard` | `full` |
| :--- | :--- | :--- | :--- |
| **File Header** | Path only | No MD5 | Full (Path, Cat, Tags, Size, MD5) |
| **file_meta** | Nur bei `partial`/`truncated` | Nur bei `partial`/`truncated` | Immer |
| **Index** | Reduziert (Hinweis) | Standard | Standard |
| **Hotspots** | 0 (aus) | Max 3 pro Lens | Max 8 pro Lens |
| **Zweck** | Minimale Token-Last | Fokus auf Inhalt | Vollständige Auditierbarkeit |

**Auto-Logik (`meta_density=auto`):**
- Wenn `path_filter` oder `ext_filter` aktiv sind → `standard` (mit Warnhinweis "Auto-Drosselung").
- Sonst → `full`.

---

## 4. Kategorien

Erlaubte Werte:
- source
- doc
- config
- test
- contract
- other

(Hinweis: `ci` ist als Tag implementiert, nicht als eigene Kategorie.)

Neue Kategorien dürfen nicht entstehen.

---

## 5. Tags

Erlaubte Tags:
- ai-context
- runbook
- lockfile
- script
- ci
- adr
- feed
- wgx-profile

Jede Datei darf 0–n Tags haben.
Neue Tags sind verboten, außer Spec wird geändert.

---

## 6. Hyperlink-Schema (Pflicht)

### 6.1 Datei-Anchor (Pflicht)

Jede Datei im Content-Bereich erhält einen Anchor:

`<a id="file-<root>-<path-without-slashes>"></a>`

Regeln:
- `/` → `-`
- `.` → `-`

Beispiel:

`tools/merger/merge_core.py`
→ `file-tools-merger-merge_core-py`

---

### 6.2 Manifest-Link (Pflicht)

Pfadspalte:

[`<path>`](#file-<root>-<path>)

---

### 6.3 Strukturbaum-Link (optional)

📄 [filename](#file-…)

---

### 6.4 Repo-Anchor (Pflicht bei Multi-Repo)

`## 📦 tools {#repo-tools}`

---

### 6.5 Backlink (Pflicht)

Jeder Datei-Contentblock endet mit:

`[↑ Zurück zum Manifest](#manifest)`

---

## 7. Manifest-Anker

Oberhalb Manifest:

`## 🧾 Manifest {#manifest}`

---

## 8. Navigation-Indexe

Vor dem Manifest:

```markdown
## Index
- [Source Files](#cat-source)
- [Docs](#cat-doc)
- [Config](#cat-config)
- [Contracts](#cat-contract)
- [Tests](#cat-test)
- [CI Pipelines](#tag-ci)
- [WGX Profiles](#tag-wgx-profile)
```

Für jede Kategorie:

```markdown
## Category: source {#cat-source}
- [file](#file-...)
```

Für Tags (z. B. CI):

```markdown
## Tag: ci {#tag-ci}
- [file](#file-...)
```

---

## 9. Non-Interpretation Guard

Regeln:
- Keine Rateversuche.
- Unklare Klassifikation → other.
- Unklare Tags → keine Tags.
- Unklare Repo-Beschreibung → leer.

---

## 10. Repo-Zweck-Auslesung (safe)

Der Merger liest nur:
1.  README.md (erster Absatz)
2.  docs/intro.md (erster Absatz)

Keine weiteren Quellen. Keine Interpretation.

Output:

`- Declared Purpose: <ausgelesener Absatz>`

---

## 11. Debug Mode

CLI: `--debug`

Mindestinformationen:
- unbekannte Kategorien
- unbekannte Tags
- Dateien ohne Anchor
- Dateien ohne Manifest-Eintrag
- Dateien ohne Tags
- kollidierende Anchors
- Section-Ordering-Check-Report

---

## 12. Strict Validator

Jede Ausgabe wird auf folgende strukturelle Integrität geprüft:
- Abschnittsreihenfolge
- Spec-Version & Contract-Header vorhanden
- Manifest-Anker vorhanden

Erweiterte Prüfungen (z.B. unbekannte Tags/Kategorien, fehlende Anker) erfolgen im **Debug-Modus** oder als Warnungen und verhindern im Standardbetrieb nicht zwingend die Ausgabe, sollten aber behoben werden.

Fehler in der Grundstruktur → kein Merge wird geschrieben.

---

## 13. Agent Contract (JSON Sidecar)

Falls ein JSON Sidecar generiert wird (`artifacts.index_json`), gelten folgende Feld-Definitionen für die stabile Navigation (Contract v2):

### 13.1 Content References

`files[].content_ref`:
- `marker` (string): Exakter Substring, der im Markdown vorkommt. Muss zwingend Anführungszeichen enthalten (z. B. `file:id="FILE:..."`).
- `selector` (object, optional): Strukturierter Parser-Pfad.
  - `kind`: `html_comment_attr`
  - `tag`: `file`
  - `attr`: `id`
  - `value`: Die ID (z. B. `FILE:f_...`)

### 13.2 Markdown References

`files[].md_ref`:
- `anchor` (string): Der HTML-ID-String ohne `#` (für `<a id="...">`).
- `fragment` (string): Der vollständige Link-Fragment-Identifier inkl. `#` (für URL-Navigation).

### 13.3 Rollout & Compatibility (Normative)

- **Paired Change Rule**: Änderungen am Schema (`repolens-agent.v*.schema.json`) müssen zeitgleich mit Updates an `merge.py` (Producer) und den Regression-Tests erfolgen.
- **No-Legacy Acceptance**: Consumers sollen strikt gegen die angegebene `contract_version` validieren. Veraltete Versionen (z. B. v1) werden nicht "best effort" unterstützt, sobald v2 etabliert ist.
- **CI as Gate**: Die Einhaltung des Contracts (Schema-Validierung) ist Teil der CI-Pipeline und darf nicht fehlschlagen.

## 14. Prescan Pool Semantics (Spec Extension)

Dieses Kapitel definiert die Semantik für persistierte Selektionen („Pools“) im Frontend (z. B. Pythonista, WebUI).

### 14.1 Structured Entry Contract

Ein Pool-Eintrag kann entweder eine einfache Liste (Legacy) oder ein strukturiertes Objekt sein.

**Strukturiertes Format:**
```json
{
  "raw": ["file1", "file2"],
  "compressed": ["dir1/"]
}
```

**Semantik-Tabelle:**

| `compressed` Value | Bedeutung | Semantik |
| :--- | :--- | :--- |
| `null` (JSON) | **ALL** | Es gibt keine Einschränkung. Alle Dateien werden einbezogen (Standard-Filter gelten weiterhin). (Python: `None`) |
| `[]` (empty list) | **BLOCK** | Nichts wird einbezogen. Explizite Blockierung. |
| `["..."]` | **PARTIAL** | Nur die gelisteten Pfade (und deren Kinder) werden einbezogen. |

**Invariante:**
- `compressed: null` ist der einzige Weg, **ALL** im strukturierten Format auszudrücken.
- Ein leeres Array `[]` bedeutet immer **BLOCK**, niemals **ALL**.

## 15. Frontend Feature Parity (Normative)

To ensure a consistent experience across all UIs, every **interactive** frontend implementation (WebUI, Pythonista) **MUST** expose the following configuration controls to the user. CLI implementations **MUST** expose equivalent command-line arguments.

| Control | Type | Values | Default | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **Level** | Select | `overview`, `summary`, `dev`, `max` | `dev` | Detail level of the report. |
| **Mode** | Select | `gesamt` (Combined), `pro-repo` | `gesamt` | Batching strategy. |
| **Split Size** | Input | String (e.g., `25MB`, `0`) | `25MB` | Threshold for splitting output files. |
| **Max Bytes** | Input | String (e.g., `0`, `5MB`) | `0` | Per-file truncation limit (`0`=unlimited). |
| **Meta Density** | Select | `auto`, `min`, `standard`, `full` | `auto` | Metadata verbosity throttle. |
| **Plan Only** | Boolean | `true`/`false` | `false` | Skip content generation. |
| **Code Only** | Boolean | `true`/`false` | `false` | Filter strictly for code files. |
| **Extras** | Multi-Select | `json_sidecar`, `augment_sidecar`, `health`, etc. | `json_sidecar, augment_sidecar` | Optional analytics modules. |

**Divergence Rule:**
If a new parameter is added to the backend `JobRequest` model, it **MUST** be added to all frontends within the same release cycle.
