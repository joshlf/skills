# Evidence and limits

These packages are instruction artifacts, not guarantees that an agent will
follow them or produce a correct result. Host configuration, model behavior,
context, tools, and task scope affect outcomes.

Public CI checks the ten standalone packages, any grouped runtime artifacts
present in the release, and supporting local links. Exact source comparison
separately checks that a selected artifact was not omitted. Those checks do not
measure writing quality, refinement success, coding reliability, privacy, or skill
activation. A source reference records provenance or rationale; it is not an
independent evaluation.

This distribution includes no raw behavioral campaign, held-out result, or claim
that these versions outperform alternatives. Historical evaluations are not
silently transferred to a changed package or combination. A future public
behavioral report should identify its exact runtime bytes, dependencies, host and
model conditions, task protocol, outcomes, failures, and uncertainty. Private
supporting evidence must not be cited as though a public reader can inspect it.

## Maintainer-reported common-corpus qualification

The `reference-corpus/1` runtime has one shared report contract, explicit instance
vocabulary and optional `corpus-nav-index/2` navigation. The standalone checker
and its 40 tests ran with isolated, no-site Python 3.10.12. On macOS with
Python 3.14.8 and Linux with Python 3.12.16, the 84-case integrated suite
reported 83 passes and one sandbox-related skip. A separate Mac cell tested
filesystem write denial.

The selected navigation wheel's 13 imported modules matched its source. Installed
Mac Python 3.14.8 and Linux Python 3.11.18 operations exercised capture, listing,
search, original-byte reads and same-ID recovery. Mac-created images and saved
handles also read exactly on Linux Python 3.11 and 3.12. Separate continuation
checks denied authoring-source access and network; a Mac sandbox additionally
denied filesystem writes. These are maintainer-reported observations under those
specific conditions; raw qualification logs and retained historical payloads are
not distributed here.

The current reader visibly rejects older image envelopes. Owners of old images
and handles must retain their explicitly selected compatible reader and runtime;
a new installation or rebuilt image does not preserve that identity. These
checks establish neither automatic skill activation nor comparative usefulness.
Authenticated Claude Code and Gemini CLI behavior remains untested for this
release. Historical discovery observations below retain their original scope.

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

The [native discovery probe](../tests/probe_hosts.py) uses the official `codex`,
`claude`, and `gemini` executables on PATH. It also requires a separately verified
complete release inventory and a reviewed `skill_packages.py` outside the tested
snapshot. Its Python environment needs the packaging dependencies pinned in
`tools/requirements.txt`.

```sh
/abs/packaging-env/bin/python -I -B tests/probe_hosts.py \
  --snapshot /abs/release \
  --expected-inventory /abs/verified-inventory.json \
  --tooling /abs/reviewed-tooling/skill_packages.py \
  --output /abs/new/results
```

The inventory has `inventory` and `content_sha256` fields produced from the
separately checked complete selection. Deriving it only from the tested snapshot
would not independently detect a whole artifact omitted from that snapshot. The
probe creates a temporary project, copies complete selected skill directories,
and uses local listing or SDK initialization APIs without sending a model turn.

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
