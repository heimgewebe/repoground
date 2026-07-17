# WC-Merger Super-Merger – Implementation Notes (Spec v2.3)

## Stage 3: Delta Layer

**Purpose:** Änderungen zwischen Repository-Snapshots tracken.

### Implementierung

- eigener Delta-Contract `repolens-delta.schema.json`
- Delta-Metadaten im `@meta`-Block des Haupt-Merges
- UI-Button „Delta from Last Import“ nutzt weiterhin `repolens-extractor.py` für die eigentliche Delta-Berechnung

### Schema-Struktur (Meta-Ausschnitt)

```json
{
  "delta": {
    "type": "repolens-delta",
    "base_import": "2025-12-01T22:14:00Z",
    "current_timestamp": "2025-12-07T12:30:00Z",
    "summary": {
      "files_added": 5,
      "files_removed": 2,
      "files_changed": 17
    }
  }
}
```

---

## Stage 4: Augment Layer

**Purpose:** Sidecar-Intelligenz für KI-Agenten bereitstellen.

### Implementierung

- Augment-Sidecar-YAML (z. B. `tools_augment.yml`)
- automatische Erkennung des Sidecars in `merge_core.py`
- Verlinkung im `@meta`-Block
- Extras-Toggle „augment_sidecar“ in UI & Headless-Mode

### Beispiel-Sidecar

```yaml
augment:
  version: 1

  hotspots:
    - path: merger/repoLens/merge_core.py
      reason: "Complex branching logic"
      severity: "medium"

  suggestions:
    - "Extract profile logic into strategy pattern"
    - "Add comprehensive unit tests"

  risks:
    - "Large merges may exhaust memory"

  priorities:
    - priority: 1
      task: "Complete super-merger roadmap"
      status: "complete"
```

---

## Stage 5: Meta & Coherence

**Purpose:** Konsistenz, Validierung und Spec-Konformität sicherstellen.

### Implementierung

- `repolens-report.schema.json` um `extras`, `health`, `delta`, `augment` erweitert
- Contract-Validator `validate_merge_meta.py`
- alle generierten Reports validieren gegen die Schema-Contracts
- standardisierte Header („Part N/M“) für Multi-Part-Merges

### Extras-Konfiguration

Alle Features sind über ein `ExtrasConfig`-Dataclass konfigurierbar:

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

**Wichtig:** `fleet_panorama` wird nur bei Multi-Repo-Merges (2+ Repos) aktiviert, auch wenn das Flag in `ExtrasConfig` gesetzt ist. Bei Single-Repo-Merges erscheint weder das Flag im Meta noch der Fleet Panorama-Block im Report.

### Report-Struktur (Spec v2.3)

1. Source & Profile
2. Profile Description
3. Reading Plan
4. Plan
5. Health Report (optional, extras.health)
6. Organism Index (optional, extras.organism_index)
7. Fleet Panorama (optional, extras.fleet_panorama)
8. Structure
9. Manifest
10. Content

### @meta-Block (vollständiges Beispiel)

```yaml
merge:
  spec_version: "2.3"
  profile: "dev"
  contract: "repolens-report"
  contract_version: "2.3"
  # ... standard fields ...
  extras:
    health: true
    organism_index: true
    fleet_panorama: true
    augment_sidecar: true
    delta_reports: true
    json_sidecar: true
    heatmap: true
  health:
    status: "ok"
    missing: ["contracts"]
  delta:
    enabled: true
  augment:
    sidecar: "tools_augment.yml"
```

### Backward-Kompatibilität

- Reports ohne Extras bleiben unverändert
- Extras-Felder sind optional im Contract
- alte Reports validieren weiterhin gegen das Schema

---

## Files / Komponenten

- `merge_core.py`
  - HealthCollector
  - Organism Index
  - Fleet Panorama
  - Augment-Sidecar-Support
  - Delta-Metadaten im `@meta`-Block

- `repolens.py`
  - UI-Toggles für Extras (bereits vorhanden)

- `repolens-report.schema.json`
  - Extras, Health, Delta, Augment-Felder

- `repolens-delta.schema.json`
  - eigener Contract für Delta-Snapshots

- `tools_augment.yml`
  - Beispiel-Sidecar für das tools-Repo

---

## Zukunft

- Health-Trends über mehrere Merges
- Organism-Rollen automatisch erkennen
- Delta-Diffs mit Inline-Content
- automatische Generierung von Augment-Sidecars
