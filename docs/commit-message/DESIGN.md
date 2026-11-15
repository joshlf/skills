# Commit messages: design

This package applies when drafting or reviewing Git commit messages, including
squashes, reverts, and backports. It does not authorize creating a commit or
changing history. The message must describe the actual recorded change against
its relevant parent or comparison base.

The subject identifies the change; the body preserves the reason a history
reader needs beyond the diff. A squash describes the final net result rather
than concatenating intermediate messages. Validation claims must belong to this
artifact and environment. Contributor attribution, disclosure, and project-
specific formatting remain applicable obligations.

The package delegates shared explanation decisions to reader-oriented-
explanation and applies separately available clear-writing guidance for prose.
Copying those general methods into every commit-writing rule would duplicate
their maintenance; making this package only a pointer would omit Git-specific
responsibilities. The resulting composition keeps the artifact-specific
contract here, at the cost of obtaining the relevant peer guidance through the
host.

A subject-only message can be sufficient when the change explains itself. A
rigid template requiring a long rationale for every change would add noise; an
unrestricted brevity rule could lose the reason needed to preserve a subtle
invariant. If peer guidance is unavailable, the skill identifies the limitation
rather than inventing it. Evidence of misleading squash descriptions,
unsupported test claims, or small changes repeatedly receiving unnecessary
essays would justify revisiting the boundaries or examples.

The [runtime instructions](../../commit-message/SKILL.md) govern execution.
See [evidence and limits](../EVIDENCE.md) for the scope of public validation.

*Authored by an AI agent acting on joshlf's behalf.*
