# Reference corpus toolkit

This package contains two independently useful skills:

| Skill | Purpose | Required setup |
| --- | --- | --- |
| `reference-research` | Plan research and maintain reports under the common report contract. | An explicit binding to the corpus's local policy, vocabulary and maintenance resources. |
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

The [common report contract](skills/reference-research/references/format.md)
defines report packages, precise examined subjects, evidence, applicability,
investigation limits and revalidation. Each corpus supplies its own topic
vocabulary in `CORPUS.json` and its own action/publication policy. The research
skill includes generic starters and standalone maintenance sources. A corpus can
retain a complete pinned local copy, including its own validator and tests, so
ordinary maintenance needs only Python 3.10+ and its standard library.

The navigation skill contains an ordinary Python source project under
`skills/corpus-navigate/python/`. Install it separately in a selected environment
and read the [`corpus-nav` contract](skills/corpus-navigate/references/cli.md).
It interprets `reference-corpus/1` and captures the exact selected policy, full
report contract and machine vocabulary. The navigator requires Python 3.11+ with
SQLite serialize/deserialize and FTS5. Index validation does not replace candidate
validation or semantic review of report claims.
The current program supports source capture, inventory, search and original-byte
reads. Preparation and nonempty card selections remain unsupported.

The reader verifies captured file bytes before deserializing that exact image
into a private in-memory SQLite connection. There is no fixed image-size cap;
reading/building a large image requires enough memory for the
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

Historical images and saved handles keep their own identities. Their owner
retains a complete, explicitly selected compatible reader and dependencies
outside this current runtime. The current reader rejects unsupported historical
images visibly. Installing these skills does not replace that independently
selected program or make a rebuilt index satisfy an old handle.
