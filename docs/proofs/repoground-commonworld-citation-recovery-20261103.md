# RepoGround – Commonworld-Zitierreparatur, produktive E2E-Abnahme

**Datum:** 3. November 2026, Europe/Berlin
**Befund:** Technische Quellenabnahme **PASS**. Ein Geschwindigkeits-, Kosten- oder Qualitätsgewinn ganzer Agentenaufgaben bleibt **not_established**.

## Revisions- und Publikationsbindung

| Identität | Nachgewiesener Wert |
| --- | --- |
| Korrektur | [RepoGround PR #1400](https://github.com/heimgewebe/repoground/pull/1400), gemergt am 03.11.2026, 16:47:21 UTC |
| Generator / RepoGround-`main` | `b9db1745335f12f5e32120cc0366cf4687585a00` |
| Eingefrorene Commonworld-Quelle | `2c6a790a8b76027d620cfc416918c9b6f08e34cc`, sauber, `origin/main` beim Readback identisch |
| Publication-Run | `20261103T182131Z-83f90c21d844` |
| Bundle-Stem | `heimgewebe__commonworld__main--2c6a790a8b76027d620cfc416918c9b6f08e34cc-max-261103-1821` |
| Manifest-SHA-256 | `e1f1d60fa35983a23b6f61eb70db0eaded2b90921831b174d5feed893a8bf688` |
| Generator-Inputs-SHA-256 | `1670587f8b9f51e206874a579d8d44f8dc21f3a2b0f6bb075170cc8d104fd811` |
| Konfigurations-SHA-256 | `16e7b3764a643e41a361ddaee107c0aef6a0b6b1a268c5f0d5b4f92c891fec5d` |
| Profil / Eingrenzung | `fleet-context`, `excluded_root_dirs=["releases"]` |
| Zustand | `fresh_exact`; Output-Health **PASS**, Post-Emit-Health **PASS** / `range_strict` |

Das Bundle liegt im regulären Veröffentlichungspfad `manifest-publications/bundles/heimgewebe__commonworld/main/20261103T182131Z-83f90c21d844/`. Die Quelle und der Generator sind getrennt an die genannten SHA-Identitäten gebunden. Historische Materialisierungen unter `releases/` werden bewusst **nicht** als aktive Repositoryquelle ausgegeben; für diesen Teilbaum wird keine vollständige Inhaltsabdeckung behauptet.

## Technischer Vorher-nachher-Befund

| Größe | Vorheriges Bundle | Neues Bundle |
| --- | ---: | ---: |
| Generator | `551b1d4c` | `b9db1745` |
| Commonworld-Quelle | `2f14d42d` | `2c6a790a` |
| Such-Chunks | 50.770 | 1.886 |
| Chunks mit `canonical_range` | 1.639 | 1.886 |
| Anteil mit `canonical_range` | 3,23 % | **100 %** |
| Zitierbares kanonisches Markdown | Nur Part 1 von 16 deklariert | Ein kanonischer Markdown-Artefaktpfad |
| Unterschiedliche indizierte Quellpfade | Nicht erneut ermittelt | 1.123 |
| Chunks aus `releases/` | Nicht separat ermittelt | **0** |

Der alte Manifest-Digest war `503606b2dc3402ab2249153ed88d36f4f2e98923180a51de30b362357f7f1975`, seine Veröffentlichung `20261103T134955Z-7bdc49ece1d7`. Der neue Index ist ungefähr 5,0 MB groß. Die Prozentzahlen beziehen sich auf **kanonische Range-Verfügbarkeit je Chunk**, nicht auf inhaltliche Wahrheit, Relevanz oder Agentenleistung.

**Wichtig:** Auch die Commonworld-Quellrevision hat zwischen beiden Publikationen gewechselt. Das ist ein echter produktiver Vorher-nachher-Befund, **kein kontrollierter kausaler Geschwindigkeitsvergleich** bei identischer Quelle. Die gezielten PR-Regressionstests isolieren den Effekt der Root-Ausklammerung in einer eingefrorenen Fixture.

## Echter Agenten-Werkzeugweg

Für die neue Publikation erfolgten reale, frische Zugriffe über die registrierten Grabowski-RepoGround-Tools:

| Zuvor unzitierbare Datei | `query_existing_index` | `range_get` mit gültigem `canonical_md`-Ref |
| --- | --- | --- |
| `scripts/catalog_delivery_compile.mjs` | `citation_status=resolved`, `range_status=resolved` | **available**, 512 Bytes, SHA-256 `f94893361da6308a8436d1fc666e362a844dc5e2cbe4554b879728d0391c991e` |
| `tests/test_commons_admission.py` | `resolved` / `resolved` | **available**, 2.915 Bytes, SHA-256 `c83c2702e4155b62df289b49f07ec7f88c75d35eaf3845c0fa522a686abd2df3` |
| `scripts/validate_commons_admission.py` | `resolved` / `resolved` | **available**, 3.458 Bytes, SHA-256 `acc88b1bcc70667f4987382163b935f7482d59dec1d970b713d809d5b8aee98b` |

Alle drei `range_get`-Ergebnisse bestätigten den erwarteten SHA-256 des wirklich zurückgelieferten kanonischen Textbereichs. Bei diesen Treffern ist außerdem eine saubere, exakt auf Commonworld `2c6a790a` gebundene Live-Git-Quelladresse verfügbar.

Der volle Agenten-Einstieg `repoground_preflight(task_profile="basic_repo_question")` lieferte `pass`; `repoground_query` fand für `normalizeBootstrapForCompile catalog_delivery_compile` drei zitierfähige Treffer. `repoground_context_pack` gab für die JavaScript-Quelle einen **direkt verwendbaren `range_ref`** zurück. Seine unveränderte Übergabe an `repoground_range_get` bestand erneut mit übereinstimmendem SHA-256 – kein manueller Ref-Aufbau erforderlich.

Die aktiven Python-Navigations-Sidecars enthalten 1.717 Symbol-Records und 18.000 Call-Records; in beiden wurden **0** Quellpfade unter dem ausgeschlossenen Root `releases/` gefunden. Erwartete aktive `scripts/`- und `tests/`-Pfade sind in beiden enthalten. Der optionale Rust-/Bash-Sprachstruktur-Sidecar ist für diese Live-Quelle nicht Bestandteil des Bundles; die separate PR-Fixture prüft die Ausklammerung auch für Rust und Bash.

## Aktivierung, Rückfall und Betriebsnachweis

- Gezielt durch den kanonischen Fleet-Publisher, **nur `heimgewebe/commonworld`**, neu veröffentlicht: Grabowski-Task `b406cf7e5bf942a4bf482b14`, Endstatus `completed`, Exit 0, Receipt `7105ed10b12bfaa538c2a0355cc2ae27291d8ce41a03e6a5350065469d2c63fd`.
- Die vorbereitete Git-freie Runtime `~/.local/share/repoground-runtime/b9db1745…` hat ihren Python-3.12-Canary bestanden. Der CLI-Aktivierungszeiger `current` wurde atomar von `551b1d4c…` auf `b9db1745…` umgestellt: Task `b3ae2c0c30c746eb8d4569a8`, `completed`, Exit 0, Receipt `fb25db6f71c93ad28accefc6a35dbc429f3ad35c111b0aa3f9944bd76c9caaf0`. Der alte Release-Ordner blieb für einen Rückfall erhalten.
- Der saubere lokale Hauptcheckout wurde per Grabowski-`post-merge-sync-apply` exakt und nur per Fast-Forward von `551b1d4c…` nach `b9db1745…` synchronisiert; Receipt `79e2328e35c52c4d89d8bc7b4fb77d380dc00cf78b646224b2e5fd4918ef32e8`, Post-Readback sauber und deckungsgleich mit `origin/main`.
- Ein eigenständiger `repoground.service` wurde weder als systemweite noch als Benutzer-Unit gefunden. Die hier bewiesene Produktivnutzbarkeit betrifft **CLI, Fleet-Publisher und echten Grabowski-MCP-Zugriff**, nicht den Betrieb eines nicht vorhandenen HTTP-Dienstes.

## Wiederholbarkeit und Entscheidung

Für eine technische Nachmessung die **exakten** Source-, Generator-, Konfigurations- und Manifest-SHAs sowie das Bundle-Stem festhalten, erst `repoground_freshness_check` und `repoground_preflight` prüfen, danach dieselben drei Pfadfragen durch `repoground_query_existing_index`, die zurückgelieferten `context_pack.snippets[].range_ref` unverändert durch `repoground_range_get` schicken und Status, Text-SHA-256, Ergebnisgröße und fehlende Quellen protokollieren. Rohquellen nicht mit abgeleiteten Navigationsdaten verwechseln.

**Abnahmeurteil:** Der konkrete produktive Defekt „aktive Commonworld-Dateien gefunden, aber nicht zitierbar“ ist für die drei zuvor reproduzierten Fälle **behoben und E2E nachgewiesen**. Die frühere R5-A/B/C-Kohorte betraf andere Repositories und zeigte keinen selektiven Nutzen. Für eine quantitative Agentenverbesserung in Commonworld braucht es ein **eigenes vorregistriertes, quellen- und protokollgebundenes A/B/C-Goldset**, echte isolierte Agentensitzungen und unabhängige Quellenbewertungen. Bis dahin bleiben End-to-End-Zeit, Tokenkosten und Antwortqualität gegenüber Git-only **not_established**.
