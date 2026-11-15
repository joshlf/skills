# Agent instructions

## Installing skills

When installing these skills, download or clone a reviewed public release. For a
reproducible installation, check out a full public commit ID rather than following
a moving branch. Review the instructions before enabling them.

Install complete package directories, including supporting references; copying
only `SKILL.md` can omit required material. Preserve directory names, bytes, and
supporting files. Do not overwrite locally modified installations. Package
directories live at the repository root; `authorship-disclosure` is in
`authorship_disclosure/`.

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
`model-refinement` for conceptual changes. Installing all seven packages covers
these dependencies.

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
