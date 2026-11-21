# Agent instructions

## Installing skills

When installing these skills, download or clone a reviewed public release. For a
reproducible installation, check out a full public commit ID rather than following
a moving branch. Review the instructions before enabling them.

Install complete package directories, including supporting references; copying
only `SKILL.md` can omit required material. Preserve directory names, bytes, and
supporting files. Do not overwrite locally modified installations.

Standalone package directories live at the repository root;
`authorship-disclosure` is in `authorship_disclosure/`. A release may also contain
native multi-skill artifacts at `systems/<name>/runtime/`, with entrypoints under
their `skills/` directory. Do not let a flat-root scan silently omit these.
See [structural staging](tools/README.md) for intact or selected-subtree copies.
Staging does not establish operational resource closure: qualify the selected
skill's resources and dependencies after relocation before installation. Native
plugin metadata does not establish a host's support or activate every skill.

| Host | Personal skill directory |
| --- | --- |
| Codex | `~/.agents/skills/` |
| Claude Code | `~/.claude/skills/` |
| Gemini CLI | `~/.agents/skills/` (shared alias) or `~/.gemini/skills/` |

Install once in the shared directory when Codex and Gemini use the same home.
Restart or refresh the host's skill discovery, check its skill listing, and invoke
one installed skill explicitly to confirm loading.

See the official [Codex](https://learn.chatgpt.com/docs/build-skills),
[Claude Code](https://code.claude.com/docs/en/skills), and
[Gemini CLI](https://geminicli.com/docs/cli/skills/) instructions for current host
behavior. These paths are installation targets, not a claim that every host version
has passed an invocation test. See [evidence and limits](docs/EVIDENCE.md).

## Using skills

Installation makes a skill available; the host and task instructions determine
when it applies. A reference to another skill can acknowledge applicable policy
without requiring automatic activation. Follow each skill's stated composition
requirements: `commit-message` uses separately available
`reader-oriented-explanation` and `clear-writing`; `skill-authorship` uses
`model-refinement` for conceptual changes; `research-wheel` runs standalone and
optionally composes with `reference-research`, `corpus-navigate`,
`model-refinement`, or separately installed coordination, efficiency,
supervision, or domain skills when present without requiring unselected
packages; `swarm-model-refinement` requires `model-refinement` (failing closed
without launching a refinement swarm when unavailable), uses Python 3.8+ standard
library for its optional `scripts/holdout-seal.py` helper when file-based
sealing is supported, and optionally composes with separately installed packages
such as `skill-authorship` or `reference-research` without requiring unselected
packages. Installing the nine standalone packages covers the standalone
dependencies. Grouped skills state their own additional requirements.

The reference-corpus runtime offers independent `reference-research` and
`corpus-navigate` skills. Research adopts the complete `reference-corpus/1`
report contract and needs an explicit corpus binding, local action policy and
topic vocabulary in `CORPUS.json`.
Its complete leaf includes standalone standard-library maintenance sources and
generic starters; it needs no navigator installation. Retain a pinned complete
local copy when offline interpretation or maintenance is required. Navigation
also needs its separately installed program and an explicit source/index/operation
binding. The current `corpus-nav-index/2` captures the complete policy, format and
vocabulary; older images require their separately selected compatible readers.
Read the complete [toolkit overview](systems/reference-corpus/runtime/README.md) before configuring it.
Skill discovery alone installs neither program dependencies nor project bindings.

## Contributions and feedback

Follow [CONTRIBUTING.md](CONTRIBUTING.md) when proposing changes. This repository
distributes selected versions; maintainers accept development changes separately
and export reviewed releases. Supporting design explanations are under
`docs/<package>/DESIGN.md`; see [evidence and limits](docs/EVIDENCE.md) before
making claims about validation or effectiveness.

A package's source URL describes provenance, not permission to publish task data.
Before opening a public issue, remove private context and use a public-safe
reproduction. For private tasks, follow the host or task's authorized reporting
route. If no safe private route exists, retain a local draft rather than posting
private details publicly.
