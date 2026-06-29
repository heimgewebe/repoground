# Graph Source Roots Consumer Proof

## Result

Issue #815 is implemented by `TASK-GRAPH-SOURCE-ROOTS-CONSUMER-001`.

The graph producer accepts optional explicit roots. Repository-relative module names remain available, and files beneath a declared root also receive a module name relative to that root.

A local edge is emitted only when one repository file claims the module name. Competing files keep an external module edge, independent of root order.

Goldset v1.2 raises local resolution from 5/7 to 7/7. The `src_layout/src` and `namespace_case` cases resolve, while the two `mod.py` candidates remain ambiguous. Other measured categories are unchanged.

Tests cover unchanged empty-root behavior, unique resolution, root-order equality, ambiguity, invalid declarations, missing directories, duplicates, and repository containment. The PR checks are green.

## Limits

No CLI or automatic bundle configuration is added. Relative imports keep their existing source context. This does not claim runtime import equivalence, graph completeness, retrieval improvement, or default-ranking readiness.
