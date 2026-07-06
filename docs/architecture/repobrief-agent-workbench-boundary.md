# RepoBrief Agent Workbench Boundary

This document defines the RepoBrief Agent Workbench boundary before the full Workbench exists.

It corrects one important naming distinction:

- **Agent Workbench** is the integrated, deterministic code-understanding tool layer that helps agents use RepoBrief to improve code.
- **Patch Evaluation Sidecar** is the external mutable layer for applying patches, running commands, sandboxing, and collecting evaluation evidence.

The Workbench may live inside RepoBrief when it remains deterministic and read-only. The Sidecar must stay outside RepoBrief because it mutates worktrees and runs commands.

## Purpose

RepoBrief turns repository state into deterministic, citable context. The Agent Workbench builds on that context with structured code-intelligence tools so an agent can understand a repository, plan edits, and cite the evidence behind proposed changes.

The Workbench is therefore an agent-facing analysis surface, not a release authority. It should help answer questions such as:

- Which symbols, files, ranges, tests, schemas, and docs are relevant?
- Which code paths appear connected by static evidence?
- Which cited ranges should an agent inspect before proposing an edit?
- Which evidence is missing, stale, degraded, or outside the current snapshot?

Patch application and command execution are different. They require an isolated mutable workspace and belong to the external Patch Evaluation Sidecar.

## Terms

- **RepoBrief Snapshot**: A generated repository brief at a specific generation time. It may be stale relative to the live working tree, GitHub, or a pull request.
- **Canonical Brief Source**: The canonical Markdown content inside a RepoBrief bundle. It is the content authority for the generated snapshot.
- **Brief Sidecar**: A navigation, diagnostic, evidence-index, or cache artifact associated with a snapshot. A sidecar helps locate or interpret evidence; it is not a replacement for canonical content.
- **Agent Workbench**: The integrated RepoBrief analysis/tool layer for agents. It may include AST-derived symbols, static references, relation cards, range/citation navigation, query helpers, reading-plan helpers, and other deterministic code-understanding tools.
- **Workbench Tool**: A bounded read-only helper that exposes deterministic evidence or navigation. It may compute or read static analysis artifacts; it must not mutate Git, run shells, apply patches, or claim approval.
- **Patch Evaluation Sidecar**: An external mutable evaluation layer that may create isolated worktrees, apply patches, run commands, and emit evaluation artifacts.
- **Patch Evaluation Artifact**: A future external artifact emitted by the Patch Evaluation Sidecar. RepoBrief may later read and link such artifacts, but must not produce or interpret them as approval.
- **Worktree**: A mutable checkout or workspace. Worktrees are outside the RepoBrief read-only evidence layer.

## Boundary decision

RepoBrief may grow an integrated Agent Workbench for deterministic code understanding.

RepoBrief must not grow an internal mutation axis for patch, shell, test, Git, pull-request, deployment, or sandbox operations.

The accepted architecture is:

- RepoBrief remains the evidence, snapshot, citation, and deterministic analysis layer.
- Agent Workbench tools may be integrated into RepoBrief if they are explicit, deterministic, inspectable, and read-only.
- Patch Evaluation Sidecar remains external for mutable patch application and command execution.
- CI remains an independent verification surface.
- GitHub PRs remain the review and decision surface.
- Bureau remains the task registry and status surface.
- Codex or other review agents remain review organs, not authority sources.
- Humans remain the decision authority for merges, risky boundary changes, and strategic direction.

This separates two useful ideas that should not be collapsed:

1. **Understanding workbench**: inside RepoBrief, because agents need better static evidence to edit well.
2. **Mutation/evaluation sidecar**: outside RepoBrief, because applying patches and running commands changes the authority model.

## RepoBrief responsibilities

RepoBrief may:

- explicitly create repository snapshots when a create operation is requested,
- read existing Brief Bundles,
- locate artifacts by role,
- resolve required reading for task profiles,
- report health, freshness, and availability,
- resolve ranges and citation surfaces,
- query existing indexes,
- preserve authority and canonicality metadata,
- expose read-only access helpers,
- generate or read deterministic code-understanding artifacts,
- expose Agent Workbench resources and tools for static code navigation,
- later read or link external Patch Evaluation Sidecar artifacts when they are explicitly present and identified as external evidence.

When RepoBrief reads external patch-evaluation artifacts, it may report their presence, provenance fields, availability, and declared status. It must not convert those observations into a release verdict.

## Agent Workbench responsibilities

Integrated Agent Workbench tools may support:

- Python AST symbol indexing,
- symbol-to-file and symbol-to-range lookup,
- static reference hints,
- test/schema/doc relation hints,
- graph availability reporting,
- relation cards and guard-relation goldsets,
- source/citation/range projection helpers,
- required-reading expansion,
- query routing over existing deterministic indexes,
- missing-evidence and stale-evidence reporting,
- agent planning aids that say what to inspect next.

Workbench outputs should be evidence surfaces or navigation surfaces. They can say, for example, “this function is statically located here” or “these tests appear related by configured relation rules.” They must not say “the patch is correct,” “the repo is understood,” or “this is safe to merge.”

## Explicit non-responsibilities

RepoBrief and its integrated Agent Workbench must not:

- trigger implicit refresh during read operations,
- mutate Git state as a side effect of reading,
- create branches or pull requests,
- write, apply, or repair patches,
- manage mutable worktrees,
- run shells, tests, linters, or sandboxes,
- read secrets,
- execute or orchestrate deployment actions,
- generate review verdicts,
- treat tests as release approval,
- claim runtime correctness,
- claim test sufficiency,
- claim review completeness,
- claim merge readiness,
- claim security correctness,
- introduce hidden LLM inference as a truth source,
- promote embeddings or semantic reranking into the deterministic core truth layer.

LLM-facing summaries may consume RepoBrief evidence, but they are not the canonical evidence layer. The canonical layer remains deterministic and inspectable.

## Patch Evaluation Sidecar responsibilities

An external Patch Evaluation Sidecar may:

- receive an explicit task, patch, branch, commit, or pull-request reference,
- consume RepoBrief snapshots, Workbench outputs, and citations as read-only context,
- create isolated mutable worktrees or sandboxes,
- apply proposed patches,
- run configured tests, linters, static checks, or smoke commands,
- capture command lines, exit codes, logs, changed files, and environment metadata,
- emit patch-evaluation artifacts,
- link observations back to RepoBrief citations or source ranges,
- stop with a precise report when the workspace, command policy, secrets policy, or provenance is insufficient.

The Sidecar is useful precisely because it is outside the RepoBrief core. It can be allowed to mutate an isolated workspace without weakening RepoBrief's evidence boundary.

## Agent flow

A typical agent improvement flow is:

1. RepoBrief creates or reads a snapshot of a repository state.
2. The integrated Agent Workbench exposes static code-understanding tools over that snapshot.
3. The agent consumes required reading, ranges, citations, source projection, symbols, relations, and relevant query results.
4. The agent proposes a code improvement with cited evidence and explicit uncertainty.
5. If mutable validation is needed, the external Patch Evaluation Sidecar receives an explicit evaluation request.
6. The Sidecar creates an isolated workspace, applies the patch, runs configured checks, and emits evaluation artifacts.
7. RepoBrief may later read or link those Sidecar artifacts as external evidence.
8. CI, PR review, and a human decide.

There is no reverse authority upgrade. A Workbench output or Sidecar artifact must not make an old snapshot fresh, canonical, complete, or correct. It can only add bounded observations.

## Patch Evaluation Artifact preview

The detailed Patch Evaluation Artifact contract is deferred to a later task. This document only sketches likely fields so the boundary is understandable.

A future artifact may include:

- artifact id and schema version,
- producer identity and version,
- input repository, branch, commit, pull request, or patch id,
- referenced RepoBrief snapshot or bundle manifest,
- referenced Workbench outputs,
- cited ranges or source references used as context,
- isolated workspace identifier,
- applied patch metadata,
- command policy,
- command lines and exit codes,
- captured logs or output references,
- changed-file summary,
- environment and tool versions,
- timeout and truncation status,
- declared non-claims.

This preview is not a schema. RBAW-V1-T002 owns the actual contract.

## MCP boundary

RepoBrief MCP remains a read-first boundary.

RepoBrief MCP may later expose Agent Workbench resources and read-only tools when they are deterministic code-understanding surfaces. Examples include symbol lookup, range lookup, relation lookup, required-reading resolution, and query over existing indexes.

RepoBrief MCP must not trigger Patch Evaluation Sidecar actions as a side effect of resource reads or read-only tools. It must not run shells, apply patches, create PRs, inspect secrets, or silently refresh snapshots.

A future `snapshot_create` tool is an explicit RepoBrief write exception for Brief Bundle generation only. It is not a permission to add patch, shell, test, or Sidecar authority to RepoBrief MCP.

If Sidecar control is ever exposed through MCP, it should be a separate Sidecar surface with its own authority model, not a hidden extension of RepoBrief resources.

## Security and secret boundary

RepoBrief should not require secrets to read existing bundles or expose snapshot evidence.

Integrated Workbench tools should preserve that property. They should operate over repository files, snapshot artifacts, and deterministic indexes. If a future tool needs privileged access, it should be treated as outside the read-only Workbench boundary unless a later architecture decision explicitly narrows it.

The Patch Evaluation Sidecar may need access to credentials, private dependencies, or privileged environments in some deployments. Those capabilities must be explicit, scoped, logged, redacted where necessary, and kept outside RepoBrief's deterministic read path.

Evaluation logs and artifacts must preserve enough provenance to be auditable without leaking secrets. Missing redaction or unknown secret exposure should degrade or fail the evaluation artifact, not be smoothed into success.

## Non-claims

A successful RepoBrief read, Workbench result, Sidecar run, CI job, review comment, or PR status does not by itself establish:

- `truth`
- `correctness`
- `completeness`
- `runtime_correctness`
- `test_sufficiency`
- `review_completeness`
- `merge_readiness`
- `security_correctness`
- `regression_absence`
- `repo_understood`
- `claims_true`
- `forensic_ready`

Evidence can support a decision. It is not the decision.

## Common false assumptions

### “Workbench means patch runner.”

False. In RepoBrief, the Agent Workbench is the integrated read-only code-understanding layer. Patch running belongs to the external Patch Evaluation Sidecar.

### “If RepoBrief can locate relevant tests, the patch is good.”

False. Static relation evidence helps an agent decide what to inspect or run. It does not prove that the patch is correct.

### “External Sidecar means weaker agent support.”

False. The agent can use integrated Workbench tools for understanding and the external Sidecar for bounded mutable evaluation. The split is the safety property.

### “Source Citation Projection already makes the Workbench complete.”

False. Source Citation Projection improves evidence projection across artifact and source coordinates. A fuller Workbench may still need AST symbols, relations, graph availability, and query/range helpers.

### “MCP can later just get shell access.”

False. RepoBrief MCP is read-first. Shell access crosses into Sidecar authority and must not be smuggled through a read-only resource interface.

## Risks and benefits

Integrated Workbench benefits:

- helps agents understand code with deterministic evidence,
- improves edit planning before mutation,
- reduces hallucinated file/symbol/test references,
- keeps citations, ranges, and static analysis in one evidence system,
- avoids requiring a mutable sandbox for simple code-understanding tasks.

Integrated Workbench risks:

- tool outputs can be overread as correctness claims,
- static analysis can be incomplete or stale,
- too many tools can confuse agents unless authority labels stay explicit,
- hidden LLM inference or embeddings could blur deterministic evidence if promoted without clear boundaries.

External Sidecar benefits:

- preserves the evidence/mutation boundary,
- allows structured patch evaluation,
- improves auditability through explicit artifacts,
- lets CI and GitHub remain independent control surfaces.

External Sidecar risks:

- more interfaces,
- more artifact types,
- more provenance fields to validate,
- possible confusion if Sidecar artifacts are displayed beside RepoBrief artifacts without clear authority labels.

Internal mutation-axis benefits:

- apparently simpler local agent loop,
- fewer moving pieces at first.

Internal mutation-axis risks:

- breaks the authority boundary,
- forces RepoBrief to own shell, secrets, rollback, Git, worktree, and runtime semantics,
- makes tests easier to misread as merge approval,
- turns a citation and code-understanding system into a mutable agent controller.

The decision is not “tooling or no tooling.” The decision is “deterministic understanding tools inside RepoBrief; mutable execution outside.” A good workbench has sharp tools, not a hidden flamethrower in the drawer.

## Future work

- RBAW-V1-T002: defined by [Patch Evaluation Artifact v1](../contracts/patch-evaluation-v1.md).
- RBAW-V1-T003: implemented by the read-only Patch Evaluation consumer described in [Patch Evaluation Artifact v1](../contracts/patch-evaluation-v1.md).
- RBAW-V1-T004: prototype an external Patch Evaluation Sidecar harness later, after provenance/freshness and agent-evidence hygiene remain stable.
- RBAW-V1-T005: triaged by [RepoBrief Agent Optimization Triage v1](repobrief-agent-optimization-triage.md).
