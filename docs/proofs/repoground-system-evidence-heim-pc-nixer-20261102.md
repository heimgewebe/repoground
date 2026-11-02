# RepoGround S1 — Heim-PC ↔ Nixer und Metarepo ↔ Zielrepo (02.11.2026)

**Status:** Ausführbarer S1-Entwicklungsnachweis im isolierten Grabowski-Worktree; kein produktiver Generator-/Publisher-/MCP-Abschluss. S2 ist bislang ein direkter Vergleich bestehender Git-Projektionen, kein veröffentlichtes History-Evidence-Pack.

## Voraus fixiertes Minigoldset

Vor dem ersten Writer-Schritt in der unveränderlichen Grabowski-Auftragsquittung festgelegt: (1) Heim-PC-Flake-URL und Lock-Pin; (2) Nixer-Modul und bedingte NixOS-Dienstdeklaration; (3) Pin gegen Nixer-main unterscheiden; (4) unabhängiger Metarepo-Sync-Vertrag und abweichende Bytes; (5) falscher Owner/Commit/fehlender Zielpfad darf keine S1-Kante ergeben; (6) fehlender Runtime-Beleg darf nicht aus der Flake-Konfiguration erfunden werden.

## Revisions- und Quellidentitäten

- Heim-PC `heimgewebe/heim-pc@a01e4d677f0375b4c5eb0a383b4eb1a5787a8003`, GitHub-main zum S0-Read: `flake.nix:11` deklariert `github:heimgewebe/nixer/6c1fae3936e441c43d19a7924f2f26f3539fb1d3`; `flake.lock:24–41` bindet dieselbe SHA; `nixos/system/flake.nix:41` deklariert `nixer.nixosModules.default` und `./modules/nixer.nix`; `nixos/system/modules/nixer.nix:45–80` deklariert bei `enableNixer` den Dienst und systemd-User-Overrides. Remote `git@github.com:heimgewebe/heim-pc.git` wurde direkt gelesen.
- Nixer `heimgewebe/nixer@6c1fae3936e441c43d19a7924f2f26f3539fb1d3`, local Git object `commit`, `flake.nix` blob `6fcff803c6fffecaec8a52b14d16818ef12e0ec7`, NixOS-Modul-Export vorhanden. Remote `git@github.com:heimgewebe/nixer.git` direkt gelesen. GitHub-main bei S0 `c252b62b0fcd0bd5442681bb68d809a4b5984c61` ist **nicht** der deklarierte Pin. Die lokale flache Nixer-Historie enthält diesen neuen GitHub-main-Commit nicht; keine unbewiesene Ancestry.
- Metarepo `heimgewebe/metarepo@c1ac04fec54de590eda209b916f81c4ce8eb363a`, `fleet/repos.yml`, `sync/metarepo-sync.yml`; Zielrepo `heimgewebe/repoground@92545a4a9cbfe5ee32a3cb35a9c0cc054c1bdcf5`. Nixer gehört **nicht** zur normativen Core-Fleet-Liste; die Flake-Kante braucht keine Fleet-Mitgliedschaft.

## S1: Reproduzierbare deterministische Relation

Der neue `flake_revision_relations`-Producer verwendet ausschließlich die Git-Objekte der angegebenen Quell- und Zielrevision, ohne Git-Fetch, Nix-Evaluation, Bundle-Refresh oder Arbeitsbaum-Lesezugriff auf die Datenquellen. Er prüft URL, owner/repo, SHA, `flake.lock`, Ziel-Commitobjekt, Modul-Export und vorhandenen lokalen Modulpfad. Unverifizierte Elemente bleiben Lücken (S0), nicht sichere Kanten (S1). Die lexikalische Erkennung ist bewusst auf Root-Inputs beschränkt; URLs in fremden Nix-Attributbereichen werden nicht als Flake-Inputs aufgewertet. Die Repositoryidentitäten stammen aus den ausdrücklich angegebenen Quell-/Zielzuordnungen, nicht aus einer automatischen GitHub-Identitätsprüfung.

CLI im Grabowski-Worktree:

```bash
python3 -m merger.repoground.cli federation flake-relations \
  --repo-root /home/alex/repos/.repoground-sources/heimgewebe__heim-pc__main--a01e4d677f0375b4c5eb0a383b4eb1a5787a8003 \
  --repo-id heimgewebe/heim-pc \
  --commit a01e4d677f0375b4c5eb0a383b4eb1a5787a8003 \
  --target heimgewebe/nixer=/home/alex/repos/nixer@6c1fae3936e441c43d19a7924f2f26f3539fb1d3
```

Erster echter direkter CLI-Lauf: Status `ok`, keine Lücken, 4 S1-Deklarationskanten, Digest `a8746ef4ddb8724d12b0459545012f56bb317a0955b8f6e4b696e0bd5b295eb3`, etwa **0,50 Sekunden**. Nach Erweiterung um `nixos_local_module_inclusion` ist der aktuelle **zweite echte CLI-Lauf** (0,528 Sekunden) ebenfalls `ok`, ohne Lücken, nun **5** gerichtete S1-Beziehungen. Der aktuelle Fünf-Kanten-Evidence-Digest lautet `805efdef4e269186e7b1be3e9d75673c2d774fd6ff46da9c01157be754664c26`. Der oben genannte Digest bezieht sich nur auf den anfänglichen Vier-Kantenstand. Jede Kante trägt die gebundene Quell- und Zielrevision sowie Git-Blob-OID/Digest; `flake.nix:11`, `nixos/system/flake.nix:41`, `modules/nixer.nix:46,69` sind auf Zeilen gebunden. Keine Relation behauptet Aktivierung oder erfolgreichen Dienststart.

Zweiter, unabhängiger Fall mit bereits vorhandenem `fleet_revision_relations`: Metarepo@oben → Heim-PC@oben beziehungsweise RepoGround@oben. `declared_copy_target` für `.github/workflows/wgx-guard.yml` und `.wgx/profile.example.yml` nach `.wgx/profile.yml`. Im echten Vergleich Status `diverged_at_revisions` mit abweichenden Quell-/Ziel-Digests, zum Beispiel `wgx-guard.yml` Metarepo `263ccdf7...` gegenüber RepoGround `8cdaec47...`. **Deklarierter Kopiervertrag, kein synchronisierter Inhalt und keine Laufzeitabhängigkeit.** Der vorhandene Föderationsproducer bleibt unverändert.

## Negativ- und Abdeckungsgrenzen

`python3 -m unittest -q tests.test_cross_repo_flake_relations`: 13 gezielte Tests bestanden, inklusive exakter Gitobjekt-Positivkette, reproduzierbarem Output, falschem Owner, falschem Zielcommit, Lock-Konflikt, fehlendem Zielrepo, fehlendem Modulpfad, kommentar-only Modul-Export, URL außerhalb der Flake-Root-Inputs, doppelter Root-Input, Root-Attrpfad, Git-HEAD im Ziel verschieden vom gepinnten Objekt und tatsächlichem CLI-Aufruf.

Nicht bewiesen: vollständige Nix-AST-Evaluation, dynamische Importpfade, vollständige Cross-Repo-Abdeckung, Build-/CI-Identität, aktivierte Generation, tatsächlich laufender Dienst, Deploy-Kompatibilität. S0 Host-Readback des *User-Managers* meldet für `nixer.service` und `nixer-image.service` `LoadState=not-found`, `ActiveState=inactive`. Das beweist weder die Nichtexistenz eines systemweiten Headless-Dienstes noch die aktuelle NixOS-Generation.

## S2: Echte historische Pinänderung – bisherige Read-only-Gegenprobe

- Heim-PC Basis `7ff110f9dc2c561ca9bb525edb4d4b41a3796bfe`, Ziel `12a8c6af34e5aedfa98f795c1261c782f97731d8`, ancestry mit `git merge-base --is-ancestor` belegt.
- Commit vom 29.10.2026 06:31 +01:00: `flake.nix` und `flake.lock` änderten den Pin von `f66d0a38ef3c75833fa20db8aa6bd9202c9608a5` auf `6c1fae3936e441c43d19a7924f2f26f3539fb1d3`; beide Nixer-Commitobjekte lokal verifiziert.
- `history_lens.git_revision_delta` meldet exakt zwei veränderte Dateien, `status=ok`; vollständiger geprüfter Git-Diff 1304 Bytes, SHA-256 `875b3b80e466962c2a9a28f90ecf271fe1e9b2b977eb375f5d7758ebde4f5961`.
- Revidierte Flake-Relationen vor und nach: jeweils vier bestätigte Deklarationskanten im ersten Producerstand, Digest davor `05cf1fdf323a7123cc9b1fa9f0d324abb6769d97106cafce41b2ee6873855fda`, danach `4599545d5dc7dd3e1f2ac20ac361b25c47e50ffd2681ef66b565c637cfcbf615`. Diese Vergleichsbeobachtung stammt vom ersten Vier-Kantenstand. Die heutige Fünf-Kanten-Version ist erneut abzugleichen.

Es wurde weder ein ausführbarer Deploy-Impact noch ein Testlauf zu den historischen Commits behauptet. Solange keine reproduzierbare integrierte S2-Antwort vorliegt, ist das nur ein Vorbeleg.

## Betriebs-, Integrations- und Kostenwahrheit

- RepoGround-GitHub-main bei S0 `92545a4...`, lokaler kanonischer Checkout `cec670b...`, sauber und drei zurück; geschützter `post-merge-sync-apply` ist **ohne ausgeführte Änderung** an einer aktiven Ressourcenbindung gescheitert (`lease_acquisition_blocked`, `retry_authorized=false`). Keine Lease-Umgehung.
- Exklusiver Grabowski-Worktree `/home/alex/repos/.grabowski-worktrees/repoground-system-evidence-s1-20261102`, Branch `feat/repoground-system-evidence-s1-20261102`, Lane `d4e357d40e07bd45ab8a606e25a21277`, Ausgangs-SHA `92545a4...`. Die fremde A1/B1-Dokumentationslane bleibt unberührt.
- Produktiver Generator bei S0 `0fe8e5fd972c69b0d816b6bf124e10e6f5a43112` und bestehendes frisches Heim-PC-Bundle `a01e4d...` sind **nicht** schon mit diesem neu entwickelten Flake-Producer gebaut. Produktive CLI-/MCP-/Publisher-Funktion und zwei reale Agentenconsumers stehen aus.
- Keine gemessenen S4-p95, Vorberechnungskosten, Speicher-/Update-Latenzen oder fairer Agentenvergleich. Der isolierte CLI-Warmaufruf ist **kein** End-to-End-Leistungsbeleg. Der neue Producer liest Git beim CLI-Aufruf; eine Veröffentlichung als vorab berechnetes Pack existiert noch nicht.

**Abschlussstatus:** S1 direkt im Entwicklungsworktree funktional demonstriert, Produktionsintegration und S2–S4 offen. Ein Merge oder CI-Lauf wird erst nach seinem tatsächlichen Readback als durchgeführt dokumentiert.
