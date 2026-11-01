# RepoGround – Codex-A/B/C-Pilot R5 mit verblindeter Antwortprüfung (01.11.2026)

**Messurteil:** `not_established`. Die vollständige technische Erhebung und der native Qualitätsauswerter funktionieren; ein Qualitäts- oder Produktivitätsgewinn durch RepoGround ist **nicht** nachgewiesen. **Bericht:** [unverändertes natives R5-JSON](../diagnostics/agent-study-reports/codex-v2-r5-20261101.json). Der [historische R3-Bericht](../diagnostics/agent-study-reports/codex-r3-20261101.json) gehört ausdrücklich zu einem **anderen Protokoll**.

## Identitäten und Quellenfreeze

| Bindung | Wert |
| --- | --- |
| Run-ID | `study-20261101-codex-v2-r5` |
| Protokollschlüssel | `8d33c6baaad6464fc62b42a0a5bfb88b7352ad67e1900f136b64b37b7238778c` |
| Taskset-SHA256 | `c09d2ed62456b1ad385f82e906be38ffc2a6ba02205b535d0ef4935ba9c59980` |
| Originalplan-Datei SHA256 | `863fd49c42d18db33af0db7734820b1052efb96f0e70d5a53885b2aa142a32b6` |
| Provider / Modell | `openai-codex-cli` / `gpt-5.6-sol`, `codex-cli-0.164.0` |
| Sampling / Host / Cache | `model_reasoning_effort=medium` / `heim-pc-nixos26.05-x86_64` / `controlled` |
| Antwortvertrag | `codex-study-prompt-v2`, Erklärungstext mit SHA-gebundenem Original-JSONL-Abgleich |
| Runner | `codex-jsonl-study-v1-fbb05c2f34910a71-codex-cli-0.164.0` |
| Runner-Datei SHA256 | `fbb05c2f34910a716e8d5bd1d592357bd50826e0a31f623ab01d38f9367c6b55` |
| MCP-Implementierung SHA256 | `ba7a0555b6fd6d83bdbded3d36338195ceb06112aca146d01e88023688608240` |
| MCP-Launcher SHA256 | `ad8dbc2577601bc2db7c716977ebce83f8a61206941a6eb13d3be97c8d91cb92` |
| Toolvertrag | `codex-study-readonly-v1-mcp-ad8dbc257760-impl-ba7a0555b6fd6d83` |
| Generator-Commit | `040ab8b7bddc8e19a1459fe16374ae1934f72e77` (frisch aus eingefrorenen Git-Quellen reproduziert) |
| Zusammengeführter v2-Quellcode | [PR #1387](https://github.com/heimgewebe/repoground/pull/1387), Merge `33c93acd4454d92430fb0d4050c27b6b32eaf6b9` |

Die **Git-Quellrevisionen** sind exakt die des R3-Tasksets geblieben; die Bundle-Manifeste wurden dagegen neu mit dem gebundenen R5-Generator hergestellt. Die separat vor Publisher-GC gesicherten Studienartefakte sind keine wechselnden `main`-Publikationen:

| Repository | Frozen-Git-Commit | Manifest SHA256 |
| --- | --- | --- |
| RepoGround | `0fe8e5fd972c69b0d816b6bf124e10e6f5a43112` | `1ba064255159ba83c0e5dd22d7b52b71d3e3d7f32a7e701cf9ea1c45c1843dec` |
| Grabowski | `3fbe93d2f4c7a99c3c1aaf2c35952bac3541d98f` | `6ed1581649f96e5c59b018f24f183ac739223c56ab44edc672e8051c27b4c1c8` |
| Commonthing | `8dbc8c53ea7f26e218d419ac401eef44b29f9333` | `c29076b2f067f69682ead6068b62b596db65717f71baba61a836cfc491ea494b` |

`archive/snapshots.json`: SHA256 `3177d273910090b1ed6be7874225e1da184ba0849a2e195705303cb60a04ea2d`; `archive/frozen-index.json`: SHA256 `6af94e5dd09cfb754d11442a23936b2226b69ec613d04f59049b97d1097d9b15`. Der native Snapshot-Gate akzeptierte alle drei archivierten Manifeste nach Hash- und Quellprüfung; der Git-Goldpfad-Check fand RepoGround 9, Grabowski 2, Commonthing 2 exakt gebundene Quellpfade. Das private Archiv bleibt **außerhalb** der automatischen Publisher-Retention. Kopien müssen als gesondertes Backup erhalten bleiben; SHA und Hardlinks schützen nicht gegen nachträgliche Veränderung durch denselben Dateisystem-Writer.

## Tatsächliche 36 Agentenläufe und verblindete Begutachtung

Sechs **vorregistrierte** Pilotaufgaben, drei Bedingungen A/B/C, zwei Wiederholungen, je Versuch neue Sitzung und eigener Workspace. **36/36 echte, erfolgreiche, strukturierte Codex-Providerreceipts und gültige SHA-gebundene Originaltraces**. Der Fortschrittsbeleg enthält 35 gültige neue Abschlüsse und einen bereits vorhandenen, erneut validierten Abschluss – **keine** verdeckte Neuausführung. Alle 36 Erklärungen wurden im v2-Format als tatsächliche Modellantworten gespeichert.

Vor dem Review wurden die Arme aus dem Paket entfernt und 36 zufällige Blind-IDs separat auf die privaten Request-/Receipt-Identitäten gebunden. Sechs Quelldateien mit je sechs Review-Belegen enthalten die Bewertung anhand eingefrorener Git-Blobs. **31 Urteile `correct`, 5 `partial`, 0 `incorrect`**; 36/36 Grades besitzen `citations_checked=true`. Dies ist eine *Reviewer-Aussage*, keine maschinell bewiesene semantische Zitatpassung. Der Reviewer war ein **anderes Modell (GPT-6) als der gemessene Codex-Agent (gpt-5.6-sol)**, arbeitete aber im selben Operator-Thread; **kein** unabhängiges menschliches Review und kein extern verblindetes Reviewer-Panel. Das ist eine wichtige Evidenzgrenze.

Für die getrennte, strengere native Metrik **`quality_correct`** müssen zusätzlich zu einem `correct`-Urteil alle geforderten strukturellen Kriterien erfüllt sein. Daher sind die nativen Erfolgszahlen niedriger als 31:

| Kennzahl | A: nur Git | B: RepoGround Pflicht | C: optional |
| --- | ---: | ---: | ---: |
| Gültige Antworten / geprüfte Grades | 12/12 | 12/12 | 12/12 |
| Native `quality_correct` | **9/12** | **8/12** | **9/12** |
| Negative Fehlzuversicht | 2 | 2 | 1 |
| Unbelegte/goldfremde Pfade | 3 | 4 | 3 |
| Mittelwert Ende-zu-Ende | 24,633 s | 34,353 s | 27,252 s |
| Input-Tokens (gemeldet) | 1.582.935 | 2.522.860 | 1.947.112 |
| Cache-Input-Tokens (gemeldet) | 1.334.784 | 2.223.360 | 1.656.192 |
| Output-Tokens (gemeldet) | 24.323 | 28.927 | 26.826 |
| Tool-Aufrufe gesamt | 56 | 93 | 66 |
| Erfolgreiche RepoGround-MCP-Aufrufe | **0** | **39** | **0** |
| Vom Provider einzeln abgerechnete Kosten | unbekannt | unbekannt | unbekannt |

**Gepaarter Zeitvergleich (über sechs Aufgaben, je zwei Wiederholungen):** B minus A = **+9,720 s**, task-geclustertes Bootstrap-95-%-Intervall **[+6,148; +12,809] s**; alle sechs Aufgaben in B langsamer. C minus A = **+2,619 s**, Intervall **[−1,019; +8,611] s**. Die C-Agenten haben RepoGround **kein einziges Mal** benutzt. Dieser Arm zeigt also **keine** durch RepoGround erlangte Wirkung. Mehr Tokenverbrauch oder mehr Aufrufe sind kein Qualitätsnachweis. Einzelne Toolzeiten sind nur beobachtete Empfangszeiten der JSONL-Ereignisse und können 0 ms ergeben, ohne dass das Tool null Arbeit verrichtet hätte. Die Pilotstichprobe ist klein, die Modell-/Providerlast schwankt, und Kosten sind mangels Providerrechnung `null` statt Null Euro.

**Urteil des vorhandenen Auswerters:** `not_established`, `quality_review_complete=true`, `default_promoted=false`. Keine Produktivvorgabe zur RepoGround-Pflicht ableiten. Die nächste Verbesserung sollte einen nachprüfbaren agentischen Qualitätsgewinn pro zusätzlichem Zeit- und Tokenaufwand erreichen, nicht bloß weitere MCP-Aufrufe erzeugen.

## Unveränderte Belegkette (SHA256)

Die privaten Originaldateien verbleiben in dem zum R5-Run gehörenden Host-State und **werden nicht nach Git kopiert**.

| Private Belegdatei relativ zum R5-State | SHA256 |
| --- | --- |
| `study-plan/plan.json` | `863fd49c42d18db33af0db7734820b1052efb96f0e70d5a53885b2aa142a32b6` |
| `review-share/answers-blind.json` | `fd1a5daa12b68f1aa80b64fb714124f54f9917fc964ff5ff34b37049eaa1cc9f` |
| `review-owner/private-map.json` | `ee577e9b797119275f40a7cf273d236ddfb8707e7e872bbe0f620ba5eef23626` |
| `review-share/reviewer-verdicts.json` | `976ea80cf31d6f8f426676f8ee4c2cdbb60b1f7d2362cee1f5a177dd51e9912c` |
| `review-owner/grades-bound-r5.json` | `7b132d0f4de3aac569ac3af9915b46f1e6963ce368cd128b20c7601f61eb8a33` |
| `review-rubric-predeclared.md` | `c822c26277a78f3301ab68b3ca237f01b2b5eead7d4c94c55a72383d24ede7f7` |
| Kanonisch sortierter Index aller 36 `{request_id, receipt_sha256, trace_sha256, status}` | `3562208093f639da81a40cdf271fd6b5b78efb3ce6e4103072f9bb1e9e74a524` |
| `report-r5.json` – identisch zur versionierten JSON-Datei | `aa1a31ac7503738a0173dac52a92042be10435cd530c106376f69b7fc7eecce6` |

Die nativen CLI-Befehle `review-import` und `evaluate --grades` wurden **mit den tatsächlich gespeicherten 36 Blindgutachten und Receipts** geprüft. `review-import` band 36 einmalige Blind-IDs erfolgreich an die echten Receipts. Die erneute native In-Memory-Auswertung war in **allen Feldern außer `created_at`** byte-/strukturäquivalent zum gespeicherten R5-Bericht. Die Quellenprüfung und die Manifest-Hashes bestanden. Diese Prüfungen bescheinigen den **Datenvertrag**, nicht automatisch die inhaltliche Unfehlbarkeit der Gutachten.

## Reproduzieren, wiederholen und sauber vergleichen

Auf dem befugten Host den R5-State als `R5` setzen; das Verzeichnis enthält `study-plan/`, `receipts/`, `traces/`, `review-share/`, `review-owner/` und `archive/`. Die folgenden **create-only**-Ziele mit neuem Suffix nie überschreiben. Ohne die privaten Daten kann der Nutzer im Git-Repository nur die hier versionierten bereinigten Ergebnisreports und deren Trend lesen; Rohantworten und Reviewer-Mapping sind bewusst kein öffentliches Beweispaket.

~~~bash
python3 -B -m merger.repoground.cli.agent_study review-import \
  --plan "$R5/study-plan/plan.json" \
  --taskset docs/retrieval/repoground_agent_study_cases.v1.json \
  --receipts "$R5/receipts" --trace-root "$R5/traces" \
  --packet "$R5/review-share/answers-blind.json" \
  --mapping "$R5/review-owner/private-map.json" \
  --grades "$R5/review-share/reviewer-verdicts.json" \
  --out "$R5/review-owner/grades-bound-NEUE-PRUEFUNG.json"

python3 -B -m merger.repoground.cli.agent_study evaluate \
  --taskset docs/retrieval/repoground_agent_study_cases.v1.json \
  --plan "$R5/study-plan/plan.json" \
  --receipts "$R5/receipts" --trace-root "$R5/traces" \
  --grades "$R5/review-owner/grades-bound-NEUE-PRUEFUNG.json" \
  --measurement-scope real_runner_reported \
  --out "$R5/report-NEUE-PRUEFUNG.json"

python3 -B -m merger.repoground.cli.agent_study trend \
  --reports docs/diagnostics/agent-study-reports \
  --out "$R5/trend-NEUE-PRUEFUNG.json"
~~~

Beim Vergleich des neuen Reports mit dem originalen Hashbericht nur `created_at` als erlaubte Erzeugungszeitdifferenz ausschließen; **alle übrigen Werte müssen identisch sein**. Der Trend über die zwei hier versionierten JSON-Berichte muss **`total_runs=2` und `comparison_groups=2`** liefern: R3 hat null unabhängig geprüfte Grade, R5 hat 36 source-reviewed Grades. Der Generator ist zudem unterschiedlich, aber die Quellcommits sind identisch. Wegen anderem Prompt, Runner-SHA und Protokollschlüssel **niemals** R3 und R5 zu einem gemeinsamen statistischen Effekt verschmelzen.

Für künftige echte Runs zuerst das identische Frozen-Taskset und die Manifest-Gesundheit mit [der vorhandenen Snapshot-Archivierung](../usage/repoground-agent-study-v1.md#ergänzung-v2--antwortqualität-und-langlebige-studienquellen) festhalten, dann mit neuer Run-ID und tatsächlich gemessenem Runner-Fingerprint einen neuen Plan erstellen. Veränderte Quellcommits, Modelle, Prompts, Runner-, Host-, Cache- oder Toolverträge müssen als **neue Vergleichsgruppe** sichtbar bleiben. Der öffentliche Trend darf weder private Traces einlesen noch fehlende Grade erfinden.

**Offene wissenschaftliche Grenze:** Unabhängiges externes/humanes Zweitreview, weitere Tasksets und wiederholte Messungen an späteren Releases sind nötig, bevor ein verallgemeinerbarer kausaler Agentennutzen behauptet werden kann.
