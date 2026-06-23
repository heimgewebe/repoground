# PR Delta Cards v1 - Gap Report

## 1. Vorhandene Delta-Source
delta.json wird durch die bestehende PR-Schau-Erzeugung produziert.
Der PR-Delta-Card-Batchproducer akzeptiert ein bereits geladenes,
vollständig gegen pr-schau-delta.v1 validiertes Mapping.
Dieser Slice lädt keine Delta-Payloads und keine PR-Schau-Bundles.
Das repositoryeigene pr-schau-delta.v1-Schema wird für die
Contractvalidierung aus dem Contracts-Verzeichnis geladen.

## 2. Vorhandene Lens-Card-Source
`merger/lenskit/core/lens_cards.py` bietet `produce_lens_card(path)`, welche einen gegebenen String-Pfad verarbeitet, den `Facet Model v1` Produzenten `infer_facets` aufruft, den Pfad validiert und eine normierte Lens-Card erstellt.

## 3. Fehlende Zielimplementierung
Die zuvor fehlende Zielimplementierung wird in diesem Draft-PR als Contract/Core/Validation/Test-Slice bereitgestellt. Merge und Post-Merge-Reconciliation stehen aus.

## 4. Source-Authority und Rollenbeschreibung
Das Source-Delta ist ein diagnostisches Signal.
Die Lens-Felder sind eine navigationale, abgeleitete Projektion.
Die äußere Card bleibt `diagnostic_signal` / `diagnostic`.
Die Card ersetzt weder delta.json noch kanonische Repo-Inhalte.

## 5. Kardinalität
Genau eine PR Delta Card pro Dateieintrag (`files[]`) in der Source-Delta-Struktur.

## 6. Identitäts- und Provenienzentscheidung
- **Identität**: `path` innerhalb eines expliziten Delta-Kontexts (`source_kind`, `source_version`, `repo`, `generated_at`). Es ist keine universelle Identität oder GitHub-PR-Identität.
- **Provenienz**: PR Delta Cards v1 enthalten keine Hashfelder und behaupten keine
Hashprovenienz. Eine mögliche spätere Bundle-/Manifest-Integration ist
nicht Teil dieses Slices und wird durch diesen PR weder implementiert
noch zugesichert.

## 7. Outputshape-Entscheidung
Wir wählen eine flache kontrollierte Projektion.
Wir projizieren: `path`, `change_status`, `primary_lens`, `matched_rule`, `facets`, und `navigation_refs`.
Ebenfalls verwenden wir eine eigene feste PR-Delta-Negativsemantik.

## 8. Inputgrenze
Unterstützung eines bereits geladenen delta.json-konformen Mappings.
Keine Datei-, CLI- oder Bundle-Integration.
Der Batchproducer akzeptiert nur vollständige pr-schau-delta.v1-Payloads.
Die formale Source-Validierung ist Draft-2020-12-basiert.
Summary-Kohärenz und eindeutige Pfade sind zusätzliche semantische Invarianten.

## 9. Bewusst ausgeschlossene Felder
Ausgeschlossen sind alle Judgment- und Impact-Felder: GitHub-PR-Nummer, Base/Head-Commit, Merge-Base, Rename-Identität, Hunks, Zeilenbereiche, Symbole, Kausalität, Impact, `suspicious_patterns` und `affected_chunk_ids`.

## 10. Contract- und Validatorstrategie
Wir erstellen `pr-delta-card.v1.schema.json` als JSON Schema (Draft-07), fordern strikte Enums für Change-Status und Authority, und Contract-Parität mit Lens Card und Source-Delta.
Vollständige Source-aware Producer-Kohärenz: Der Validator erzeugt die Card aus der Original-Source-Evidence neu und vergleicht alle Rootfelder vollständig.

## 11. Teststrategie
- Contracttests: min/max Kardinalität, Status-Enums, Authority-Enums, keine neuen Felder, feste PR-Delta-Negativsemantik-Sortierung.
- Producertests: Determinismus, Input/Output-Kardinalität, Statusbehandlung, fehlendes JS Schema verhalten.
- Validatortests: Fehlschlag bei abweichender Card-Evidence, abweichendem Source-Content, fehlendem JS Schema.
- Contract-Paritätstests via Node/JS Parität für Pfadpattern.

## 12. Verbleibende Folgearbeiten
- Merge ausstehend.
- Post-Merge-Reconciliation ausstehend.
- automatische Emission nicht vorhanden.
- Bundle-/Manifest-Integration nicht vorhanden.
- Consumer-/Frontend-Nutzung nicht belegt.
- tatsächlicher Agenten- oder Retrievalnutzen nicht belegt.
