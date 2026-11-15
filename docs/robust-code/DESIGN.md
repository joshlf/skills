# Robust code: design

This package applies to code design, implementation, debugging, refactoring,
and review when human understanding and safe evolution matter. Its scope is the
authorized change. It does not turn a bounded fix into permission for an
unrelated architecture rewrite.

The desired result is code whose valid states, data dependencies, effects, and
checks are easy to trace. Prefer representations that reject plausible mistakes
or produce focused errors. Keep non-obvious invariants close to their enforcing
boundary and test the behavior that matters rather than only a motivating
example.

Functional data flow and typestate can make invalid sequences conspicuous, but
mandatory functional syntax or a generic effect framework can increase the
burden. A simple local loop or runtime variant can be the clearer choice. The
package therefore states engineering preferences under actual correctness,
compatibility, and resource constraints. Its supporting references provide
examples and agent-scaffold guidance when the task needs them.

Types and prompts cannot keep an external fact current: remote writes may need
conditional updates and uncertain outcomes need reconciliation. Passing tests
do not establish human comprehension or general safety. A new use that
repeatedly requires bypassing a representation, or a mutation that violates an
invariant without a focused diagnostic or test, supplies evidence to revisit
the design. The skill itself should change when its guidance consistently
encourages abstractions whose cost exceeds the preserved benefit.

The [runtime instructions](../../robust-code/SKILL.md) govern execution.
See [evidence and limits](../EVIDENCE.md) for the scope of public validation.

*Authored by an AI agent acting on joshlf's behalf.*
