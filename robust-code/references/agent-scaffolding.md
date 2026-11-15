# Scaffolding an agent for robust code

Use this reference when setting up or evaluating a coding workflow, not as another
mandatory procedure for every edit. The model proposes code; the environment
supplies feedback; an acceptance mechanism decides what may proceed. An instruction
file does not implement the latter two responsibilities.

## Give the agent a small, executable task contract

Adapt the following to the repository. Replace bracketed fields with verified
facts, omit irrelevant fields, and use the host's supported skill-loading mechanism.
Do not assume that mentioning a filename loads it or that every host discovers
`AGENTS.md` in the same way.

```text
Task: [requested behavior and authorized edit scope].
Preserve: [API/wire compatibility, important observations, resource bounds].
Important invariant: [domain fact, owner, and places that can invalidate it].
Read: [small set of authoritative files and relevant callers].
Load robust-code through this host's supported skill mechanism.
Check: [verified commands, working directory, and environment prerequisites].
Accept only when: [observable outcomes, including negative/failure cases].
Do not weaken acceptance checks merely to accommodate the patch.
Report: the patch, its important invariant/tradeoff, actual checks, and gaps.
```

A repository instruction should supply durable local knowledge, not a duplicate
repository tour. For example: identify the validated domain type, the wire-format
compatibility rule, the authoritative transaction owner, and the correct test
command. Keep changing task state in the repository's established work tracker.

Use a small contrastive example only when it resolves a real decision boundary:
a tagged union versus correlated optional fields; an owned transition versus a
forgeable marker; a clear loop versus an opaque fold. State the governing rule so
the agent need not infer it from surface syntax. Do not make every task load a
large example catalog.

## Make useful feedback cheap to obtain

Provide a reproducible environment and one documented entry point for the checks
that actually exist. Run fast, localized checks during implementation and broader
required checks before acceptance. Return the command, exit status, relevant
location, and enough diagnostic context to fix the cause. Preserve a usable path
to full output rather than silently truncating a failure into a success summary.

For the target language and repository, select the applicable mechanisms:

| Concern | Feedback mechanism | Remaining obligation |
| --- | --- | --- |
| Invalid construction or call sequence | Opaque constructors, ownership, type checks, compile-fail callers | Check alternate constructors, casts, aliases, FFI, and external invalidation |
| New closed-set case | Exhaustiveness check | Verify the added case's semantics, not just coverage |
| Pure decision logic | Example/property tests with explicit inputs | Check that the properties describe the domain rather than restate the code |
| Stateful protocol | Transition/model tests and fault injection | Check cancellation, partial progress, concurrency, and unknown outcomes |
| Refactoring | Differential tests and compatibility checks | Separate preserved behavior from intentional corrections |
| Weak test oracle | Targeted mutation tests | Exclude equivalent or irrelevant mutants; do not optimize a bare score |
| Human comprehension | Reader explanation and extension tasks | Automated lint and code size are only partial signals |

Do not enable every strict rule or tool by default. A useful check constrains a
real obligation and produces actionable feedback at acceptable cost. Record a
required but unavailable check as a gap. Do not silently substitute a weaker one.

## Separate proposing a patch from accepting it

For an enforced gate, the operator must control the acceptance definition and
trusted execution path. Evaluate the exact candidate revision in an isolated
environment, retain the trusted checks outside its unreviewed write scope, and
inspect changes to tests, configuration, dependencies, and generated files. Avoid
privileged execution of untrusted candidate code. A checker in the writable
candidate tree can be useful feedback without being an independent gate.

This package supplies no sandbox, branch protection, permission system, or CI
installation. Configure those only with authorization and verify the actual host
behavior. A local hook is not a security boundary when the agent can bypass it.

Keep the loop bounded by the task's resources. A failed check should produce a
focused repair and recheck, not an instruction to iterate until success at any
cost. Preserve the failure when the contract, environment, or authority blocks a
sound repair. Save relevant revision and check identities for interrupted work;
re-read live state before resuming or repeating an uncertain external effect.

A separate reviewer can examine assumptions, effects, and extension hazards. Give
them the contract and patch without an expected verdict when practical. Additional
agents are not independent evidence merely because they agree, and no multi-agent
architecture is mandatory.

## Measure whether the scaffold helps

Compare under the same task contract, tools, model conditions, and resource limits:
no additional skill, a competent short instruction, and this skill. A fourth arm
can add the proposed scaffold to isolate its contribution. Existing mandatory
repository checks belong in every arm; optional new feedback can vary by arm while
the final acceptance oracle stays common.

Evaluate the initial patch and a later small change made from a fresh context.
Include failures that ordinary happy-path tests miss: adding a variant, changing a
boundary, introducing a second caller, or timing out after a write. Check both
correct behavior and the effort needed to find and satisfy the new obligation.

Have technically competent readers explain the invariant, predict failure/effect
behavior, and locate the needed extension points. Prefer blinded comparison when
feasible. Do not equate the author's self-review with a human-comprehension study.

Keep author-visible examples separate from reserved confirmation tasks. Validate
the grader against legitimate alternatives and known violations. Record all
attempts and classify task, evaluator, and infrastructure failures separately.
Report retries and actual telemetry when available; answer length is not total
cost. Re-evaluate after material changes to the model, host, instructions, or task
distribution. These are evaluation design recommendations, not results for this
skill or guarantees about future agents.
