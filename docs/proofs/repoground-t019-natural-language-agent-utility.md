# RepoGround T019: Natürlichsprachliche Agenten-Utility

## Bindung

- Bureau-Task: `REPOGROUND-AGENT-UTILITY-V1-T019`
- Ausgangscommit: `cfd341b00c6a36125a014dbfa54cf78c8215da75`
- Vorgelagerte Routing-Evidenz: `docs/retrieval/task-profile-routing-evidence.v1.json`
- Goldset: `docs/retrieval/t019-natural-language-goldset.v1.json`

## Umgesetzter Vertrag

1. **Profilgebundene Hybridroute:** `hybrid_activation.py` übernimmt die bestehende T013-Profilentscheidung. Eine Route mit `keep_opt_in` wird nur bei explizitem Opt-in aktiviert; blockierte Profile bleiben deterministisch lexikalisch. Die Aktivierung bindet Modellname und -revision, Modell- und Tokenizer-SHA-256, Embedding-Policy, Index, Bundle-Manifest, Repositorycommit und Routing-Evidenz.
2. **Mehrsprachiges Goldset:** deutsche und englische Fälle decken exakte Bezeichner, Paraphrasen, Synonyme, zusammengesetzte Fragen und echte Fehlanfragen ab. Der Paarvergleich berichtet Recall@k, MRR, Fehlertaxonomie, Latenz, Kontextbytes und Toolaufrufe.
3. **Relevanzbudget:** alle Kandidaten konkurrieren in einem gemeinsamen Pool nach Relevanz, Änderungsnähe, Belegautorität und Abdeckungsdiversität. Token- und Bytebudget sind hart. Geänderte Pfade werden unabhängig vom Retrieval-`k` aufgelöst. Jede Auslassung nennt Ursache, verletzte Budgetgrenze, Restbudget und erforderliche Größe.
4. **Kompakte Standardprojektion:** `context compile` liefert standardmäßig eine knappe Entscheidungsprojektion mit Status, Fundstellen, Bereichen, Lücken, Budget und Grenzen. `--verbose` liefert den vollständigen Plan.

## Sicherheits- und Aussagegrenzen

- Keine globale Standardaktivierung semantischer Suche.
- Ein T013-`keep_opt_in` ist keine Qualitätsfreigabe, sondern nur die Erlaubnis für einen ausdrücklich angeforderten Profilpfad.
- Ähnlichkeitswerte beweisen weder Wahrheit noch Vollständigkeit.
- Der Evaluator kann Promotion blockieren, aber nicht selbst genehmigen.
- Kompakte Projektion entfernt keine veränderlichen Status-, Bereichs-, Lücken- oder Mutationsgrenzen.

## Regressionen

Fokussierter Lauf:

```text
python3 -m pytest merger/repoground/tests/test_context_compiler.py merger/repoground/tests/test_t019_agent_utility.py merger/repoground/tests/test_task_profile_routing.py merger/repoground/tests/test_module_reachability.py -q
59 passed
```

Architektur-Reachability nach produktivem Export der neuen Verträge:

```text
python3 -m pytest merger/repoground/tests/test_module_reachability.py -q
19 passed
```

Die vollständige Suite und GitHub-CI bleiben Merge-Gates. Dieses Dokument behauptet keine reale Modellqualitätssteigerung und keine Produktionsfreigabe eines semantischen Standardpfads.
