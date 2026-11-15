# Evidence and limits

These packages are instruction artifacts, not guarantees that an agent will
follow them or produce a correct result. Host configuration, model behavior,
context, tools, and task scope affect outcomes.

Public CI checks package structure, supporting local links, and the expected
seven-package composition. Those checks do not measure writing quality,
refinement success, coding reliability, privacy, or skill activation. A source
reference records provenance or rationale; it is not an independent evaluation.

This distribution includes no raw behavioral campaign, held-out result, or claim
that these versions outperform alternatives. Historical evaluations are not
silently transferred to a changed package or combination. A future public
behavioral report should identify its exact runtime bytes, dependencies, host and
model conditions, task protocol, outcomes, failures, and uncertainty. Private
supporting evidence must not be cited as though a public reader can inspect it.

## Maintainer-reported discovery check

The initial [public release](https://github.com/joshlf/skills/commit/6a63da89d7240b1083e56991ab3718fbe7862ae7)
was checked on fresh GitHub-hosted Linux and macOS 15 runners with only its
proposed public files supplied to the discovery jobs. All seven packages were
found in each of these six host/platform cases:

| Host | Version | Discovery operation |
| --- | --- | --- |
| Codex | 0.169.0 | App-server `skills/list` |
| Claude Code | 2.1.325 | SDK initialization command listing |
| Gemini CLI | 0.68.0 | `skills list` |

The tested snapshot's complete path/byte/mode inventory has SHA-256
`79e5fc738cd04ae51e8b6f14340360791821f7008555ca948d0758fcbf242151`.
These are maintainer-reported observations; the raw host-run logs are not
included here. No model turn was sent, and authenticated invocation checks were
deferred. The result establishes discovery in those conditions, not automatic
activation, instruction following or comparative effectiveness. It does not
silently apply to later changed files or host versions.

## Reproduce discovery

The [native discovery probe](../tests/probe_hosts.py) can be run from a clean
installation with the official `codex`, `claude`, and `gemini` executables on
PATH. It creates a temporary project, copies the complete packages, and uses
local listing or SDK initialization APIs without sending a user/model turn:

```sh
python3 -I -B tests/probe_hosts.py --snapshot . --output /absolute/new/results
```

The probe reports actual host versions and binds the result to a complete
path/byte/mode inventory digest. It tests discovery, not instruction following,
automatic activation, writing quality, or general reliability. Host startup can
consult its normal configuration; use a fresh account or host environment for
isolation. Do not publish local diagnostic logs without checking them for private
configuration details.

Host discovery and explicit invocation must be verified in the user's actual
installation. Documentation of an installation path is not an executed host test.
The private release review records which environments were actually exercised;
unverified combinations remain unverified.
