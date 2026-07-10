# CodeQL path-injection suppression ratchet

Lenskit uses a small number of inline `lgtm[py/path-injection]` comments where a
filesystem sink is protected by a project-specific validation boundary that
CodeQL does not infer. A suppression is not a security boundary and must never
replace validation.

## Source of record

`config/codeql-path-suppressions.v1.json` inventories every accepted
suppression. Each boundary records:

- the authority under which the path may be used;
- the validation that runs before the filesystem sink;
- the exact source statement and enclosing Python scope;
- the expected occurrence count and files;
- concrete regression-test node IDs.

`scripts/ci/check_codeql_suppressions.py` validates this inventory before the
CodeQL action starts. It tokenizes every tracked Python source file, including `.pyi`/`.pyw` and extensionless
Python-shebang scripts, plus equivalent local files outside excluded cache and
environment directories. Only real
comment tokens count, not marker-like text inside strings.

## Changing a suppression

1. Establish or review the runtime validation boundary first.
2. Keep the suppression inline with the exact filesystem sink.
3. Reuse a boundary ID only when authority and validation are genuinely the
   same. Otherwise create a new boundary entry.
4. Update the exact site, occurrence count, file set, rationale, and concrete
   regression-test references in the inventory.
5. Run:

   ```bash
   python3 scripts/ci/check_codeql_suppressions.py
   pytest -q merger/lenskit/tests/test_codeql_suppression_ratchet.py
   ```

6. Review the complete diff. An inventory update is evidence of an explicit
   decision, not proof that the suppression is justified.
7. Require both ordinary CodeQL success and the raw-SARIF clean gate.

The ratchet verifies that referenced pytest nodes exist. The normal test-suite
workflow remains responsible for executing them.

A source statement may move to another line without inventory churn. Changing
the statement or enclosing scope, moving it to another file, adding or deleting
an occurrence, or using an alternative, unknown, or bare suppression fails the
ratchet.

## Boundaries of the ratchet

The ratchet establishes only that suppressions are explicit, stable, and tied
to named tests and documented trust boundaries. It does not establish that the
referenced tests are sufficient, that upstream validation cannot regress, that
CodeQL has no blind spots, or that a green analysis proves runtime safety or
merge readiness.
