# RepoBrief Release Packaging v1 — Abschlussbeleg

## 1. Zielbindung

- Technischer Commit: `6fe256e69b072af0c5d25e1ea0eb4dd613608510`
- Git-Baum: `7141dbc87cb48af3a1e1057dd3835c79bd7a18d2`
- Release-Version: `2.4.0-rc.1`
- Kandidat: `2.4.0-rc.1-g6fe256e69b07`
- Lizenzkennung: `LicenseRef-RepoBrief-All-Rights-Reserved`
- Distribution: `blocked_without_separate_written_permission`

Dieser Beleg bindet den lokalen Kandidatenpfad an den technischen Commit vor
Hinzufügen dieses Proof-Dokuments. PR- und Main-CI erzeugen deshalb Kandidaten
für ihre jeweils neueren Heads und sind getrennt nachzuweisen.

## 2. Deterministischer Kandidat

Zwei voneinander getrennte Ausgabeverzeichnisse wurden aus demselben sauberen
Git-Commit gebaut und mit `diff --recursive --brief` verglichen.

Ergebnis:

- Archivdateien bytegleich;
- Manifeste bytegleich;
- `SHA256SUMS` bytegleich;
- 922 verfolgte Git-Einträge;
- 923 Tar-Mitglieder einschließlich normalisiertem Wurzelverzeichnis;
- Archivgröße: 2.115.896 Byte;
- Archiv-SHA-256:
  `50a755fa97f52cc23c6083f059eed12fbc750aa6beaec202a9c2c0b75d3607af`;
- Manifest-SHA-256:
  `bc581af402e834cec7be74900ac88ee8379c42507c7b20a11c77e0f97d395fab`.

Der Source-bound-Verifier bestätigte für beide Ausgaben:

- Commit und Git-Baum;
- vollständige Pfadmenge und Dateiinhalte;
- Datei-, Ausführungs- und Symlinkmodi;
- normalisierte UID, GID, Tar- und Gzip-Zeitstempel;
- Kandidatenname aus Version und Commit;
- vier eingebettete Lockdateien samt Größe und SHA-256;
- restriktive Lizenzgrenze;
- expliziten Ausschluss der Semantik-/Torch-Erweiterung.

Das Manifest validierte gegen
`repobrief-release-candidate.v1.schema.json`.

## 3. Abhängigkeitsbeleg

Die vier Locks wurden im digestgebundenen Playwright-Python-3.12-Container
regeneriert. Vorher- und Nachher-Hashes waren identisch:

| Lock | SHA-256 |
|---|---|
| Runtime | `d977d718585a787d68c646b27f7f9add248e0e3a4b4b9b2c53ecdf4733cdf2e4` |
| Entwicklung | `92883d9c1bb09cd8940b4059b62c86c26af8a1f7683ce939e4043aa720cd5a0e` |
| Browser | `8439f7aee554a7e1d225258b9301a0ecbbbebb666fddae7a4a070cd55ed17ff1` |
| Lock-Werkzeug | `bde91235736edee6a36ade1a5ea79eca17221c9efee192557465610061d96d51` |

Alle vier Locks wurden mit `--require-hashes` in getrennte leere Zielpfade
installiert. Zusätzlich bestanden:

- `pip-tools==7.5.3`, `pip==26.1.2`, `setuptools==83.0.0` aus dem Werkzeug-Lock;
- 22 Fokusprüfungen in der isolierten Entwicklungsumgebung;
- Chromium-Runtime-Smoke mit Chromium `149.0.7827.55`;
- zehn von zehn Browser-Flows.

## 4. Fälschungs- und Governance-Prüfungen

Die fokussierte Endprüfung umfasste 130 Tests. Darin enthalten sind
Negativfälle für:

- schmutzige Git-Arbeitsbäume;
- nichtleere Ausgabeverzeichnisse;
- zusätzliche Kandidatendateien;
- manipulierte Archive und Manifeste;
- falsche Lockhashes im Manifest;
- aus dem Archiv ausbrechende Symlinks;
- unhashte oder nicht exakt gepinnte Anforderungen;
- Lockverbraucher ohne passenden Workflow-Pfadtrigger.

Zusätzlich bestanden:

- RepoBrief-Release-Contract: vier Locks, null Findings;
- Status-Truth: 92 Tasks und 92 Boardzeilen, null Findings;
- Planning-Registration-Ratchet: null Drift;
- GitHub-Actions-Pin-Check;
- Reusable-Workflow-Contract-Check;
- YAML-Parsing aller Workflows;
- repo-weiter Ruff-Ratchet.

## 5. PR-, Main- und Ruleset-Abschluss

Pull Request [#978](https://github.com/heimgewebe/lenskit/pull/978) wurde nach
einem fünfstufigen, Head- und Diff-gebundenen Self-Review gemergt. Der Review
fand einen materiellen P2-Punkt: Der Verifier erzwang die im Manifest
behauptete Tar-Mitgliedsreihenfolge noch nicht. Head
`43d35717f3613459cc1699f0977de6dc207ae38b` schloss diese Lücke und ergänzte
einen Fälschungstest, der ein neu gehashtes, aber umsortiertes Archiv abweist.

Der vollständige PR-Diff war vor dem Merge gebunden an:

- Head: `43d35717f3613459cc1699f0977de6dc207ae38b`;
- SHA-256: `b0c804969d9a33b0fe20b76b1c00757612f39c51c5f8998d08caa91e89176d2f`;
- 45 geänderte Dateien und 3.595 geänderte Zeilen laut Review-Gate.

Der Merge erfolgte mit `--match-head-commit` als
`50de5cd4c95f473fff5d6420d0e8c99ba92771bf`. Der Merge-Commit hat den
geprüften PR-Head als zweiten Elterncommit; sein Baum ist mit dem PR-Head
identisch, es gab keine Konfliktauflösung oder zusätzliche Mergeänderung.

Auf dem PR-Head und anschließend auf dem Merge-Commit bestanden alle
beobachteten GitHub-Prüfungen. Insbesondere:

- PR `release-candidate`: Run `29152972829`, Job `86545378664`;
- Main `release-candidate`: Run `29153314855`, Job `86546260543`;
- Main `pytest-full`, `browser-tests`, `webui-js-tests`, beide CodeQL-Pfade,
  Ruff, AI-Context, Forensic Preflight sowie die Graph- und Vertragsprüfungen:
  abgeschlossen mit `success`.

Der aktive Repository-Ruleset `18784275` wurde am 2026-07-11 um
14:56:57 Uhr MESZ um den Pflichtkontext `release-candidate` mit
`integration_id=15368` erweitert. Die API-Rückleseprüfung gegen
`config/github-main-required-checks.v1.json` ergab `status=pass` und null
Findings. `test-suite.yml` läuft ohne Pfadfilter auf jedem Pull Request gegen
`main`; der neue Pflichtcheck kann daher auch bei reinen Dokumentations-PRs
erzeugt werden.

`.github/grabowski-required-checks.json` spiegelt dieselben acht
Pflichtkontexte für künftige Head- und Diff-gebundene Grabowski-Reviews. Es
ist ein Prüfkatalog, keine zweite GitHub-Wahrheit; der Live-Ruleset bleibt die
Laufzeitinstanz.

## 6. Grenzen

Dieser Beleg etabliert nicht:

- eine öffentliche Verbreitungs- oder Open-Source-Lizenz;
- Produkt-, öffentliche Release- oder Deployment-Reife;
- Laufzeitkorrektheit oder Testvollständigkeit;
- Abwesenheit von Schwachstellen;
- einen reproduzierbaren Semantik-/Torch-Stack;
- dauerhafte GitHub-Verfügbarkeit oder Korrektheit jedes Pflichtchecks.

Die öffentliche Lizenzentscheidung und der Semantik-Lock bleiben getrennte,
kanonisch registrierte Folgetasks.
