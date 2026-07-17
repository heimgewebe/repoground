# RepoGround Artifact Output Control Plane

Status: Blueprint
Scope: RepoGround build, RepoGround service, CLI, UI, manifest and output health
Version: v0.1

Ziel: Artefaktproduktion profilierbar, beweisbar, laufzeitbewusst und UI-tauglich machen, ohne Inhaltswahrheit, Navigation, Diagnose und Cache zu vermischen.

## 0. Kernentscheidung

Nicht Artefakte hart zusammenlegen.
Nicht alle Artefakte immer sichtbar machen.
Nicht einzelne Toggles als Default anbieten.

Stattdessen:

1. Rollenmodell bleibt strikt.
2. Profile sind UI- und CLI-Presets.
3. Erzeugung und Anzeige sind getrennte Entscheidungen.
4. Jeder Schritt bleibt schemagebunden, manifestgebunden und validierbar.
5. Laufzeit- und Zugriffsfehler werden nicht zu Inhaltswahrheit hochgestuft.

## 1. Zielbild

RepoGround erzeugt nicht einfach „Dateien“, sondern einen kontrollierten Artefaktverbund mit expliziten Rollen:

- kanonischer Inhalt,
- Navigation,
- Diagnose,
- Beleg- und Provenienzflächen,
- maschinenlesbare Ableitungen,
- optionaler Cache.

Die Control Plane steuert, welche dieser Rollen für ein Profil erzeugt, veröffentlicht und in der UI angeboten werden. Sie ändert nicht die epistemische Bedeutung eines Artefakts.

## 2. Rollenmodell

### 2.1 Kanonischer Inhalt

Der kanonische Inhalt ist die einzige inhaltliche Autorität des Bundles. Alle Sidecars und Indizes müssen auf ihn zurückführen.

### 2.2 Navigation

Navigationsartefakte helfen, relevante Stellen zu finden. Sie beweisen weder Vollständigkeit noch Richtigkeit.

### 2.3 Diagnose

Diagnoseartefakte berichten über beobachtete Qualität, Verfügbarkeit oder Abweichungen. Sie dürfen keine Freigabe oder Inhaltswahrheit behaupten.

### 2.4 Beleg und Provenienz

Belegflächen binden Aussagen an konkrete Quellen, Bereiche, Hashes und Erzeugungsbedingungen. Sie ersetzen keine fachliche Prüfung.

### 2.5 Maschinenlesbare Ableitungen

Graphen, Karten, Tabellen und strukturierte Sidecars sind reproduzierbare Ableitungen. Ihre Gültigkeit hängt vom gebundenen Quellstand und ihrem Contract ab.

### 2.6 Cache

Caches verbessern Laufzeit. Sie sind austauschbar und niemals Autorität.

## 3. Profilmodell

Profile bündeln sinnvolle Erzeugungs- und Darstellungsentscheidungen. Ein Profil ist kein Qualitätsurteil.

### 3.1 Minimal

- kanonischer Inhalt,
- Bundle-Manifest,
- grundlegende Provenienz,
- minimale Navigation.

### 3.2 Review

Zusätzlich:

- Citation Map,
- Range-Auflösung,
- Symbol- und Relationsflächen,
- relevante Tests und Architekturhinweise,
- explizite Lücken.

### 3.3 Agent

Zusätzlich:

- Reading Pack,
- Retrieval-Index,
- Entry-Point- und Graphflächen,
- maschinenlesbare Kontextrollen,
- Negative Semantics.

### 3.4 Forensic

Zusätzlich:

- vollständige Hashbindungen,
- Generationstransaktionen,
- Surface- und Health-Diagnostik,
- externe Manifestreferenzen,
- reproduzierbare Prüfbelege.

## 4. Erzeugung und Veröffentlichung

Erzeugung und Veröffentlichung sind getrennt:

1. RepoGround baut eine vollständige lokale Generation in einem isolierten Ziel.
2. Alle Pflichtartefakte werden gegen ihre Schemata und Hashbindungen geprüft.
3. Erst danach wird die Generation atomar als vollständig markiert.
4. Eine Veröffentlichung bindet die geprüfte Generation an einen stabilen Zeiger oder eine externe Referenz.
5. Fehler vor dem Umschalten dürfen keine halbfertige aktuelle Generation sichtbar machen.

## 5. UI-Vertrag

Die UI zeigt Profile und Artefaktrollen, keine ungeordnete Sammlung interner Dateinamen.

### 5.1 Standardansicht

- aktuelles Profil,
- Frische und Provenienz,
- kanonischer Inhalt,
- wichtigste Navigationsflächen,
- klar sichtbare Degradation.

### 5.2 Erweiterte Ansicht

- vollständige Artefaktliste,
- Contract- und Versionsinformationen,
- Hashes,
- Erzeugungs- und Diagnosebelege,
- Legacy-Kompatibilitätsflächen.

### 5.3 Verbotene UI-Semantik

Die UI darf nicht aus einem grünen technischen Check ableiten:

- „Code ist korrekt“,
- „Review vollständig“,
- „Tests ausreichend“,
- „Änderung sicher“,
- „Merge freigegeben“.

## 6. CLI-Vertrag

Die CLI verwendet ein einheitliches Produktpräfix und beschreibende Unterbefehle. Aktuelle Beispiele:

```text
repoground build
repoground query
repoground graph
repoground ground
repoground serve
repoground mcp
```

Legacy-Befehle bleiben während RepoGround 3.x dünne Delegates. Sie dürfen keine eigene Implementierung oder abweichende Defaults enthalten.

## 7. Manifest-Vertrag

Das Bundle-Manifest ist die zentrale maschinenlesbare Bindung zwischen:

- Generation,
- Quellstand,
- Profil,
- Konfiguration,
- Artefakten,
- Hashes,
- Links,
- Fähigkeiten,
- negativen Aussagen.

Neue RepoGround-Generationen verwenden einen neuen versionierten Manifesttyp. Dokumentierte ältere Manifesttypen bleiben lesbar, werden aber nicht als neue Identität ausgegeben.

## 8. Output Health

Output Health beantwortet technische Fragen:

- Sind Pflichtartefakte vorhanden?
- Stimmen Hash und Größe?
- Sind Links auflösbar?
- Sind Schemata erfüllt?
- Sind optionale Rollen verfügbar oder bewusst ausgelassen?

Output Health beantwortet nicht:

- Ist der Repository-Inhalt korrekt?
- Ist die Änderung sicher?
- Ist eine Analyse vollständig?
- Darf gemergt oder veröffentlicht werden?

## 9. Degradation

Degradation ist explizit und additiv:

- fehlende optionale Rolle → `degraded`, nicht still ignorieren;
- fehlende Pflichtrolle → `invalid` oder `missing_required`;
- unbekannte Contract-Version → fail closed;
- Legacy-Generation → als Legacy kenntlich machen;
- Cachefehler → Laufzeitdegradation, keine Inhaltsdegradation;
- veralteter Quellstand → stale, nicht automatisch neu erzeugen.

## 10. Sicherheitsgrenzen

Die Control Plane darf nicht:

- Git als Nebenwirkung eines Lesezugriffs verändern,
- externe Befehle implizit ausführen,
- Patch- oder Merge-Autorität ableiten,
- Geheimnisse in Bundles oder Logs übernehmen,
- Pfade außerhalb gebundener Wurzeln veröffentlichen,
- unvollständige Generationen als aktuell markieren.

## 11. Kompatibilitätsstrategie

RepoGround 3.x trennt drei Klassen:

1. **kanonische Oberfläche:** RepoGround-Namen und neue versionierte Verträge;
2. **Kompatibilitätsdelegates:** alte Befehle, Modulpfade und Service-Konfigurationen mit Warnung;
3. **persistierte Altverträge:** alte Kinds, Schemanamen, URIs und Artefaktpfade, deren Bedeutung unverändert bleibt.

Ein Delegate darf entfernt werden, sobald der dokumentierte Consumer-Inventarstand keinen aktiven Verbraucher mehr ausweist. Ein persistierter Vertrag darf nur durch eine explizite neue Version abgelöst werden.

## 12. Teststrategie

Pflichtprüfungen:

- Profil- und Rollenmatrix,
- Produzent gegen Manifest-Schema,
- Leserkompatibilität für dokumentierte Generationen,
- atomare Veröffentlichung und Wiederaufnahme,
- Pfad- und Symlink-Sicherheit,
- UI-Projektion ohne Autoritätseskalation,
- CLI-Hauptweg und Legacy-Delegates,
- Namenshygiene,
- Frische- und Provenienzbindung.

## 13. Rollout

### Phase A: kanonische Oberfläche

- RepoGround-Befehle und Module bereitstellen,
- aktuelle Dokumentation umstellen,
- alte Einstiege als Delegates erhalten.

### Phase B: neue Generation

- neuen Manifesttyp ausgeben,
- Leser auf Alt und Neu testen,
- externe Veröffentlichung an Typ und Version binden.

### Phase C: Verbraucher

- externe Repositories und Dienste auf RepoGround umstellen,
- Altpfade nur solange behalten, wie reale Verbraucher belegt sind.

### Phase D: Entfernung

- Delegates erst in einem neuen Major entfernen,
- Migration und Rollback dokumentieren,
- gespeicherte Altartefakte weiterhin lesbar halten oder ein explizites Konvertierungswerkzeug bereitstellen.

## 14. Nichtziele

Dieser Blueprint begründet nicht:

- öffentliche Distributionsfreigabe,
- semantische Vollständigkeit,
- Produktreife,
- Betriebsfreigabe,
- automatische Migration externer Verbraucher.

## 15. Abnahmekriterien

Der Umbau ist für diese Control Plane abgeschlossen, wenn:

1. aktuelle CLI-, UI- und Dokumentationsflächen RepoGround verwenden;
2. jede neue Generation einen eindeutigen versionierten RepoGround-Vertrag trägt;
3. dokumentierte Altgenerationen weiterhin lesbar sind;
4. alte Programme nur Delegates sind;
5. Erzeugung, Prüfung und Veröffentlichung getrennte, fail-closed Schritte bleiben;
6. alle statischen und dynamischen Tests grün sind;
7. externe Verbraucher separat inventarisiert und kontrolliert umgestellt werden.
