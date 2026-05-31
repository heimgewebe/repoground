# Contributing to Lenskit

> Aktualisiert am 2026-05-31.
> Diese Datei fasst die **gelebten** Konventionen des Repos zusammen. Maßgeblich
> bleiben [`AGENTS.md`](AGENTS.md) und
> [`docs/roadmap/lenskit-master-roadmap.md`](docs/roadmap/lenskit-master-roadmap.md).

## Arbeitsphilosophie: Diagnose-first

Lenskit ist ein **epistemischer Kern** — Korrektheit und Belegbarkeit gehen vor
Feature-Tempo. Die zentrale Arbeitsregel der Master-Roadmap lautet:

> **Erst diagnostizieren, dann ändern. Keine Heuristik-Patches ohne Target-Proof.**

Praktisch heißt das:

1. **Vorhandenes prüfen, bevor gebaut wird.** Viele „offensichtlich fehlende"
   Features existieren bereits (vgl.
   `docs/proofs/weiterentwicklungsplan-2026-05-reconciliation-proof.md`). Prüfe
   per `rg`/`test -f`, ob ein Feature schon da ist.
2. **Kleine, belegte Slices.** Nicht-triviale Änderungen bekommen einen
   Proof unter `docs/proofs/`, der Scope, Belege und ein explizites **STOP**
   (was bewusst *nicht* getan wurde) festhält. Siehe die `authority-risk-class-*`-
   Proofs als Vorbild.
3. **Keine Pfad-/Begriffs-Erfindung.** Rollennamen folgen
   `bundle-manifest.v1.schema.json`, nicht älteren Blueprint-Begriffen.
4. **Keine neue Wahrheitsschicht.** Diagnose-/Navigations-Artefakte sind nie
   `canonical_content`; sie dürfen `canonical_md` nicht ersetzen.

## Frontend-Parität (verpflichtend)

Jedes neue Feld im Backend-`JobRequest`-Modell
(`merger/lenskit/service/models.py`) MUSS in **beiden** Frontends umgesetzt
werden (repoLens-CLI **und** rLens-WebUI). Nach jeder Änderung an `JobRequest`
oder UI-Komponenten:

```bash
python3 tools/parity_guard.py
```

prüft Backend-Modell, CLI-Argumente (`repolens.py`), HTML-IDs (`index.html`)
und JS-Payload-Keys (`app.js`). Details: [`docs/PARITY_GUARD.md`](docs/PARITY_GUARD.md).

## Lokale Checks vor dem Commit

```bash
# Tests (pytest.ini konfiguriert die Pfade)
python3 -m pip install -r requirements-dev.txt
python3 -m pytest

# Lint (exakt wie die CI)
ruff check --select=F401,F811 --exclude='**/fixtures/**' .

# Parität (falls JobRequest/UI berührt)
python3 tools/parity_guard.py
```

Test-Fixtures unter `**/fixtures/**` sind absichtlich vom Lint ausgenommen
(sie enthalten bewusst „kaputten" Code für Linter-/Graph-Tests).

## CI-Gates (Auswahl)

PRs gegen `main` müssen u. a. grün sein bei:

- **lint** (`ruff` F401/F811)
- **Parity Gate** / **parity_check**
- **anti-hallucination-lint** (contract-statischer L3/L5-Governance-Lint)
- **contracts-validate**, **validate-merges**
- **ai-context-guard**, **wgx-guard**, **codeql**

## Commit- & Branch-Konventionen

- **Branch:** themenbezogen, kleinteilig. Automations-/Agent-Branches nutzen das
  Schema `claude/<slug>`. Nicht direkt auf `main` pushen.
- **Commit-Message:** kurz, imperativ, aussagekräftig. Conventional-Commit-
  Präfixe (`fix(...)`, `refactor(test): …`) sind willkommen; bei Track-C-Arbeit
  den Track referenzieren (`C2.x: …`) und den zugehörigen Proof nennen.
- **Eine Sache pro PR.** Diagnose, Contract-Änderung und Producer-Emission nach
  Möglichkeit trennen (so wie die C2-Serie).

## Reihenfolge beim Lesen (vor Parität/Evidence/Runtime-Änderungen)

1. [`docs/roadmap/lenskit-master-roadmap.md`](docs/roadmap/lenskit-master-roadmap.md)
2. [`docs/testing/test-matrix.md`](docs/testing/test-matrix.md)
3. die relevanten [`docs/proofs/*`](docs/proofs/)

## Was nicht tun

- Generierte Docs (`docs/_generated/*`) nicht editieren. Änderungen sind nur
  über den jeweiligen Generator erlaubt. Für Doc-Freshness lautet der Generator:
  `python -m merger.lenskit.cli.main doc-freshness update --write`
- Lokale Runtime-Artefakte nicht committen.
- Den rLens-**Launcher** (`cli/rlens.py`) nicht still als HTTP-Client
  umdeuten — der CLI-Client ist `cli/cmd_rlens_client.py`.
- Keine semantische Reranking-Priorisierung vor Belegadressierung; keine
  Federation-Härtung vor stabiler lokaler Evidence-Address (s. Roadmap
  „Nicht jetzt").

Danke fürs Beitragen — sorgfältig, belegt, klein. 🧵
