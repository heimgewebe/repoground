---
doc_type: blueprint
status: active
initiative: LENSKIT-REPOBRIEF-AUDIT-REMEDIATION-2026-07
---

# Lenskit / RepoBrief Audit Remediation 2026-07

## Rolle

Dieser Blueprint überführt den Komplettaudit vom 11. Juli 2026 in eine
abarbeitbare Reihenfolge. Er ist ein Arbeitsplan, kein Beweis für bereits
umgesetzte Produktreife. Inhaltsclaims bleiben gegen den aktuellen Working Tree
und bei Snapshots gegen das kanonische `*_merge.md` zu prüfen.

## Ziel

RepoBrief soll für interne Operator-Arbeit nicht nur viele Diagnoseartefakte
erzeugen, sondern eine widerspruchsfreie Abschlusskette besitzen:

1. Profil- und Exportpolitik entscheiden zentral und fail-closed.
2. Der finale Health-Pass prüft exakt den finalen Manifestzustand.
3. Retrieval-Nutzen wird mit dem repo-eigenen Goldstandard gemessen.
4. CI, Browserprüfung und Lieferkette sind reproduzierbar und verpflichtend.
5. Task-, Roadmap- und Claimstatus widersprechen sich nicht.
6. Paketierung, Graphprojektion und Wartbarkeit erhalten explizite Grenzen.

## Arbeitspakete

### A — Final Control Plane (Audit F-01, F-02, F-04)

- Zentrale Exportsemantik für alle RepoBrief-Profile.
- Agent-Export-Gate und Export-Safety blockieren fehlende Redaction oder rote
  Kontrollberichte.
- Zweiphasiger Bundle-Abschluss: Inhaltsartefakte fixieren, Kontrollflächen
  etablieren, finalen Health-Pass über die vollständige Manifestmenge ausführen.
- Manifestmutation nach dem finalen Health-Pass erkennen.
- AI-Context-Workflow syntaktisch reparieren und als aggregierten Statuscheck
  für den Main-Ruleset vorbereiten.

### B — Retrieval Measurement (Audit F-03)

- `docs/retrieval/review_queries.v1.json` als kanonischen RepoBrief-Benchmark
  in den Snapshotpfad verdrahten.
- Fragen-Recall und Einzelziel-Recall getrennt ausweisen.
- Generischen Beispielbenchmark nur noch klar benannt diagnostisch führen.
- Promotion bleibt fail-closed und beweist keine Reviewvollständigkeit.

### C — CI Supply Chain (Audit F-05)

- Fremde und repo-übergreifende Actions/Workflows auf vollständige Commit-SHAs
  pinnen.
- Schreibrechte pro Job minimieren.
- Automatisierte Tests verhindern neue mutable Pins.

### D — Browser Gate (Audit F-08)

- Pytest-/pytest-playwright-Versionen kompatibel pinnen.
- Browserinstallation reproduzierbar machen.
- Die zehn Playwright-Flows in einem eigenen Pflichtjob ausführen.
- Treiberfehler von Anwendungsfehlern getrennt berichten.

### E — Status Truth (Audit F-06)

- Taskindex, Blueprint/Roadmap und Claim-Evidence gegeneinander prüfen.
- Veraltete Beschreibungen korrigieren.
- Einen Drift-Check etablieren, ohne Health-Pässe als Produktreife umzudeuten.

### F — Release and Packaging (Audit F-09)

- Lizenzentscheidung dokumentieren.
- Reproduzierbare Abhängigkeits-/Lockstrategie festlegen.
- Versionierte Release-, Hash-, Upgrade- und Rollbackoberfläche definieren.

### G — Graph and Maintainability (Audit F-07, F-10)

- Test-, Fixture-, Script- und Produkteinstiegspunkte getrennt projizieren.
- `unknown`-Schichtanteil messbar reduzieren oder ausdrücklich begrenzen.
- Komplexitätsratchet: keine neuen C901-Überschreitungen.
- Große Orchestrierungsfunktionen schrittweise in kleine, testbare Einheiten
  zerlegen.

## Reihenfolge und Gates

1. A muss vor agent-portabler Neuveröffentlichung abgeschlossen sein.
2. B und D liefern den Nutzungs- und UI-Nachweis.
3. C und E härten Lieferkette und Steuerwahrheit.
4. F und G schließen Produktisierung und langfristige Wartbarkeit.

Jedes Paket benötigt:

- aktuellen Diff und kritisches Self-Review,
- passende lokale Negativ- und Positivtests,
- grüne GitHub-CI auf dem unveränderten PR-Head,
- einen Proof mit expliziten Nichtaussagen,
- Taskindex-/Board-Reconciliation.

## Nichtaussagen

Der Abschluss dieses Plans beweist nicht automatisch:

- vollständiges Repositoryverständnis,
- Abwesenheit aller Schwachstellen oder Regressionen,
- semantische Wahrheit aller Claims,
- Test- oder Reviewvollständigkeit,
- Runtime-Kausalität oder Graphvollständigkeit,
- Eignung für unüberwachten externen Betrieb.
