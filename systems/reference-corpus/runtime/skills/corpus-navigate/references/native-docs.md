# Native Markdown navigation

Use this contract only for an explicitly selected `rircon-prior-art/1` binding
and its absolute `corpus-docs` executable. The original `reference/1` API remains
[corpus-nav](cli.md); its report sections, metadata filters and request schemas
do not apply here. Native corpus policy and task authority remain separate from
navigation.

## Requests and capabilities

```console
/absolute/path/to/corpus-docs OP --request - --json < request.json
```

Send scalar UTF-8 JSON on stdin, at most 1 MiB. Every request has
`schema:"corpus-docs-OP/1"` and may have `max_bytes` (integer 0..1048576,
default 16384). That cap includes the complete response envelope and newline.
Duplicate/unknown keys, nonfinite JSON, invalid Unicode and booleans used as
integers are invalid. Use exact absolute paths; no repository, cache, executable
or generation is inferred from the current directory.

| OP | Other fields; `!` means required |
| --- | --- |
| `doctor` | `repository`, `cache` (optional absolute capability-probe paths) |
| `build` | `build_id!`, `corpus_id!`, `repository!`, `ref!`, `reader!`, `required_context!`, `cache!`, `settings`, `recipe`, `card_selections` |
| `list` | `index!`, `items`, `document`, `container`, `limit`, `continuation` |
| `read` | `index!`, `handle!`, `continuation` |
| `search` | `index!`, `query`, `document`, `container`, `literals_all`, `bounds`, `limit`, `continuation` |
| `prepare` | No fields beyond schema/max_bytes; returns `unsupported_capability` |

Run `doctor` before relying on runtime capabilities. The native reader requires
Python 3.11 or later with SQLite `Connection.serialize` and `deserialize`; the
distribution's Python floor alone does not
establish that capability. No model service or publication credential is needed.
The native SQLite image has a fixed 256 MiB limit, checked before opening and
publication. This limits image size, not total heap use or query work.

Build requires a fresh caller-known 32-character lowercase hexadecimal `build_id`,
nonempty `corpus_id`, explicit local `repository` and `ref`, the exact
`reader:"rircon-prior-art/1"`, and private absolute `cache`. Selection is at the
repository root. `ref` cannot contain NUL. `required_context` is an exact map of
these paths to lowercase SHA-256 values supplied by the binding:

- `docs/README.md`
- `docs/prior-art.md`
- `docs/prior-art/AGENTS.md`
- `docs/prior-art/README.md`

Those hashes must match the selected raw Git blobs. Do not substitute the captured
corpus commit for a report's studied upstream snapshot. Unknown readers return
`unsupported_format` before reservations. The only recipe is `source-only/1`
(default); other recipes and nonempty `card_selections` are unsupported before
new build effects.

`settings` is closed; each value is an integer 1..2147483647:

| Setting | Default | Meaning |
| --- | ---: | --- |
| `unit_bytes` | 4096 | Target original-text unit size; one UTF-8 scalar is indivisible. |
| `query_bytes` | 4096 | Maximum UTF-8 query bytes. |
| `query_terms` | 64 | Maximum distinct query terms. |
| `source_bytes` | 16777216 | Per-selected-source capture limit. |
| `capture_bytes` | 1073741824 | Captured blobs plus retained raw commit/tree proof bytes. |

## Generation, document and source identity

Keep the exact completed `index:{path:ABSOLUTE,sha256:SHA256}` returned by build.
Every opened context identifies that index, the captured corpus ID/commit/tree,
reader and builder recipe hashes, coverage and `metadata_state:"not_extracted"`.
The reader extracts native document membership, heading ranges and H1 display
labels. It does not extract upstream snapshots, lineage, evidence grades, topics,
status or applicability; `not_extracted` means neither false nor absent.

`document` and `container` are canonical base64 encodings of exact relative raw
Git paths. They are corpus-local identities, not upstream project or subject IDs.
The interpretation recognizes comprehensive `docs/prior-art/NAME/README.md`, the
three named Netstack3 studies, Zircon's architecture-evolution study and the four
required context files. Unexpected paths remain inventory-visible with exclusion
reasons. Missing, linked, non-UTF-8 or oversized required sources fail the build.

A source can serve several documents. Comprehensive reports receive the four
context sources; Netstack3/Zircon studies receive `docs/README.md` only. This
retrieval membership neither grants authoring rights nor extends the prior-art
policy to another directory. Search covers primary document content, so a term
found only in the high-recall index or shared policy does not make every report
match. The index's source/relationship checks establish captured correspondence,
not the accuracy, current applicability or completeness of original claims.

A source handle has exactly:

```text
index_sha256, corpus_id, commit, path_b64, blob, file_sha256,
start_byte, end_byte
```

The endpoints are inclusive/exclusive, ordered, within captured bytes and on
UTF-8 scalar boundaries. Empty ranges are valid. A handle has no document owner
or heading claim and is not a signature. A valid child interval remains valid
when formed from a parent handle. Pass the handle to `read` with its exact index;
a plausible path or modified source identity is insufficient.

## List, search and read

`limit` is 1..100, default 10. `list.items` defaults to `documents`; alternatives
are `sources` and `headings`:

- Documents permit exact `document` and/or `container` filters and return native
  identity/kind, nullable H1 title, context paths and a primary whole-source handle.
- Sources list the full non-tree inventory with path, mode, kind, object ID,
  optional size and capture state. Captured sources have a whole-source handle;
  manifest-only entries have an exclusion reason. An exact `document` selects its
  primary/context membership. `container` is forbidden for source listing.
- Headings require `document` and forbid `container`. They return ordinal, H-level,
  original parser label and subtree handle. A subtree starts at its heading token
  and ends before the next equal/lower H-level, or EOF. Parent/child containment
  is valid; repeated labels have distinct ordinals. Fenced heading-like text is
  not a heading. Preambles remain available through whole-source reads.

Syntactically valid unknown document/container filters yield empty results rather
than matching related subjects. A syntactically valid unknown heading document
also yields an empty list.

Search accepts the same exact document/container filters. `literals_all` defaults
to an empty array; every selected literal must occur in the complete primary
original before result limits apply. Query absence lists eligible documents in
raw-path order without ranking. A present query needs a tokenizer-recognized term
and must fit the selected query byte/term limits. Whitespace-separated terms are
sorted, deduplicated and quoted into an OR query. There are no metadata-subject,
topic or applicability selectors.

A ranked search returns the best original unit per document. BM25 ascending,
raw document path and unit ID break ties deterministically. Returned handles name
original source ranges; the tool does not manufacture quotation snippets or
technical verdicts. `bounds` is closed, with positive integer values up to
2147483647: `unit_matches` defaults to 100000 and `sqlite_steps` to 5000000.
The unit bound counts admitted eligible FTS matches before document deduplication.
The tool observes at most one additional eligible match to detect truncation;
that observation is charged to the SQLite budget and is not ranked. Query-free
inventory has no matching units, so only its SQLite, page and output bounds apply.
Truncation returns a partial ranking; SQLite exhaustion returns `work_exhausted`.

FTS matches are computed within captured units. A word or phrase split at a unit
boundary may be missed. A complete page exhausts that indexed query, not every
whole-document occurrence or relevant source. For exact text, omit `query` and
use `literals_all`, which checks complete primary-document bytes case-sensitively.
Then obtain the whole-source handle from document listing and read it. The first
unit returned by query-free search need not contain the literal.

Read accepts one verified `handle` per call. It returns at most one original-text
segment per page, with its exact handle and fragment flag. Concatenating returned
segment UTF-8 encodings exactly reassembles the selected interval. An empty range
returns an empty-text segment. If no useful scalar fits the complete JSON budget,
the operation returns `budget_too_small`; do not treat that as empty source.

List/search results contain `context`, `effective_request`, `items` and `page`;
read uses `segments` in place of `items`. Pages are:

- `kind:"complete"`.
- `kind:"more"`, with `reason:"page_limit"|"output_budget"` and `continuation`.
- `kind:"partial"`, with explicit reasons such as `unit_budget` and no exact
  continuation.

Treat continuation tokens as opaque. Keep their operation, index, reader and
semantic request unchanged. `max_bytes` and `limit` may change; source/index/scope,
filters and selected handle may not. Relocating an unchanged index permits old
handles with the relocated same-hash IndexRef, but requires a fresh list/search
request rather than an old path-bound cursor. Empty complete results do not prove
that no relevant material exists; partial rankings do not prove exhausted coverage.

## Errors and build recovery

Success is `schema:"corpus-docs-result/1",operation:OP,status:"ok",result:...`.
Errors use the same schema/operation with `status:"error",error:{code,...}`.
Exit 0 means success; exit 1 carries a bounded error envelope. If even that cannot
fit, exit 2 has empty stdout and `budget_too_small` on stderr. Keep invalid input,
missing source, unsupported capability/format, work exhaustion, corrupt/wrong
index, invalid handles/cursors and insufficient output budget distinct.

Build returns `build_id`, `context`, `build_input_sha256` and `residue`.
Reservations are `cache/docs-indexes/BUILD_ID/`; staging is
`cache/docs-builds/BUILD_ID/`. Publication is a hash-named immutable SQLite file,
using no-clobber hard links and fsync. After missing stdout or a failed/unknown
publication, inspect/retry the same request and known ID before reading source
again. A complete reservation recovers the same generation after source removal
or ref movement. Empty, corrupt, foreign and conflicting residue remains an
explicit failure; do not delete unknown state or change IDs to manufacture success.

Successful builds retain staging as explicit residue. Its payload and the published
file initially share one hard-linked body. Cache capability probes also retain
their small test directories. Reported paths aid reconciliation; they do not grant
ownership or deletion permission. Revalidate current contents and remaining uses
before explicit retirement. Namespace changes after this call attempts a new link
return `publication_unknown`. A conflicting existing reservation returns
`attempt_conflict`; an empty one returns `attempt_incomplete`. No observation
guarantees future path liveness.

Captured list/search/read works without the live repository. Native opens use
verified captured bytes in private SQLite memory, no extension loading and no
disk scratch. These controls do not review native source claims or confer
permission to change a corpus, publish reports, retire caches or install globally.
