# Optionale Rust-/Bash-Strukturadapter v1

## Entscheidung und Aktivierung

RepoGround kann für einen einzelnen, revisionsgebundenen Git-Checkout ein
abgeleitetes `language_structure_json` erzeugen. Die Fläche ist Navigation,
nicht Inhaltswahrheit: `authority=navigation_index`, `canonicality=derived` und
`risk_class=navigation` bleiben im Manifest und im Sidecar sichtbar.

Die Erzeugung ist standardmäßig aus. Sie wird ausschließlich explizit über das
Extra `language_structure` aktiviert (CLI: `--extras language_structure`; in
beiden UIs als standardmäßig nicht ausgewählte Option). Ein schmutziger,
mehrdeutiger oder nicht an genau einen Git-Commit gebundener Quellbaum erzeugt
kein Sidecar. Es gibt keinen Netzwerkzugriff, Download, Tool-Install, Reparatur-
oder Auto-Enable-Pfad.

## Gemeinsamer Record-Vertrag

Jeder Record enthält zwingend:

- Sprache `bash|rust` sowie Adapter-ID und Adapterversion;
- Typ (`symbol|relation` beziehungsweise bei SCIP `occurrence|relationship`),
  Relation, Symbol und optionales Zielsymbol;
- Repository-relativen Pfad und Range;
- Evidenzstufe `S0|S1`, endliche Konfidenz in `[0,1]` und Ableitungsbasis;
- Repositorycommit, Manifestdateiname, kanonischen Dump-Index-SHA-256 und beim
  Lesen den SHA-256 genau der stabil gelesenen Manifestbytes;
- eine sortierte Liste sichtbarer Unsicherheiten;
- für S1-SCIP-Evidenz zusätzlich den SHA-256 des normalisierten lokalen
  SCIP-Quellartefakts.

Auf Disk bleibt `bundle_manifest_sha256` im Record `null`, weil ein Manifest,
das den Sidecar-Hash enthält, nicht zugleich ohne Zirkelschluss in den
Sidecarbytes gehasht werden kann. Der integritätsprüfende Leser liest das
Manifest stabil, prüft Rolle/Contract/Bytes/SHA/Identitäten und projiziert den
Hash dieser exakt gelesenen Manifestbytes erst in eine Kopie der selektierten
Records. Sidecar-Record, Sidecar-Header, Manifest-Snapshotprovenienz, `run_id`
und `canonical_dump_index_sha256` müssen kohärent sein; andernfalls ist der
Lesestatus `blocked`.

Lexikalische Ranges verwenden 1-basierte Zeilen und 0-basierte
Unicode-Codepoint-Offsets mit exklusivem Ende
(`source_lines_1_based_unicode_characters`). Normalisierte SCIP-Ranges behalten
ihre deklarierte `position_encoding` und heißen ausdrücklich
`scip_position_encoding_units`; sie werden nicht als Unicode-Zeichenpositionen
umgedeutet. Ein Treffer belegt weder die volle Deklaration noch den Funktionsrumpf,
sondern genau das erkannte Symbol-/Relationstoken.

## Bash-Adapter

`bash-static-structure` v1.0 liest begrenzt reguläre UTF-8-Dateien mit
`*.bash`, `*.bats` oder `*.sh`. Bei `.sh` ohne belegten Bash-Shebang trägt jeder
Record die Dialektunsicherheit. Unterstützt sind:

| Fläche | Statischer Vertrag |
|---|---|
| Dateien | deterministisch sortierte, nicht verlinkte Kandidaten außerhalb bekannter Build-/Cache-Verzeichnisse |
| Symbole/Deklarationen | Funktionsdeklarationen in der explizit erkannten einfachen Syntax |
| Calls | statisch benannter Aufruf einer genau einmal im selben File deklarierten Funktion |
| Dependencies | literales `source`/`.`-Ziel |
| Ranges | Zeile plus Unicode-Zeichenoffset des Funktionsnamens bzw. Ziel-Tokens |

`eval`, indirekte Parameterexpansion, Command Substitution, dynamische
`source`-Ziele, Laufzeit-PATH/Aliase/Funktionsmutation und generierter Code
werden nicht ausgewertet. Doppelte Funktionsnamen erzeugen eine
`duplicate_function_definition`-Degradation; der zugehörige Call wird als
`ambiguous_function_call_target` ausgelassen.

## Rust-Adapter

`rust-static-structure` v1.0 ist ein konservativer Lexer, kein Rust-Parser und
kein Ersatz für `rustc` oder rust-analyzer. Er maskiert Kommentare sowie
String-/Zeichen-/Raw-String-Literale offsettreu und unterstützt:

| Fläche | Statischer Vertrag |
|---|---|
| Dateien | deterministisch sortierte, nicht verlinkte `*.rs`-Dateien außerhalb bekannter Build-/Cache-Verzeichnisse |
| Symbole/Deklarationen | `fn`, `struct`, `enum`, `trait`, `type`, `const`, `static`, `mod` im erkannten Zeilen-Subset |
| Calls | statisch benannter Aufruf einer genau einmal im selben File erkannten Funktion |
| Dependencies | syntaktisch erkannte `use`-Angabe, ausdrücklich ohne Filesystem-/Namensauflösung |
| Ranges | Zeile plus Unicode-Zeichenoffset des erkannten Tokens |

Makro- und prozedurale Makroexpansion, `cfg`-Auswertung, `include!`/generierter
Code, Trait-/Methodendispatch, Cross-Modul-Namensauflösung und
Laufzeiterreichbarkeit bleiben außerhalb des Vertrags. Makrotreffer und
mehrdeutige Funktionsnamen werden als Degradation sichtbar und nicht geraten.

Optional kann ein bereits vorhandenes, lokales, normalisiertes
`repoground.scip_symbol_relations`-Dokument als `rust-scip-structure` v1.0/S1
übernommen werden. Header, Commit, Indexhash, Recordzahl, sichere Pfade und
Ranges werden geprüft. RepoGround startet oder installiert dafür keinen
Indexer. S1 bedeutet stärkere Artefaktevidenz, nicht Laufzeitwahrheit.

## Konsum und Bytebudget

`ask_context` selektiert nur ein manifest- und hashgeprüftes Sidecar. Textuelle
`canonical_md`-Exzerpte und relevante mehrsprachige Strukturrecords teilen ein
einziges hartes Limit `max_context_bytes`; das aus dem Tokenbudget abgeleitete
Limit (`max_context_tokens * 4`) kann durch `max_context_bytes` nur verschärft
werden. Gezählt werden:

1. die exakten UTF-8-Bytes aller emittierten `text_excerpt`-Werte;
2. die exakten UTF-8-Bytes der kanonisch serialisierten, nichtleeren
   `language_structure.evidence`-Struktur.

Adress-/Envelope-Metadaten sind explizit nicht Teil dieses Evidence-Payload-
Budgets. `context_bytes_used`, `context_unicode_characters_used`, die Einheit,
die Accounting-Regel und alle Omission-Gründe werden separat ausgegeben.
Unicode-Präfixe werden niemals mitten in einem Codepoint abgeschnitten.
Strukturrecords werden nur als Ganzes aufgenommen; Range, Provenienz,
Konfidenz und Unsicherheit werden nie zum Einpassen entfernt. Selektion und
Komposition interleaven Sprachen deterministisch, damit Bash oder Rust die
andere Sprache nicht allein durch Sortierreihenfolge verdrängt.

Die Agent-Impact-Komposition übernimmt dieselben Records mit Range,
Evidenzstufe, Konfidenz, Provenienz und Unsicherheit. Sie darf sie als
Navigationsrelationen anzeigen, aber nicht zu Python-AST-Evidenz,
Runtime-Behavior, Testabdeckung oder vollständigem Call-/Dependency-Graph
hochzustufen.

## Doctor und Fehlerpfade

Doctor meldet jeden Adapter separat als `available`, `degraded` oder `blocked`,
mit erwarteter/ermittelter Version und Auswirkung. Nicht vorhandene optionale
Adapter sind `degraded`; fehlerhafter Import oder Versionsabweichung ist für
diesen Adapter `blocked`. Beides lässt den Python-/FTS-Kernstatus unverändert.
Doctor installiert, repariert oder aktiviert nichts.

## Goldset, Kosten und Promotion

Das lokale Goldset
`docs/retrieval/repoground_agent_utility_t021_goldset.v1.json` deckt positive,
mehrdeutige, dynamische und echte Nullfälle für Bash und Rust ab. Der Benchmark
verweigert nicht zum angegebenen `source_revision` passende HEADs sowie jeden
schmutzigen/untracked Repositoryzustand. Er bindet Report, Fixturebytes und Records an
Commit und kanonischen Goldset-SHA-256 und wiederholt die semantische Extraktion
für einen Determinismusvergleich.

Getrennt berichtet werden Symbol-TP/FP/FN und Precision/Recall,
Relations-TP/FP/FN und Precision/Recall, exakte Range-Precision/Recall,
True-Null-False-Positives sowie Latenz, Peak-Speicher und serialisierte
Indexgröße. Qualitäts- und Kostenmetriken werden aggregiert und je Sprache
ausgewiesen. Interpreterversion, Betriebssystem, Maschinenarchitektur und
logische CPU-Zahl bleiben als Messumgebung sichtbar. Laufzeitwerte sind
Umweltbeobachtungen und kein Cross-Machine-Reproduzierbarkeitsbeweis.

Der Promotionspfad ist derzeit bewusst hart geschlossen. Ohne externes
`agent_benefit` bleibt der Status `keep_optional` mit
`revision_bound_agent_benefit_missing`. Das Legacy-Argument `--agent-benefit`
bleibt nur zur Eingabekompatibilität erhalten: Auch ein syntaktisch gültiges oder
maximal positives Mapping ist **keine** Promotionsautorität und ergibt
`keep_optional` mit `verified_component_delta_agent_benefit_missing`. Es gibt
aktuell keinen Eingabepfad zu `eligible_for_explicit_promotion_review`.

Eine spätere Wiederöffnung erfordert einen verifizierten Component-Delta-Lauf im
bestehenden generischen Agent-Benchmark. Baseline und Treatment müssen dabei
denselben RepoGround-Kontext, dasselbe Modell, denselben Prompt, dasselbe Budget,
dieselbe Source-Revision und denselben Grader verwenden; nur das revisions- und
hashgebundene `language_structure_json` darf variieren. Erst eine solche über die
generischen Receipt-, Scoring- und Pair-Integrity-Flächen geprüfte Messung darf
wieder in eine separate Promotionsentscheidung eingehen. Die statischen
Qualitäts-, Nullfall-, Determinismus- und Kostenmetriken dieses Benchmarks bleiben
bis dahin Diagnoseevidenz, nicht Agentennutzen. `default_promoted` bleibt in
jedem Fall `false`.

## Nichtaussagen

Die Fläche etabliert insbesondere keine vollständige Symbol-, Call- oder
Dependencyabdeckung, keine Makro-/Shellauswertung, keine generierte-Code-
Abdeckung, keine Python-AST-Äquivalenz, keine Laufzeiterreichbarkeit, keine
Testhinlänglichkeit und keine Default-Promotion.
