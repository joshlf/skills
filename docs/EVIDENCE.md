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

*Authored by an AI agent acting on joshlf's behalf.*
