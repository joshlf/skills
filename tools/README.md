# Stage a selected skill artifact

`skill_packages.py` makes a checked copy of one explicit artifact into a **new**
directory. It accepts a standalone skill root or the skills-only Agent Plugins
1.0.0 producer profile. It does not install skills, activate plugins, install a
skill's dependencies, switch a live selection or remove existing files.

Use Python 3.9 or later and a separate environment for these packaging tools:

```sh
python3 -m venv /abs/packaging-env
/abs/packaging-env/bin/python -m pip install --only-binary :all: --require-hashes \
  -r /abs/release/tools/requirements.txt
```

For an intact copy, preserving package-owned shared files and their geometry:

```sh
/abs/packaging-env/bin/python -I -B /abs/release/tools/skill_packages.py \
  --source /abs/release/systems/example/runtime \
  --destination /abs/new-staging-directory --layout intact
```

For a complete copy of one skill subtree, with its original internal paths:

```sh
/abs/packaging-env/bin/python -I -B /abs/release/tools/skill_packages.py \
  --source /abs/release/systems/example/runtime \
  --destination /abs/new-skill-staging-directory --layout skills --skill example
```

Omitting `--skill` selects every offered skill. A subset is supported only for
the `skills` layout. Each invocation stages one artifact; independently created
flat stages are not checked for conflicts with each other or installed copies.

The JSON result includes actual file hashes/modes, source correspondence and
`operational_closure: "not_checked"`. It proves structural correspondence, not
that a skill works independently. Supported local Markdown references must
survive the chosen layout, but scripts can read resources that a Markdown scan
cannot find. Review the operation's declared resources and dependencies and test
them after relocation before treating a leaf copy as a usable delivery. Preserve
an intact package when a skill needs package-owned parent resources.

Directory capture rejects symlinks, unsupported entries, empty directories and
portable-name collisions. Copying uses captured bytes rather than reopening the
source. `captured_content_sha256` identifies that observed source tree; it does
not prove an atomic revision of a changing directory. Use a reviewed immutable
checkout, or pass `--expected-content-sha256` with a previously reviewed inventory
hash when that exact identity is required.

An existing destination is an error. A failed write leaves its reported staging
residue for inspection. The tool does not clean up unknown files or retry against
an active installation. Reconcile baseline, local edits and proposed resources
under the host's supported installation/update procedure. Package metadata and
successful staging grant no action authority or host compatibility guarantee.
