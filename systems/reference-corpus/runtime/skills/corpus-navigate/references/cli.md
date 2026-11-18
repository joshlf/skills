# Corpus navigator CLI contract

Invoke the absolute executable selected by the project binding as
`corpus-nav <operation> --request - --json`, supplying one strict UTF-8 JSON
request on stdin. This document defines the closed interface, including the optional preparation
contract. This release supports source-only navigation. `prepare` and nonempty
card-selection requests return `unsupported_capability` before effects. Optional
preparation requires separate implementation and qualification.
A hinted build with no selected cards may record `none_selected`, with source
coverage only. Check release evidence and `doctor` results before reliance; this
contract alone establishes neither implementation nor host support.

This is the wire/data specification for the corpus navigator. It defines one
domain tool's interfaces, not a common family manifest or approval protocol.
Types below are closed records: unlisted fields are invalid, `?` means optional,
and omitted fields take the stated defaults. Explicit null is invalid unless
listed. Integers exclude booleans. Strings are Unicode scalar text; no Unicode
normalization changes source, literal or identity values.

## Shared types and canonicalization

- `Hash`: 64 lowercase SHA-256 hex digits. `Oid`: full lowercase Git object ID
  whose length agrees with the recorded object format. `AbsPath`: explicit
  absolute filesystem path. `RawPath`: canonical padded base64 of relative Git
  path bytes relative to the selected corpus root (all wire `path_b64` fields
  use that base); reject NUL, absolute paths and `.`/`..` components. Structural
  paths use exact ASCII spellings, even though support paths can be arbitrary bytes.
- `IndexRef = {path: AbsPath, sha256: Hash}`. Verify the selected file; never use
  its basename or build-input key as sufficient proof of identity.
- `Selector`: nonempty map of nonempty identity-coordinate strings to nonempty
  values. Keys/values match exactly within one subject entry. It never matches
  descriptive subject `name`; matching names do not establish identity.
- `Handle = {index_sha256: Hash, corpus_id: string, commit: Oid, package: string|null,
  path_b64: RawPath, blob: Oid, file_sha256: Hash, start_byte: integer,
  end_byte: integer}`. Byte offsets satisfy `0 <= start <= end <= file_size` and
  UTF-8 boundaries. Package is null only for captured governing documents outside
  report packages. Verify the complete relation, not fields independently.
- `Bounds = {unit_matches: integer, sqlite_steps: integer}`; both positive and
  at most 2147483647. Defaults are 100000 unit rows and 5000000 SQLite instructions.
  An instruction budget uses a progress handler every 1000 steps, so that bound can
  overshoot by at most 999 instructions; it is not a wall-clock/CPU deadline.
- `Filters = {topics_any?: string[], subjects_all?: Selector[],
  literals_all?: string[]}`, default empty arrays. Topic and literal strings must
  be nonempty. Arrays with set meaning are deduplicated; every literal must occur
  in complete captured original prose or admitted support text, independently of
  units. Topic alternatives use OR; subject selectors and literals use AND.

Canonical JSON is `json.dumps(value, sort_keys=True, separators=(",", ":"),
ensure_ascii=True, allow_nan=False)` encoded as ASCII, with no trailing newline.
Reject duplicate keys before canonicalization. Materialize defaults; sort/dedup
set-like arrays and selectors by their canonical bytes. Query semantics are OR
over distinct whitespace-separated quoted terms, not AND or a phrase. Different
terms can therefore match different units/reports. The empty explicit query or
one with no tokenizer-recognized term is invalid; omitted query permits browsing.

For cursors, canonicalize the semantic request after removing `continuation`,
`max_bytes` and `limit`; include index hash, operation, normalized query, filters,
context targets, selection and work bounds. Bind also the reader distribution/
SQLite/tokenizer recipe identity. A presentation cap/page size can change on the
next page; semantic/ranking or work settings cannot. Cursor is canonical JSON
encoded as base64 with `{schema:"corpus-nav-cursor/1", operation, index_sha256,
request_sha256, reader_recipe_sha256, next}`. Validate every field and recompute
the request digest. It carries no authority and contains no executable expression.

`next` is an operation-specific resume position, with these closed variants:

```text
{kind:"report", package:string}                          # list reports
{kind:"admission", package:string, recipe_sha256:Hash,
 requested_card_sha256:Hash}                             # list admissions
{kind:"source", path_b64:RawPath}                        # list sources
{kind:"rank", ordinal:integer}                          # search: next zero-based item
{kind:"read", section_ordinal:integer, byte_offset:integer}
{kind:"prepare", package:string}                        # prepare: last emitted package
```

Reports and prepare use ascending package-path bytes; admissions use the full
package/recipe/requested-card tuple; sources use ascending raw path bytes.
Key-based positions resume strictly after their recorded key. Rank
ordinals resume in the fully computed deterministic ranking. Read positions name
the next byte of the selected section/handle (handle selection has ordinal0).
Reject a kind that disagrees with operation/selection, a missing ordering key,
out-of-domain position or mismatched digest. Do not persist cursor objects in the
index. A partial ranking has no exact-ranking continuation.

Prepare's selected package universe/order is fixed by request and immutable index.
Card inventory/admission state is freshly observed per page, not an atomic snapshot
of mutable output directories. Cards created after an earlier page do not
rewrite that page's observation; a fresh scan can revisit it. Build revalidates
every actual selected card before use. This needs no cursor/inventory service.

## Closed request variants

Requests are at most 1 MiB of UTF-8 before decoding. All contain their exact
`schema` below. `max_bytes` defaults to 16384 and is an integer in 0..1048576.
`limit` defaults to 10 and is an integer in 1..100.
`continuation` is optional cursor text. CLI subcommand must agree with schema.

| Operation/schema | Other fields and defaults |
| --- | --- |
| `doctor` / `corpus-nav-doctor/1` | `repository?: AbsPath`, `cache?: AbsPath`, `max_bytes?`. Check runtime/FTS always; Git controls only with repository; filesystem publication only with cache. Missing inputs yield `not_examined`, not pass. Cache probes use a fresh synthetic subdirectory and retain its last-known path as residue; no corpus mutation. |
| `build` / `corpus-nav-build/1` | Required `build_id` (32 lowercase hex digits, caller supplied), `corpus_id` (nonempty), `repository: AbsPath`, `ref` (nonempty local ref/commit), `corpus_path` (relative structural path or `.`), `format:{reader:"reference/1",sha256:Hash}`, `cache:AbsPath`. Optional `recipe:"source-only/1"|"hinted/1"` defaults source-only; `settings`, `card_selections:CardSelection[]` default empty; `max_bytes?`. No continuation. |
| `search` / `corpus-nav-search/1` | Required `index:IndexRef`. Optional `query:string`, `filters:Filters`, `target_subjects:Selector[]` (default empty, annotations only), `bounds:Bounds`, `limit?`, `max_bytes?`, `continuation?`. |
| `list` / `corpus-nav-list/1` | Required `index:IndexRef`. Optional `items:"reports"|"admissions"|"sources"` defaults reports, `package?:string` (sources only), `filters:Filters`, `limit?`, `max_bytes?`, `continuation?`. Only reports accepts nonempty filters; admissions enumerates package/card records, sources enumerates captured and manifest-only entries. |
| `read` / `corpus-nav-read/1` | Required `index:IndexRef`, `select:ReadSelection`. Optional `max_bytes?`, `continuation?`. |
| `prepare` / `corpus-nav-prepare/1` | Required `index:IndexRef`, `recipe_sha256:Hash`, `cards_directory:AbsPath`. Optional `packages:string[]` defaults all, `selected_cards:CardSelection[]` defaults empty, `limit?`, `max_bytes?`, `continuation?`. Recipe digest identifies the bound preparation instructions/schema. Read-only planning; no model calls or filesystem writes. |

`settings` has only positive integer fields `unit_bytes` (4096), `query_bytes`
(4096), `query_terms` (64), `metadata_bytes` (1048576), `report_bytes` (16777216),
`capture_bytes` (1073741824), and `support` with either `{mode:"inventory"}`
(default) or `{mode:"utf8",max_file_bytes:integer}`. All integers are at most
2147483647. These effective values enter recipe identity; a supported recipe
cannot reinterpret evidence or arbitrary Markdown headings.

`ReadSelection` is exactly one of:

```text
{kind:"handle", handle:Handle}
{kind:"package", package:string, sections?:Section[]}
```

`Section` is Summary, Applicability, Findings, Boundaries, Evidence or Revalidation.
Omitted sections means Summary/Applicability/Boundaries in that order. Requested
sections are unique and returned in native report order. Each result segment has
an exact handle and text; no cross-section synthetic quotation. `read` does not
accept a filesystem source path or fetch instruction. `list items=sources` returns
whole-file handles for captured report, support and governing documents, including
files that no search matched. A caller finds a known raw relative path in that
bounded inventory, then reads its handle without Git or a checkout. Manifest-only
entries have no handle and remain `source_unavailable`; listing is not capture.
Card debugging uses `list items=admissions`. Selected identities/coverage accompany
all data results.

### Card selections, jobs and completed cards

`CardSelection = {package:string, recipe_sha256:Hash, path:AbsPath, sha256:Hash}`.
Its hash identifies exact canonical completed card bytes, not a directory name or
latest timestamp. Build accepts selections only with hinted recipe; source-only
rejects a nonempty list. Hinted build with an empty list builds raw-source-only
coverage with explicit `hints:none_selected`. It does not scan a card directory.

Admit at most one selection per package/recipe. Duplicate selections for that key
are `invalid_request` before build effects. A selected missing, malformed, stale,
hash-mismatched or foreign-package card is rejected with a reason and contributes
no hints; the build remains available with original source. Results include counts
and actual enabled channels. Full per-card decisions are retained in the manifest
and visible through admissions listing. This is documented optional degradation,
never a silent claim that requested hints were present or faithful.

`prepare` validates its explicit selected-card list against the selected generation
and recipe. Treat `cards_directory` as the cache's cards root: inspect only
`<root>/<source-fingerprint>/<recipe-sha256>/<card-sha256>.json` for each selected
package. Do not scan other fingerprints/recipes or select by timestamp. Ignore
temporary/non-card filenames; malformed completed candidates produce rejections.
The total precedence is: a valid explicit selection makes `ready`; otherwise
one or more usable candidates make `needs_selection`; otherwise return preparation inputs.
Report a rejected explicit selection alongside whichever branch applies. Even
one unselected candidate requires explicit choice. No branch claims semantic
quality from structural admission.

Each pending item returns this closed input description inline:

```text
JobSpec = {schema:"corpus-nav-job/1",job_key:Hash,input_index:IndexRef,
 package:string,source_fingerprint:Hash,recipe_sha256:Hash,
 inputs:[{path_b64:RawPath,file_sha256:Hash}],cards_directory:AbsPath}
```

The initial recipe requires exactly the package's REPORT.json and REPORT.md plus
captured FORMAT.md context. Sort their identities by raw path. `job_key` hashes
canonical fingerprint, recipe and selected input identities, not itself or physical
directories. Every call constructs the description with its current selected index
and card destination; there is no old job manifest to reuse/rebind. A different
input-resource shape needs a deliberately supported recipe contract, not a hash
substitution that silently changes the selected operation's requirements.

A missing cards directory means no completed cards; permission/enumeration failure
is `io_error`, not an empty successful inventory. Preparation never creates the
directory. Its result is reproducible planning input, not a worker claim, assignment
or completion certificate. A caller may save it through an authorized native
handoff, but the toolkit owns no job-file lifecycle. Lost stdout is retried as a
read-only operation over the same generation/recipe and current card observations.
If a required description cannot fit the response cap, return `budget_too_small`;
never silently materialize a large file instead. Its initial input list carries
three identities, not source contents or a whole-support inventory.

The ordinary preparer reads the selected guidance and originals and writes a
candidate card to a unique temporary file in the selected fingerprint/recipe
subdirectory. It closes/validates the candidate, computes canonical bytes/hash,
then atomically publishes without overwrite as `<card-sha256>.json`. Temporary
files are not completions; conflicting same-name bytes are corruption. The card is:

```text
{schema:"corpus-nav-route/1",source_fingerprint:Hash,recipe_sha256:Hash,
 generator:string,entries:[{text:string,
 anchors:[{path_b64:RawPath,file_sha256:Hash,start_byte:integer,end_byte:integer}]}]}
```

Generator is a nonempty reported label or `unknown`. Routing text and anchors are
nonempty; anchor paths use the corpus-relative base but must belong to this
package's REPORT.json/REPORT.md inputs. FORMAT is context, not a report anchor.
Fingerprint binds corpus ID, package path/tree and governing contract blobs. Build
recomputes these allowed source/hash relationships; it needs no original job file.
Structural admission does not establish semantic quality or publication authority.

Fresh-session resumption reruns planning: valid explicit selection is ready;
otherwise any valid candidates need selection; otherwise return preparation inputs.
Torn, stale, malformed or foreign completions are reported/ignored with reasons.
User then calls build with a new ID, the same selected source and explicit card
selections to produce H. Original G remains unchanged and source-only usable.
Concurrent preparers may duplicate work; inline descriptions do not supply a lease. No background or mutable job-success state exists.

## Closed response records

The following notation expands types in place; it is not a permissive free-form
payload. Arrays preserve their stated order. `Count` is an integer in 0..2^63-1.
`BuildId` is the request's 32 lowercase hex digits. `Metadata` is exactly the
validated REPORT.json shape in native FORMAT.md. `Operation` is the six CLI names.
`SemanticRequest` is the request's closed schema projected by the canonicalization
algorithm above; no other fields may appear. `Section` and Handle are as defined
above. No status below establishes applicability or authority.

```text
Snapshot = {corpus_id:string,object_format:"sha1"|"sha256",commit:Oid,
            tree:Oid,corpus_path:string}
HintState = {kind:"disabled"} | {kind:"none_selected"}
          | {kind:"selection",admitted:Count,rejected:Count}
Coverage = {captured_files:Count,manifest_only_files:Count,hints:HintState}
Context = {index:IndexRef,snapshot:Snapshot,recipe_sha256:Hash,
           reader_recipe_sha256:Hash,coverage:Coverage}
PageEnd = {kind:"complete"}
        | {kind:"more",reason:"page_limit"|"output_budget",continuation:string}
        | {kind:"partial",reasons:("unit_budget"|"output_budget"|"page_limit")[]}
Quote = {handle:Handle,text:string}
Target = {selector:Selector,state:"recorded_match",subject_ordinals:Count[]}
       | {selector:Selector,state:"not_recorded"}
Score = {kind:"bm25",value:number} | {kind:"rrf",value:number}
RouteMatch = {text:string,anchors:Handle[]}
SearchItem = {package:string,title:string,rank:integer|null,score:Score|null,
              channels:("source"|"hints")[],handles:Handle[],quotes:Quote[],
              routes:RouteMatch[],targets:Target[]}
ReportItem = {package:string,title:string,metadata:Metadata}
Admission = {package:string,recipe_sha256:Hash,requested_card_sha256:Hash,
             state:"admitted"|"rejected",reason:string}
SourceBase = {path_b64:RawPath,package:string|null,mode:string,
              object_kind:"blob"|"commit",oid:Oid,size:Count|null,
              role:"metadata"|"prose"|"contract"|"support"}
SourceItem = SourceBase + {state:"captured",file_sha256:Hash,handle:Handle}
           | SourceBase + {state:"manifest_only",reason:string}
Rejection = {hash:Hash|null,reason:string}
CandidateCard = {path:AbsPath,sha256:Hash}
PrepareItem = {package:string,state:"ready",card:CardSelection,rejections:Rejection[]}
            | {package:string,state:"needs_selection",candidates:CandidateCard[],
               rejections:Rejection[]}
            | {package:string,state:"needs_preparation",job:JobSpec,
               rejections:Rejection[]}
Check = {name:"runtime"|"git"|"publication",state:"passed"|"failed"|"not_examined",
         detail:string}

DoctorResult = {checks:Check[],residue:AbsPath[]}
BuildResult = {build_id:BuildId,context:Context,build_input_sha256:Hash,
               report_count:Count,residue:AbsPath[]}
SearchResult = {context:Context,effective_request:SemanticRequest,
                items:SearchItem[],page:PageEnd}
ListResult = {context:Context,effective_request:SemanticRequest,
              items:ReportItem[]|Admission[]|SourceItem[],page:PageEnd}
ReadResult = {context:Context,effective_request:SemanticRequest,
              segments:[{handle:Handle,text:string,fragment:boolean}],
              other_sections:[{section:Section,handle:Handle}],page:PageEnd}
PrepareResult = {context:Context,effective_request:SemanticRequest,
                 preparation_recipe_sha256:Hash,items:PrepareItem[],page:PageEnd}
```

`+` merges the listed closed fields. `SourceItem` mode is the actual six-digit Git
mode; commit/submodule entries have null size and cannot be captured. A captured
handle covers the complete file. Its package is null only for captured governing
documents. A manifest-only item outside report packages also has a null package;
it records a source entry outside any report package and has no readable handle.
Its role is `support` unless it is a governing document.
The list request's `items` selects exactly one array variant, even for an empty
array. Captured flags cannot be used without their required handle/hash.

HintState is disabled for source-only, none_selected for hinted-empty, otherwise
selection with admitted+rejected equal to the nonzero requested selection count.
Actual enabled channels derive from admitted>0: source always, hints only when
present. Admission reason is `accepted` for admitted; rejection reasons identify
missing/io/hash/JSON/schema/source/recipe/anchor/Unicode failure. They are diagnostic
strings, not an extensible instruction or success policy.

Search channels are nonempty, unique and ordered source then hints. Handles are
nonempty verified original-source handles; quotes are an optional bounded subset
whose text exactly reencodes its range. Routes contain generated text and source
anchors, never original-source quotations. Rank is one-based for text search and
null for filter-only browsing, as is score. BM25 lower values rank first; RRF higher
values rank first; package breaks ties. Scores are finite numbers, not probabilities.
Recorded target matches have nonempty ordinals; not_recorded has none. Read handle
selection has empty other_sections; package view supplies the unselected sections.

PageEnd partial has nonempty unique reasons and no continuation; more always has
a validated cursor; complete has none. A prepare item selects exactly its state's
fields. Zero candidates return preparation inputs, one-or-more unselected candidates require
selection, and a valid explicit selection is ready. Context coverage concerns the
immutable index; preparation's current file observations are in its items instead.

Success is `{schema:"corpus-nav-result/1",operation:Operation,status:"ok",
result:ResultForOperation}` with the exact matching result type above. Failure is
`{schema:"corpus-nav-result/1",operation:Operation,status:"error",error:Error}`.
`Error = {code:ErrorCode,message?:string,build_id?:BuildId,checks?:Check[],
residue?:AbsPath[]}`. Checks are allowed only for doctor capability failure;
residue is allowed for doctor and build errors as a bounded observation or last-known path,
not permission to delete paths or proof that an uncertain publication failed.
Small caps may omit it; the error code/build ID and known recovery directory
remain usable. Doctor success has no failed check; requested failure uses error.
The closed version1 error-code set is `invalid_request`, `binding_missing`,
`binding_conflict`, `unsupported_format`, `unsupported_structure`, `source_missing`,
`invalid_report`, `index_missing`, `index_mismatch`, `invalid_query`, `invalid_handle`,
`source_unavailable`, `cursor_mismatch`, `work_exhausted`, `budget_too_small`,
`unsupported_filesystem`, `attempt_incomplete`, `attempt_conflict`,
`publication_unknown`, `io_error`, `unsupported_capability`. Missing optional cards
are admission records, not whole-build errors. Small caps omit optional error
details, not the code.

Filter eligibility is established before LIMIT/report collapse. SQLite instruction
exhaustion is an error, not empty success or a fully computed ranking. A completed
SQL iterator stopped at the unit-row budget may return a clearly partial ranking
over observed candidates, with no exact-ranking cursor. Output pagination of a
complete ranking instead retains the full ordering. Source-only and hint ranks
collapse units per report before report-level reciprocal-rank fusion.

All serialized bytes count, including newline/escaping. Page fitting must make
progress or return `budget_too_small`; it cannot issue a repeating zero-progress
cursor. If even the fixed minimal error envelope cannot fit, stdout is empty,
exit2 and stderr is exactly `budget_too_small\n`. Other errors exit1 with fitting
JSON; success exits0. Error messages/details are omitted rather than exceeding
the cap. Human output is a bounded rendering of the same result; programmatic
clients use `--json`. Neither renderer generates replacement report summaries.

## Captured SQLite image runtime

The navigator requires Python 3.11 or newer and a SQLite build supporting
serialize/deserialize and FTS5. It opens an ordinary selected file through a
no-follow, nonblocking descriptor, captures its bytes and verifies their expected
hash before deserializing exactly those bytes into a private in-memory database.
SQLite never reopens the original pathname. Schema, full FTS shadow structure,
derived token/docsize integrity and original-source relationships are checked
before the private connection becomes query-only. Sorting stays in memory and
extension loading is disabled.

Legacy `reference/1` imposes no new fixed image-size cap. Callers must provision
memory for captured image bytes, the SQLite image and validation work. Changes in
reader code/SQLite identity invalidate old cursors through the existing recipe
binding; old supported IndexRefs and source handles retain their schemas and
original payload identities.

## Build effect ordering and recovery

The caller knows `cache/indexes/<build_id>/` before any response. This is an
exclusive publication reservation, not a mutable current pointer. Its only valid
completed content is one ordinary file named `<actual-sha256>.sqlite`. That name
supplies the expected payload hash after lost stdout; recovery verifies it rather
than legitimizing changed bytes by computing a new hash. The manifest contains
build ID, canonical semantic request identity, resolved snapshot, recipe, counts
and completion facts; it contains no hash of its own complete database bytes.

Before any reservation/build effects, preflight a fitting success shape using
actual path/input lengths, fixed hash lengths and worst-case bounded counts and
one residue-directory path. If the ID directory does not exist, create it with
exclusive mkdir; exactly one caller becomes its builder. Use private staging at
`cache/builds/<build_id>/payload.sqlite`, creating a fresh staging directory;
an existing staging path conflicts and is never overwritten or silently cleaned.
Resolve the ref once, capture selected inputs and construct/validate the database
in memory, then serialize its complete image. Write a new payload exclusively
through the owned staging-directory descriptor and sync it. No request/result
sidecar is required. Request identity excludes max_bytes/build ID, and includes all source,
recipe and card selections. A different output cap is permitted on retry.

Before publication, construct and budget-check the complete BuildResult with the
staging-directory residue. Hard-link the exact closed payload without overwrite
between the retained directory descriptors, sync the reservation, and verify its
bytes/schema/manifest. Keep the staging hard link and report its directory as
residue; build performs no automatic cleanup. The two links initially share one
payload allocation. Explicit retirement requires current ownership/consumer checks.
The ID directory is the stable recovery surface; there is no separate saved
success result. Any exception from an attempted link is conservatively
`publication_unknown`; retry inspects the known reservation.

A same-ID retry first inspects that directory, before resolving a ref or rebuilding:

- Missing directory: preflight and attempt exclusive creation as a new operation.
- Empty directory: return `attempt_incomplete`; do not infer builder death, reuse
  the reservation, publish another payload or delete its staging.
- Exactly one canonical hash-named ordinary file: verify filename hash, complete
  schema and manifest, including ID and semantic request. Return its same IndexRef
  and immutable facts, plus freshly observed staging residue. A mismatched request
  is `attempt_conflict`; corrupt bytes/schema are `index_mismatch`.
- Any unexpected or multiple entries: `attempt_conflict`, with no replacement,
  deletion or best-match choice. A race where exclusive mkdir reports existence
  returns through these same branches, never a second builder for that ID.

The operator must quiesce an incomplete builder before explicit cleanup/new-ID
rebuilding. A completed reservation is immutable until explicit retirement;
ordinary retry never deletes or rewrites it. Distinct IDs can build concurrently
and may retain separate identical-byte copies; cross-ID deduplication is not
promised. Payloads/old handles still use actual SHA-256 identity, independently of
which caller ID names the directory. Explicitly selected relocated complete files
can be opened through IndexRef; build emits only verified published references.

Publication and result delivery remain separate observations. A lost stdout after
successful publication is recovered by the known directory's sole hash-named file;
a moved ref is never re-resolved for that success. A crash after reservation but
before publication remains visibly incomplete. Retained staging can change between retries and is reported as a current
observation, not an immutable historical claim. Before returning a build/recovery
result, observe that the named cache/reservation/payload still select the retained
directory/file identities and verified bytes. A changed namespace blocks success
(`attempt_conflict` before a link attempt, `publication_unknown` afterward).
These observations supply no lease, atomic future-liveness promise or security
boundary against arbitrary same-UID mutation after the checks. Retirement considers reservation, staging, handles and remaining consumers;
removing a cache pathname is not rollback of corpus state or an external effect.

Acceptance must trace empty/valid/corrupt/conflicting directories, simultaneous
same/different IDs, close/publication/output/cleanup interruptions, moved refs and
response caps. Local mkdir/no-clobber/fsync behavior must be tested on advertised
filesystems; these are proposed guarantees, not executed durability evidence.
