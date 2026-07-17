# Two-Layer Artifact Pattern

## Zweck

Beschreibe das RepoGround-Muster: Index Layer zeigt, Content Layer beweist.

Dieses Dokument zieht eine architektonische Regel fest, die in RepoGround bereits
implizit gelebt wird (PR-Schau JSON ↔ Markdown, Bundle Manifest ↔ canonical_md,
Runtime-Trace ↔ Context Bundle). Es macht das Muster explizit, damit neue
Artefakte ohne Drift in genau eine Schicht eingeordnet werden können.

## Kernregel

Index Layer zeigt.
Content Layer beweist.
Diagnose warnt.
Cache beschleunigt.
Runtime beobachtet.

Kein Artefakt darf still als ein anderes auftreten.

## Index Layer

Eigenschaften:

- maschinenlesbar
- navigierend
- enthält Integritäts-, Hash-, Range-, Rollen- oder Vollständigkeitsmetadaten
- darf nicht als vollständiger Inhaltsbeweis gelten

Beispiele:

- bundle manifest
- dump_index_json
- index_sidecar_json
- PR-Schau JSON
- artifact_lookup / trace_lookup / context_lookup Oberflächen, sofern sie nur
  verweisen

## Content Layer

Eigenschaften:

- enthält den eigentlichen Inhalt oder einen explizit kanonischen Ausschnitt
- darf gesplittet werden
- darf nicht still gekürzt werden
- muss über Range, Hash oder Completeness prüfbar bleiben

Beispiele:

- canonical_md
- PR-Schau Markdown-Parts
- query_context_bundle payload, sofern vollständig materialisiert

Hinweis: `query_context_bundle` kann vollständig materialisierten Inhalt
enthalten; seine Artefakt-Autorität bleibt dennoch Runtime Observation, weil es
aus einem konkreten Query-Lauf entsteht.

## Diagnostic Layer

Eigenschaften:

- macht Zustände sichtbar
- darf warnen
- darf keine kanonische Inhaltsautorität beanspruchen

Beispiele:

- architecture_summary
- diagnostics lookup
- Eval-/PR-Schau-Diagnosen

## Runtime Observation Layer

Eigenschaften:

- entsteht aus einem konkreten Lauf
- ist nützlich für Nachvollziehbarkeit
- beweist nicht den Live-Repository-Zustand

Beispiele:

- query_trace
- context_bundle
- agent_query_session

## Verbotene Gleichsetzungen

- JSON-Index als Inhaltswahrheit behandeln
- Markdown-Vorschau als vollständigen Report verkaufen
- Diagnose-Artefakt als canonical content verwenden
- Cache-Artefakt als Ursprung ausgeben
- Runtime-Spur als Live-Repo-Beweis behandeln

## Abbildungen in RepoGround

- PR-Schau: JSON index ↔ Markdown content
- RepoGround build bundle: bundle manifest / sidecar / dump index ↔ canonical_md
- Query Runtime: query_trace ↔ context_bundle ↔ agent_query_session

## Architekturregel

Neue Artefakte müssen angeben:

- welche Schicht sie bedienen
- was sie beweisen
- was sie nicht beweisen
- woraus sie regeneriert werden können
- welcher Guard oder Test ihre Drift erkennt
