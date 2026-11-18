# Reference corpus toolkit

This package contains two independently useful skills:

| Skill | Purpose | Required setup |
| --- | --- | --- |
| `reference-research` | Plan research and maintain reports under a selected corpus's native rules. | A binding to that corpus's policy, format and validation procedure. No navigator installation. |
| `corpus-navigate` | Find and read original reports from an immutable captured index. | A separately installed selected executable and an explicit interpretation/source/index binding. |

The complete skill directories are under `skills/`. Each skill resolves its
supporting references from its own `SKILL.md` directory. Copy the entire selected
directory when using a host's ordinary skill-directory route. Installing the
whole package makes both entrypoints available to a compatible client; it does
not activate both skills or install the navigation program.

The root `plugin.json` uses the Agent Plugins 1.0.0 skills layout. This package
includes no MCP server or client extension. Format validation does not establish
support in a particular host. Use that host's supported discovery route and
verify the selected resources after installation.

The navigation skill contains an ordinary Python source project under
`skills/corpus-navigate/python/`. Install it separately in a selected environment;
read the complete [`corpus-nav` contract for `reference/1`](skills/corpus-navigate/references/cli.md)
before use. The navigator requires Python 3.11 or newer with SQLite
serialize/deserialize and FTS5 support. Native maintenance follows its selected
validation procedure: `reference/1` has a candidate-local standard-library
validator. Index validation does not replace it.
The current program supports source capture, inventory, search and original-byte
reads. Preparation and nonempty card selections remain unsupported.

The reader verifies captured file bytes before deserializing that exact image
into a private in-memory SQLite connection. Legacy `reference/1` adds no fixed
image-size cap; reading/building a large image requires enough memory for the
captured bytes, SQLite image and validation work. Build staging remains as a
reported hard link after publication. The cache owner explicitly retires that
residue after checking ownership and remaining consumers.

Corpus content, project policy, indexes and local bindings belong to their
respective owners. They are not part of this package. Research and maintenance
retain the corpus's native validation and publication requirements. Captured
navigation does not grant authority to change or publish corpus content.

Cache capability probes also retain their small test directories. Reported residue
is a reconciliation aid; verify its current ownership and contents before explicit
retirement. Neither a successful probe nor a returned path supplies a lease on a
mutable filesystem namespace.
