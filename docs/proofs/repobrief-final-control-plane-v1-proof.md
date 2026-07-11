# RepoBrief Final Control Plane v1 — Proof

## Gegenstand

Dieser Slice schließt die im Audit als F-01, F-02 und F-04 bezeichneten
Kontrolllücken:

- ein roter Export-Safety-Bericht durfte die Snapshot-Erzeugung nicht als
  Erfolg verlassen;
- der Post-Emit-Health-Pass sah nicht alle später registrierten Artefakte;
- der AI-Context-Workflow besaß eine invalide leere `env`-Oberfläche und keinen
  stabilen aggregierten Checknamen für den Main-Ruleset.

## Implementierte Grenze

### Zentrale Profilsemantik

`repobrief_profiles.py` ist nun die kontrollierte Quelle für die
Exportsemantik aller Snapshotprofile. Exportbericht und Agent-Export-Gate
konsumieren dieselbe Profilentscheidung. Legacy-Profilnamen bleiben nur für
bestehende direkte Gate-/Report-Consumer kompatibel.

### Zweiphasiger Abschluss

`repobrief snapshot create` führt nach der Inhaltsproduktion zwei Phasen aus:

1. Reading Pack und Agent Entry Manifest werden einmal auf den endgültigen
   Artefaktbestand aktualisiert. Vorläufige Health-, Gate-, Export- und
   Surface-Berichte etablieren alle Kontrolllinks.
2. Der autoritative Post-Emit-Health-Pass prüft den vollständigen
   Manifestartefaktbestand. Gate, Exportbericht und Surface-Bericht werden
   danach gegen denselben Manifestzustand erneuert. Eine spätere
   Manifestmutation wird über den SHA-256-Vergleich blockiert.

Ein fail-closed Profil liefert CLI-Exitcode `1`. Die latest-complete Registry
wird nur bei erfolgreicher Finalisierung geschrieben.

### Manifest-Metadaten

Beim Aktualisieren eines bereits registrierten Artefakts werden Contract-,
Authority-, Canonicality- und Risk-Metadaten bewahrt. Die neue Abschlussprüfung
hat sichtbar gemacht, dass der frühere Refresh diese Felder verlor.

### AI-Context-Workflow

Der leere top-level-`env`-Schlüssel wurde entfernt. Ein aggregierter Job mit dem
stabilen Checknamen `ai-context-guard` verlangt erfolgreiche `repo-root`- und
`templates`-Jobs. Der gewünschte Main-Ruleset enthält diesen Check; die live
GitHub-Regel wird erst nach erfolgreichem Merge und grünem Main-Lauf angepasst.

## Dynamische Belege

Fokussierter Lauf:

```text
469 passed
```

Realer Mini-Snapshot, Profil `agent-portable`, mit `--redact-secrets`:

```text
CLI rc                         0
post_emit_health              pass
agent_export_gate             pass
export_safety_report          pass
bundle_surface_validation     pass
manifest artifacts            19
post-health artifacts checked 19
manifest SHA after health      unchanged
```

Vollständige nicht-Browser-Suite:

```text
3680 passed, 1 skipped, 13 deselected in 86.98s
```

Fünf WebUI-JavaScript-Testdateien wurden ausgeführt und bestanden.

Negativfall ohne `--redact-secrets`:

```text
CLI rc                         1
post_emit_health              pass
agent_export_gate             fail
export_safety_report          fail
```

## Sicherheits- und Autoritätsgrenzen

- Kontrollsidecars bleiben Diagnose- beziehungsweise Gateoberflächen; sie sind
  keine kanonische Inhaltsquelle.
- `post_emit_health=pass` beweist keine Claimwahrheit, Testvollständigkeit,
  Runtime-Korrektheit oder Regressionsfreiheit.
- Der Manifest-SHA-Vergleich belegt nur, dass nach dem finalen Health-Pass kein
  Manifestbyte verändert wurde.
- Ein Export-Gate prüft die modellierten Bedingungen; es garantiert keine
  vollständige Secret-/PII-Erkennung.
- Der GitHub-Ruleset-Vertrag beweist erst nach API-Readback die live wirksame
  Konfiguration.
