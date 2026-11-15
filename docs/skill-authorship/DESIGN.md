# Skill authorship: design

This package governs creating, changing, evaluating, consolidating, and
retiring reusable agent capabilities. Merely executing another skill is outside
that scope. Settled link, wording, or formatting corrections need the relevant
narrow checks rather than a new capability-design exercise.

Keep four things distinct: the governing behavioral contract, the
implementation, evidence about that implementation, and its lifecycle or action
disposition. A well-written instruction does not establish that an agent
follows it. A successful evaluation does not grant authority to publish or
activate it. Historical failures and unknown outcomes remain evidence rather
than becoming claimed passes after a rewrite.

When the work changes the behavioral model, model-refinement owns conceptual
comparison and stopping. This package retains authoring responsibilities such
as representation, evidence calibration, packaging, and authorized delivery.
Duplicating a second refinement loop would increase effort without adding an
independent check; omitting authoring checks because refinement converged would
lose separate obligations. Runtime guidance and maintainer intent also have
different loading needs, so supporting development material stays outside
routine skill use.

Behavioral trials, structural checks, host discovery, and maintainability
probes support different claims. Use the smallest check sufficient for the
requested decision, without asking a structural validator to certify
effectiveness. Reopen the model if repeated failures show that an agent cannot
locate the governing contract, that evaluations reward a weakened obligation,
or that deployment claims exceed the evidence. A local evaluator or packaging
defect should be repaired at that layer without silently changing the
capability’s behavioral contract.

The [runtime instructions](../../skill-authorship/SKILL.md) govern execution.
See [evidence and limits](../EVIDENCE.md) for the scope of public validation.

*Authored by an AI agent acting on joshlf's behalf.*
