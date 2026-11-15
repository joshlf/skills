# Agent skills

Seven reusable instruction packages for coding agents. Each package contains its
runtime instructions and any supporting references. Install complete directories;
copying only `SKILL.md` can omit required material.

| Skill | Package | Purpose |
| --- | --- | --- |
| clear-writing | `clear-writing/` | Write and revise clear nonfiction while preserving meaning. |
| commit-message | `commit-message/` | Explain the exact change and its reason in Git history. |
| model-refinement | `model-refinement/` | Simplify or generalize conceptual models while preserving their contract. |
| robust-code | `robust-code/` | Make code understandable and safe to evolve. |
| skill-authorship | `skill-authorship/` | Engineer reusable agent capabilities and keep evidence and lifecycle claims accurate. |
| reader-oriented-explanation | `reader-oriented-explanation/` | Give readers the facts and connections they need. |
| authorship-disclosure | `authorship_disclosure/` | Maintain accurate AI-authorship disclosures. |

## Installation

Download or clone a reviewed public release. For a reproducible installation,
check out a full public commit ID rather than following a moving branch. Review
the instructions before enabling them, then copy the selected complete package
directories into the host's supported skill directory. Preserve their names,
bytes, and supporting files. Do not overwrite locally modified installations.

| Host | Personal skill directory |
| --- | --- |
| Codex | `~/.agents/skills/` |
| Claude Code | `~/.claude/skills/` |
| Gemini CLI | `~/.agents/skills/` (shared alias) or `~/.gemini/skills/` |

Install once in the shared directory when Codex and Gemini use the same home.
Restart or refresh the host's skill discovery, check its skill listing, and invoke
one installed skill explicitly to confirm loading. Installation makes a skill
available; host and task instructions determine when it applies.

`commit-message` uses `reader-oriented-explanation` and separately available
`clear-writing`. `skill-authorship` uses `model-refinement` for conceptual changes.
Installing all seven covers these dependencies.

See the official [Codex](https://learn.chatgpt.com/docs/build-skills),
[Claude Code](https://code.claude.com/docs/en/skills), and
[Gemini CLI](https://geminicli.com/docs/cli/skills/) instructions for current host
behavior. These paths are installation targets, not a claim that every host version
has passed an invocation test. See [evidence and limits](docs/EVIDENCE.md).

## Development and feedback

This repository distributes selected versions. Maintainers accept development
changes separately and export reviewed releases; public contributions follow
[CONTRIBUTING.md](CONTRIBUTING.md). Supporting design explanations are under
`docs/<package>/DESIGN.md`.

Public issues and pull requests are for public-safe reports and proposed changes;
the contribution guide explains the disclosure limits and release process.
Instructions for agents using or working on this repository are in
[AGENTS.md](AGENTS.md).
