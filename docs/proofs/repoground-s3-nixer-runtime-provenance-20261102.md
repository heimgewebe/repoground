# RepoGround S3 – Beobachtete Git-/Build-/Generations-/Runtime-Provenienz

Stand: 2. November 2026. Baseline RepoGround: `7d299a7d1248a22263e176a7f7c5182a2ad57ba2`. **Status: lokale, rein lesende Live-Prüfung auf heim-pc; keine Aussage über Merge, Release oder Fleet-Publikation dieser neuen S3-Funktion.**

## Quellen und Reproduzierbarkeit

Der kleine, ohne zusätzliche Datenhaltung laufende Prüfer `scripts/ops/measure_nixer_runtime_chain.py` verbindet bereits bestehende RepoGround-S1-Git-Objekt-Evidenz mit den verantwortlichen Live-Primärquellen: `/run/current-system`, Nix-Systemprofil, systemd-Unit, `nix why-depends`, Nix-Derivation und Nix-Store-Quelldateien, `/proc/<pid>` und eine lokale HTTP-Abfrage. Er führt **keinen** Nix-Build, Rebuild, Restart, Fetch, Publisherlauf oder Git-Checkout-Wechsel aus.

Wiederholung (im RepoGround-Repository, auf dem produktiven Heim-PC mit vorhandenen lokalen Gitobjekten):

```bash
python3 -m scripts.ops.measure_nixer_runtime_chain \
  --heim-pc-repo /home/alex/repos/heim-pc \
  --heim-pc-commit 049efc0fcddee75d5d6ddee631be6e5b42784761 \
  --nixer-repo /home/alex/repos/nixer \
  --older-nixer-commit 6c1fae3936e441c43d19a7924f2f26f3539fb1d3 \
  --declared-nixer-commit c252b62b0fcd0bd5442681bb68d809a4b5984c61
```

Das Ergebnis ist maschinenlesbares JSON mit `kind=repoground.nixer-runtime-provenance`, genauen Quell-Commits, `observed_at_utc`, jeder einzelnen Evidenzverbindung, Store-Identitäten, SHA-256-Belegen, ausdrücklich fehlender Provenienz und eigenem `evidence_sha256`. Für Langzeitvergleiche ist die Zeit Teil des Evidenz-Digests; der Digest ändert sich also bei erneuter Messung auch dann, wenn die Generation unverändert ist. Die fachliche Vergleichbarkeit erfolgt über die expliziten Quellen- und Store-IDs plus Kantenstatus.

Gespeicherte Live-Messung: `docs/retrieval/repoground-s3-nixer-runtime-provenance-20261102.json`
Beobachtet: 2026-11-02T12:21:16.593786+00:00 (UTC)
Evidenz-Digest: `af9d5318a755099356d5bb1b84597c307092ef1f340cecdadbd84d283687f426`

## Nachgewiesene Kette

1. Heim-PC Git-Commit `049efc0fcddee75d5d6ddee631be6e5b42784761` deklariert im durch S1 belegten Nix-Flake die Nixer-Revision `c252b62b0fcd0bd5442681bb68d809a4b5984c61`. Diese Deklaration beweist **keinen** Build.
2. Aktive Systemgeneration und Systemprofil zeigen beide auf `/nix/store/2xy6inggq55kq8zzkhvppivm8yz0xlqn-nixos-system-heim-pc-26.05.20261025.1f607aa`.
3. `nix why-depends` belegt die Store-Kette über `etc → system-units → unit-nixer-headless.service → nixer-0.2.0`.
4. Effektives Nixer-Paket: `/nix/store/292bw8x8n77zw4bdlr247rqk11lln9iw-nixer-0.2.0`; sein Deriver: `/nix/store/dk36ajandjc88knhjzwwaza72lsmzr31-nixer-0.2.0.drv`. Das Nix-Derivation-JSON nennt den identischen Store-Output und drei konkrete Quelldateien.
5. Deren Bytes entsprechen vollständig den drei Git-Dateien von Nixer `6c1fae3936e441c43d19a7924f2f26f3539fb1d3`. Zwei Dateien entsprechen auch dem heutigen deklarierten Pin; **`server.py` jedoch nicht** (Store-SHA-256 `0576da02fd08deb7f1cdea3d92a75e573eab294128cd384c914ad400bb0a1a88` gegenüber Git-SHA-256 `741520a0cb7a469dbcc98c0aba4acf5ba504acd3c5ea51aa6cccb800df9b9703`).
6. Die wirksame systemd-Unit referenziert dieses Nixer-Paket. Der Unit-Prozess war `active` (PID 4413), seine tatsächliche Cmdline und Cgroup passten dazu.
7. Der lokale HTTP-Endpunkt `127.0.0.1:18187/mcp` antwortete auf einen einfachen GET mit **406**. Zusätzlich bestand die tatsächliche JSON-RPC-MCP-Initialisierung (`2025-06-18`), ein `tools/call nixer_status` über HTTP/SSE und die gebundene Antwort `backend.ready=true`. Der tatsächliche Werkzeugaufruf wird separat von der bloßen Erreichbarkeit ausgewiesen.

## Nachweisgrenzen

Die Übereinstimmung einzelner Git-Quelldateien mit dem Nix-Derivation-Eingang ist keine eindeutige Herkunftsidentität einer vollständigen Git-Revision. Die Quelle eines Builds kann bei mehreren Commits dieselben Dateien enthalten. Zudem fehlt weiterhin der lückenlose Beleg *vollständig evaluierter Flake-Eingabesatz → derivierter Gesamtbuild*. Die aktuelle Git-Deklaration ist nachweislich **nicht** byteidentisch mit der im laufenden Nixer-Build enthaltenen Server-Datei. Keine Schlussfolgerung, dass der aktuelle Pin ausgeführt wird, keine automatische Deployment-Änderung.

11 fokussierte positive und negative Unittests bestanden, einschließlich der Ablehnung falscher Commit-Identität aus bloßer Bytegleichheit; Ruff und C901-Prüfung bestanden. GitHub-CI, späterer Release und vollständiger produktiver Agentenweg müssen gesondert bestätigt werden.