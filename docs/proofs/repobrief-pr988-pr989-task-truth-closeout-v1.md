# RepoBrief PR #988/#989 Task-Truth Closeout v1

## Bindung

- Namespace- und Verteilungsentscheidung: PR `#988`, Head `83f022515c4c88dfaf9e154bf7be6eaf17dd9adb`, Merge `e241b7b95f08905159cf94f706f3e45024da4b71`.
- Read-only-Adapter und Workbench-Nutzennachweis: PR `#989`, Head `e9c2f71b7d2892800f2862bef140fa80232e1401`, Merge `0d601df241e2dab9915bf3df6ebd023f410b1750`.
- Dieser Closeout ändert keine Produktlogik. Er gleicht ausschließlich Taskindex, Board und Status-Truth mit bereits auf `main` vorhandener Evidenz ab.

## TASK-REPOBRIEF-PACKAGE-RENAME-DECISION-001

Die Entscheidung ist getroffen und maschinenlesbar dokumentiert:

- RepoBrief bleibt Produkt- und primärer CLI-Name.
- Repositoryname `lenskit` und Python-Namespace `merger.lenskit` bleiben für die 2.x-Linie stabil.
- Die Verbraucherbestandsaufnahme weist organisationsinterne Nutzer außerhalb dieses Repositories aus.
- Ein späterer Rename ist nur für einen bewusst brechenden Major-Release mit Verbraucherbestand, Migrationsplan, Abschreibungsfenster, Rollback und aktualisierten Diensteinstiegen zulässig.

Primäre Evidenz: `docs/decisions/repobrief-package-namespace-decision.v1.json` (SHA-256 `299b4e95e91922ba9c60a4ce5b984aba513fc7cfdae546ce6b6d077b79fbaecc`).

Nicht belegt: dauerhafter Ausschluss eines späteren Renames, vollständiger Bestand unbekannter Verbraucher oder öffentliche Paketfreigabe.

## TASK-REPOBRIEF-READONLY-ADAPTER-NO-MIRROR-001

Der breite, protokollneutrale Adapter ist implementiert und geprüft:

- nur ausdrücklich registrierte Manifeste unter erlaubten Wurzeln;
- pfadgebundene, größenbegrenzte und SHA-256-geprüfte Artefaktzugriffe;
- Vor- und Nachprüfung delegierter SQLite- und Symbolindex-Leseoperationen;
- keine Git-, Shell-, Netzwerk-, Refresh-, Snapshot-, PR-, Patch-, Secret- oder Schreibfunktion;
- maschinenlesbarer Kompatibilitätsvertrag für Bibliothek, CLI und abgegrenzte MCP-Bezüge.

Primäre Evidenz: `docs/proofs/repobrief-readonly-adapter-no-mirror-v1-proof.md` (SHA-256 `b8d3cb65561d2d3ddaff2872fd5634f2d385b6303c519492ed62063e4561af33`) und `docs/contracts/repobrief-readonly-adapter-compatibility.v1.json` (SHA-256 `7ba246b4e5caa7c4154be6c32dcabcb5e2777e13dae10cc6033f9475624d0249`).

Nicht belegt: laufender MCP-Transportserver, Authentifizierung, entfernte Freshness, Antwortkorrektheit, Reviewvollständigkeit oder Merge-Reife.

## TASK-REPOBRIEF-WORKBENCH-USEFULNESS-EVAL-001

Der fest begrenzte Nutzennachweis ist abgeschlossen:

- acht vorab festgelegte Navigationsfragen;
- Agent Reading Pack: kombinierte Zieltrefferquote `0.250`;
- Workbench aus bestehendem SQLite- und Symbolindex: kombinierte Zieltrefferquote `1.000`;
- Vorteil `+0.750` ohne Bundle-Mutation;
- breite Karten- und Diagnosemengen bleiben aufgabenspezifisch und werden nicht zum Standardkontext befördert.

Primäre Evidenz: `docs/proofs/repobrief-workbench-usefulness-eval-v2-proof.md` (SHA-256 `e4f093eaabc8996401740f8a2ada39772ac9dae7ed2c0eafbac71b5187242f49`) und Bericht `docs/diagnostics/repobrief-workbench-usefulness-eval-20260712T2053Z.json` (SHA-256 `03b2416c239860a91021c572a5addced7b0194ba6e581742d6ee9d34fd89f326`).

Nicht belegt: allgemeine Retrievalqualität, natürlichsprachliche Antwortkorrektheit, tatsächliches Agentenvertrauen, Patchkorrektheit, Reviewvollständigkeit oder Standardbeförderung.

## Abschlussaussage

Die drei Aufgaben waren nach PR #988/#989 technisch abgeschlossen, aber im kanonischen Taskindex noch offen. Dieser Closeout beseitigt ausschließlich diese Statusabweichung. Die getrennte öffentliche Lizenzentscheidung bleibt offen und gesperrt; der Semantic-Lock bleibt bis zu seinem eigenen Installations- und Hashnachweis offen.
