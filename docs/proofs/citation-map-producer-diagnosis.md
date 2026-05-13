# Citation-Map Producer — Diagnose und Stop-Entscheidung

## Status

**Hypothesis H1 (Producer fehlt vollständig) ist repo-belegt.**

Die Citation-Map-Producer-Komponente existiert nicht im Repo. Schema, Manifest-Role, ArtifactRole-Enum und Beispiele sind vorhanden — aber kein Producer, kein Wiring, kein Konsument.

**Stop-Kriterium erfüllt:** Im Repo ist kein realer Dump mit dual ranges als prüfbares Artefakt abgelegt; kein In-Repo-Konsument; Real-Dump-Proof ist daher aus dem Repo-Stand heraus nicht möglich.

**Keine Implementierung in diesem Diagnose-Schritt.**

## Vorhandene Bausteine (repo-belegt)

| Beleg | Datei | Status |
|---|---|---|
| Schema | `merger/lenskit/contracts/citation-map.v1.schema.json` (5.7 KB) | vollständig, draft-07, erfordert `citation_id`, `repo_id`, `snapshot`, `canonical_range`; `source_range` optional |
| Beispiele | `merger/lenskit/contracts/examples/citation_map_minimal.jsonl` | 3 gültige Einträge demonstrieren source_range Varianten |
| Schema-Test | `merger/lenskit/tests/test_citation_map_schema.py` | vorhanden |
| Proof | `docs/proofs/citation-map-artifact-fit.md` | Rollen und Nicht-Rollen geklärt |
| Manifest-Role | `merger/lenskit/contracts/bundle-manifest.v1.schema.json:84, 498–551` | strikt registriert mit Constraints: `contract=citation-map/v1`, `authority=navigation_index`, `canonicality=derived`, `regenerable=true`, `staleness_sensitive=true` |
| ArtifactRole Enum | `merger/lenskit/core/constants.py:21` | `CITATION_MAP_JSONL = "citation_map_jsonl"` |
| Roadmap-Eintrag | `docs/roadmap/lenskit-master-roadmap.md:76` | `[ ] Citation-Map-Producer …, Real-Dump-Proof` offen |

## Fehlende Komponenten (negativ belegt)

| Komponente | Befund |
|---|---|
| Producer-Datei | Kein `merger/lenskit/core/citation_map.py` oder äquivalent. `find merger/lenskit -name '*citation*'` findet nur Schema, Beispiel, Test. |
| Wiring in merge.py | `_add_artifact(CITATION_MAP_JSONL, …)` fehlt in Zeilen 5919–5975 (alle anderen Rollen vorhanden). Kein Contract-/Authority-Default-Eintrag für `CITATION_MAP_JSONL` in Zeilen 5825–5882. |
| Output-Health Integration | `merger/lenskit/core/output_health.py` erwähnt `citation_map` keinmal (wäre die Stelle für geplante Citation-Health-Checks). |
| Konsument im Code | `merger/lenskit/retrieval/query_core.py`, `service/`, `cli/` referenzieren `citation_id` nirgends. Contracts-Matrix nennt Konsumenten nur als geplant (Query/Context/Agent Evidence Pack in Phase 2/5). |
| Real-Dump | `data/` enthält nur `.gitkeep`. Im Repo ist kein erzeugter `*.bundle.manifest.json`, kein `*.merge.md` mit zugehörigem chunk_index abgelegt. Real-Dump-Proof aus dem Repo-Stand heraus unmöglich. |
| Fixture-Update | `merger/lenskit/tests/fixtures/retrieval/mini_chunk_index.jsonl` enthält keine dual ranges (`canonical_range`, `source_range`, `content_range_ref`); ein Producer würde an dieser Fixture leer laufen. |

## Epistemische Leeren

Folgende Lücken verhindern einen stabilen Producer-PR:

1. **Real-Dump fehlt, nötig für Real-Dump-Proof.** `data/` ist leer. Kein produzierter Lenskit-Bundle mit chunk_index dual ranges ist im Repo als prüfbares Artefakt abgelegt.
   - Folge: Ein Test-Fixture kann Producer-Logik prüfen, aber keinen Real-Dump-Proof ersetzen.

2. **Konsument fehlt im Code, nötig für klaren Nutzen.** Im Repo erweitert kein Schema `citation_id`, kein Validator liest citation_map_jsonl.
   - Folge: Producer würde ein Artefakt erzeugen, das kein Code im Repo konsumiert.

3. **Snapshot-Quelle für run_id/canonical_md_sha256 nicht zentral verdrahtet.** `merge.py` kennt diese Werte, aber nicht im Kontext eines Citation-Producers.
   - Folge: Deterministische Citation-Id-Ableitung hätte keine garantierte Quelle.

4. **Citation-Id-Derivationsregel nur in Blueprint, nicht in Code.** `docs/blueprints/lenskit-evidence-address-architecture.md:107–116` definiert die Regel; Schema erzwingt sie nicht.
   - Folge: Producer müsste die Regel erraten oder vom Blueprint kopieren.

## Stop-Kriterien (Briefing)

| Kriterium | Erfüllt? | Begründung |
|---|---|---|
| Citation-Map-Schema fehlt oder ist nicht eindeutig | **Nein** | Schema ist eindeutig, vollständig |
| Manifest-Role fehlt oder Semantik unklar | **Nein** | Role ist scharf constraint-belegt |
| **Kein realer Dump mit dual ranges verfügbar** | **Ja** | `data/` leer; im Repo kein Bundle-Manifest abgelegt; Fixture hat keine dual ranges |
| Producer-Status nicht eindeutig belegbar | **Nein** | H1 ist eindeutig belegt |
| **Kein Konsument oder kein klarer Nutzen** | **Teilweise Ja** | Kein Konsument im Code; Nutzen (stable citation_id) ohne Konsument spekulativ |

**Mindestens ein hartes Stop-Kriterium ist erfüllt → Kein Patch jetzt.**

## Warum jetzt nicht implementieren?

Ein Producer ohne Real-Dump-Proof:

1. **Verletzt die Roadmap:** `[ ] Citation-Map-Producer …, Real-Dump-Proof` definiert Gate als „Real-Dump-Proof"; ein Fixture-Test ist kein Real-Dump-Proof.
2. **Erzeugt Phantom-Evidenz:** Artefakt ohne Konsument im Repo ist totes Inventar, erhöht nur die Komplexität.
3. **Verstärkt die nächste Hypothese-Fallstricke:** Nachfolgende Agenten sehen einen implementierten Producer und bauen Konsumenten darauf, statt den fehlenden Real-Dump zu beheben.

## Nächste erforderliche Vorbedingungen

Bevor ein echtes `merger/lenskit/core/citation_map.py` begonnen wird, müssen diese Bedingungen erfüllt sein:

### 1. Real-Dump mit dual ranges bereitstellen
- Quelle: Ein von der aktuellen Lenskit-Pipeline erzeugter `*.bundle.manifest.json` mit zugehörigem chunk_index.jsonl, das `canonical_range`, `source_range`, `content_range_ref` enthält.
- Zielort: `data/` oder dokumentierter externer Pfad.
- Validierung: Das Bundle muss sich mit aktuellen Schemas validieren.
- Warum: Ohne echten Dump ist kein Real-Dump-Proof möglich, nur Fixture-Proof.

### 2. Mindestens einen Konsumenten benennen
- Option A: Query-Result-Schema-Erweiterung um `citation_id` (Phase 2 geplant).
- Option B: Explicit validator (`lenskit citation validate <bundle_manifest>`) in `merger/lenskit/cli/cmd_citation.py` (Phase 4 geplant).
- Option C: Roadmap-gültige Placeholder wie `merger/lenskit/retrieval/citation_lookup.py` mit stub consumer.
- Warum: Producer ohne Konsument ist unmotiviert; die nächste Lenskit-Instanz weiß nicht, warum das Artefakt existiert.

### 3. Citation-Id-Derivationsregel als Code-Helper fixieren
- Neuer PR: `merger/lenskit/core/citation_id.py` mit:
  - `make_citation_id(canonical_md_sha256: str, start_byte: int, end_byte: int, content_sha256: str) -> str`
  - Implementiert: `"cit_" + sha256(f"lenskit.citation-map.v1:{canonical_md_sha256}:{start_byte}:{end_byte}:{content_sha256}")[:16]`
  - Test: Determinismus-Check (same input → same output)
- Warum: Die Regel ist derzeit nur Blueprint-Text; sie muss Code werden, damit der Producer sie nicht erraten muss.

## Roadmap-Implikation

In `docs/roadmap/lenskit-master-roadmap.md` soll bleiben:

```
- [ ] Citation-Map-Producer, geplante Citation-/Evidence-Health-Prüfung in separater Folge-PR, Real-Dump-Proof
```

Nicht auf `[x]` setzen. Optional darunter kurz ergänzen:

```
  Blocker: Real-Dump nicht verfügbar, Konsument nicht definiert, Citation-Id-Regel nicht in Code; siehe docs/proofs/citation-map-producer-diagnosis.md.
```

Ziel: Spätere Roadmap-Reader sehen sofort, dass Producer nicht „vergessen" ist, sondern bewusst blockiert.

## Entscheidungsgrad

| Aspekt | Sicherheit |
|---|---|
| H1 (Producer fehlt) ist belegt | sehr hoch (0.95) |
| Stop-Kriterium Real-Dump ist erfüllt | sehr hoch (0.95) |
| Stop-Kriterium Konsument ist erfüllt | hoch (0.85) — teilweise, da „spekulativ" sein könnte |
| Nächste Vorbedingungen sind sinnvoll | hoch (0.80) |

## Nicht Gegenstand dieses Proofs

- Beweis, dass ein Producer **könnte** funktionieren (Skizze/Pseudo-Code).
- Beweis, dass die Blueprint-Regel richtig ist.
- Implementierung einer der Vorbedingungen.
- Änderung des Citation-Map-Producer-Status auf `[x]`.
- Beweis, dass der spätere Producer mit Real-Dump funktioniert.
- Weitere Roadmap-Änderungen über die Blocker-Notiz hinaus.

Dieser Proof **dokumentiert die Stop-Entscheidung**, nicht die Machbarkeit des Patches.

---

**Dokument-Version:** 1.0  
**Diagnose durchgeführt:** 2026-05-12  
**Nächste Bewertung:** Nach Real-Dump-Verfügbarkeit und Konsumenten-Definition  
**Status:** ✋ Stop, kein Patch, nur Dokumentation
