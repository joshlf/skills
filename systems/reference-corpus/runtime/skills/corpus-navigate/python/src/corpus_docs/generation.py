"""Verified captured images and caller-known native build reservations."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib.metadata
from pathlib import Path
import sqlite3
import sys

from corpus_nav import captured, git_source, publishing
from corpus_nav import response as shared
from . import rircon
from .wire import (
    MAX_INDEX_BYTES,
    READER,
    NavError,
    canonical,
    digest,
    encoded_path,
    fits,
    hashed,
    integer,
    oid,
    parse_request,
    record,
    semantic,
    sha,
    strict_json,
)

SCHEMA = "corpus-docs-index/1"
DDL = {
    "manifest": "CREATE TABLE manifest(data TEXT NOT NULL)",
    "objects": "CREATE TABLE objects(oid TEXT PRIMARY KEY,kind TEXT NOT NULL,data BLOB NOT NULL)",
    "inventory": "CREATE TABLE inventory(path BLOB PRIMARY KEY,mode TEXT NOT NULL,kind TEXT NOT NULL,oid TEXT NOT NULL,size INTEGER)",
    "sources": "CREATE TABLE sources(path BLOB PRIMARY KEY,hash TEXT NOT NULL,data BLOB NOT NULL)",
    "documents": "CREATE TABLE documents(path BLOB PRIMARY KEY,container BLOB NOT NULL,kind TEXT NOT NULL,title TEXT)",
    "membership": "CREATE TABLE membership(document BLOB,source BLOB,role TEXT,PRIMARY KEY(document,source))",
    "headings": "CREATE TABLE headings(document BLOB,ordinal INTEGER,level INTEGER,label TEXT,start INTEGER,end INTEGER,PRIMARY KEY(document,ordinal))",
    "units": "CREATE TABLE units(id INTEGER PRIMARY KEY,document BLOB NOT NULL,start INTEGER NOT NULL,end INTEGER NOT NULL)",
    "source_fts": captured.FTS_DDL,
}
SHADOWS = captured.FTS_SHADOWS

COLUMNS = {
    "manifest": ("data",),
    "objects": ("oid", "kind", "data"),
    "inventory": ("path", "mode", "kind", "oid", "size"),
    "sources": ("path", "hash", "data"),
    "documents": ("path", "container", "kind", "title"),
    "membership": ("document", "source", "role"),
    "headings": ("document", "ordinal", "level", "label", "start", "end"),
    "units": ("id", "document", "start", "end"),
    "source_fts": ("text",),
}


require_image_support = captured.require_image_support


def reader_identity():
    root = Path(__file__).parent
    legacy = Path(shared.__file__).parent
    sources = {
        prefix + "/" + path.relative_to(base).as_posix(): sha(path.read_bytes())
        for prefix, base in (("corpus_docs", root), ("corpus_nav", legacy))
        for path in sorted(base.rglob("*.py"))
    }
    return digest(
        dict(
            reader=READER,
            sources=sources,
            sqlite=sqlite3.sqlite_version,
            markdown_it=importlib.metadata.version("markdown-it-py"),
        )
    )


def object_id(kind, data, algorithm):
    return hashlib.new(
        algorithm,
        kind.encode("ascii")
        + b" "
        + str(len(data)).encode("ascii")
        + b"\0"
        + data,
    ).hexdigest()


def _proof_inventory(snapshot, objects):
    algorithm = snapshot["object_format"]
    width = 20 if algorithm == "sha1" else 32
    for name, (kind, data) in objects.items():
        if object_id(kind, data, algorithm) != name:
            raise ValueError("Git object proof hash differs")
    commit_kind, commit = objects[snapshot["commit"]]
    if commit_kind != "commit" or commit.split(b"\n", 1)[
        0
    ] != b"tree " + snapshot["tree"].encode("ascii"):
        raise ValueError("commit does not select root tree")
    inventory = {}
    visited = {snapshot["commit"]}
    modes = {
        b"40000": ("040000", "tree"),
        b"100644": ("100644", "blob"),
        b"100755": ("100755", "blob"),
        b"120000": ("120000", "blob"),
        b"160000": ("160000", "commit"),
    }

    # A legitimate Git tree can be deeper than Python's call stack. Enter/leave
    # frames retain path ancestry without recursion, and shared subtrees are
    # still expanded under every path instead of skipped by the visited set.
    ancestors = set()
    stack = [("enter", snapshot["tree"], b"")]
    while stack:
        action, tree, prefix = stack.pop()
        if action == "leave":
            ancestors.remove(tree)
            continue
        if tree in ancestors:
            raise ValueError("cyclic tree proof")
        kind, data = objects[tree]
        if kind != "tree":
            raise ValueError("non-tree proof member")
        visited.add(tree)
        ancestors.add(tree)
        stack.append(("leave", tree, prefix))
        cursor = 0
        names = set()
        children = []
        while cursor < len(data):
            space = data.index(b" ", cursor)
            stop = data.index(b"\0", space + 1)
            mode, kind = modes[data[cursor:space]]
            name = data[space + 1 : stop]
            if (
                not name
                or name in (b".", b"..")
                or b"/" in name
                or name in names
                or stop + 1 + width > len(data)
            ):
                raise ValueError("invalid tree member")
            names.add(name)
            child = data[stop + 1 : stop + 1 + width].hex()
            path = prefix + name
            inventory[path] = (mode, kind, child)
            if kind == "tree":
                children.append(("enter", child, path + b"/"))
            cursor = stop + 1 + width
        stack.extend(reversed(children))
    if set(objects) != visited:
        raise ValueError("unrelated proof objects")
    return inventory


def _source_rows(connection):
    return connection.execute(
        "SELECT i.*,s.hash,s.data FROM inventory i JOIN sources s USING(path) ORDER BY i.path"
    )


def _coverage(connection):
    counts = {
        row[0]: row[1]
        for row in connection.execute(
            "SELECT kind,count(*) FROM documents GROUP BY kind"
        )
    }
    return dict(
        captured_files=connection.execute(
            "SELECT count(*) FROM sources"
        ).fetchone()[0],
        manifest_only_files=connection.execute(
            "SELECT count(*) FROM inventory WHERE kind!='tree' AND path NOT IN (SELECT path FROM sources)"
        ).fetchone()[0],
        tree_entries=connection.execute(
            "SELECT count(*) FROM inventory WHERE kind='tree'"
        ).fetchone()[0],
        documents=sum(counts.values()),
        document_kinds=counts,
    )


class Generation:
    def __init__(self, index, connection, manifest):
        self.index = index
        self.connection = connection
        self.manifest = manifest
        self.reader_recipe_sha256 = reader_identity()

    def context(self):
        return dict(
            index=self.index,
            snapshot=self.manifest["snapshot"],
            reader_recipe_sha256=self.reader_recipe_sha256,
            builder_recipe_sha256=self.manifest["builder"][
                "reader_recipe_sha256"
            ],
            coverage=self.manifest["coverage"],
            metadata_state="not_extracted",
        )

    def handle(self, source, start=0, end=None):
        return dict(
            index_sha256=self.index["sha256"],
            corpus_id=self.manifest["snapshot"]["corpus_id"],
            commit=self.manifest["snapshot"]["commit"],
            path_b64=encoded_path(source["path"]),
            blob=source["oid"],
            file_sha256=source["hash"],
            start_byte=start,
            end_byte=len(source["data"]) if end is None else end,
        )


def _validate(connection):
    schema = connection.execute(
        "SELECT name,type,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
    ).fetchall()
    if set(row[0] for row in schema) != set(DDL) | SHADOWS or any(
        row[1] != "table" for row in schema
    ):
        raise NavError("index_mismatch", "Unexpected native schema objects.")
    sql = {row[0]: row[2] for row in schema}
    for table, statement in DDL.items():
        if (
            sql[table] != statement
            or tuple(
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(" + table + ")"
                )
            )
            != COLUMNS[table]
        ):
            raise NavError(
                "index_mismatch", "Native schema differs from trusted reader."
            )
    # Check physical FTS schema and derived token state before reading its rows.
    # The shared helper runs only on this private in-memory SQLite image.
    captured.validate_fts(connection)
    try:
        rows = connection.execute("SELECT data FROM manifest").fetchall()
        if len(rows) != 1:
            raise ValueError("manifest cardinality")
        manifest = strict_json(rows[0][0].encode("utf-8"))
        keys = {
            "schema",
            "complete",
            "build_id",
            "semantic_request",
            "request_sha256",
            "snapshot",
            "builder",
            "build_input_sha256",
            "coverage",
        }
        record(manifest, keys, keys)
        if manifest["schema"] != SCHEMA or manifest["complete"] is not True:
            raise ValueError("incomplete native manifest")
        request = parse_request(
            "build",
            canonical(
                {
                    **manifest["semantic_request"],
                    "build_id": manifest["build_id"],
                }
            ),
        )
        if (
            semantic(request) != manifest["semantic_request"]
            or digest(semantic(request)) != manifest["request_sha256"]
        ):
            raise ValueError("semantic request mismatch")
        snapshot = manifest["snapshot"]
        keys = {"corpus_id", "object_format", "commit", "tree", "corpus_path"}
        record(snapshot, keys, keys)
        if (
            snapshot["corpus_id"] != request["corpus_id"]
            or snapshot["corpus_path"] != "."
            or snapshot["object_format"] not in ("sha1", "sha256")
        ):
            raise ValueError("snapshot mismatch")
        length = 40 if snapshot["object_format"] == "sha1" else 64
        if any(len(oid(snapshot[key])) != length for key in ("commit", "tree")):
            raise ValueError("snapshot object format mismatch")
        record(
            manifest["builder"],
            {"python", "reader_recipe_sha256"},
            {"python", "reader_recipe_sha256"},
        )
        shared.text(manifest["builder"]["python"])
        hashed(manifest["builder"]["reader_recipe_sha256"])
        objects = {
            row["oid"]: (row["kind"], row["data"])
            for row in connection.execute("SELECT * FROM objects")
        }
        proved = _proof_inventory(snapshot, objects)
        inventory = {
            row["path"]: row
            for row in connection.execute("SELECT * FROM inventory")
        }
        if {
            path: (row["mode"], row["kind"], row["oid"])
            for path, row in inventory.items()
        } != proved:
            raise ValueError("inventory differs from root tree proof")
        sources = {row["path"]: row for row in _source_rows(connection)}
        selected = {
            path
            for path, entry in inventory.items()
            if path in rircon.CONTEXT or rircon.document_kind(path) is not None
        }
        if (
            set(sources) != selected
            or not rircon.CONTEXT <= set(sources)
            or {
                row[0] for row in connection.execute("SELECT path FROM sources")
            }
            != selected
        ):
            raise ValueError("native capture coverage mismatch")
        total = sum(len(raw) for _, raw in objects.values())
        for path, row in inventory.items():
            shared.raw_path(encoded_path(path))
            if path not in sources:
                if row["size"] is not None:
                    raise ValueError("unproved manifest-only byte count")
                continue
            source = sources[path]
            data = source["data"]
            if (
                source["kind"] != "blob"
                or source["mode"] not in ("100644", "100755")
                or source["size"] != len(data)
                or source["hash"] != sha(data)
                or object_id("blob", data, snapshot["object_format"])
                != source["oid"]
            ):
                raise ValueError("captured blob identity mismatch")
            rircon.utf8(data)
            if len(data) > request["settings"]["source_bytes"]:
                raise ValueError("captured source exceeds selected bound")
            total += len(data)
        if total > request["settings"]["capture_bytes"]:
            raise ValueError("capture exceeds selected bound")
        context = {
            path.decode("ascii"): sources[path]["hash"]
            for path in rircon.CONTEXT
        }
        if context != request["required_context"]:
            raise ValueError("native context binding mismatch")
        documents = {}
        memberships = []
        expected_headings = []
        for path, source in sources.items():
            kind = rircon.document_kind(path)
            if kind is None:
                continue
            title, headings = rircon.headings(source["data"])
            documents[path] = (path, kind[1], kind[0], title)
            memberships.append((path, path, "primary"))
            memberships.extend(
                (path, context, "context")
                for context in rircon.context_paths(kind[0])
            )
            expected_headings.extend(
                (path, h.ordinal, h.level, h.label, h.start, h.end)
                for h in headings
            )
        if sorted(
            tuple(row) for row in connection.execute("SELECT * FROM documents")
        ) != sorted(documents.values()):
            raise ValueError("document identity/classification mismatch")
        if sorted(
            tuple(row) for row in connection.execute("SELECT * FROM membership")
        ) != sorted(memberships):
            raise ValueError("document context relationship mismatch")
        if sorted(
            tuple(row) for row in connection.execute("SELECT * FROM headings")
        ) != sorted(expected_headings):
            raise ValueError("heading subtree relationship mismatch")
        covered = dict.fromkeys(documents, 0)
        for unit in connection.execute(
            "SELECT * FROM units ORDER BY document,start,end,id"
        ):
            path, start, end = unit["document"], unit["start"], unit["end"]
            if path not in documents:
                raise ValueError("unit has no native primary document")
            data = sources[path]["data"]
            integer(start, 0, len(data))
            integer(end, 0, len(data))
            if (
                start != covered[path]
                or not start < end
                or not rircon.boundary(data, start)
                or not rircon.boundary(data, end)
            ):
                raise ValueError("units have a gap, overlap or split scalar")
            text = data[start:end].decode("utf-8")
            if (
                end - start > request["settings"]["unit_bytes"]
                and len(text) != 1
            ):
                raise ValueError("unit exceeds selected size")
            row = connection.execute(
                "SELECT text FROM source_fts WHERE rowid=?", (unit["id"],)
            ).fetchone()
            if row is None or row[0] != text:
                raise ValueError("FTS content differs from original unit")
            covered[path] = end
        if any(
            covered[path] != len(sources[path]["data"]) for path in documents
        ):
            raise ValueError("units omit original primary content")
        if (
            connection.execute("SELECT count(*) FROM source_fts").fetchone()[0]
            != connection.execute("SELECT count(*) FROM units").fetchone()[0]
        ):
            raise ValueError("unrelated FTS rows")
        if _coverage(connection) != manifest["coverage"]:
            raise ValueError("coverage mismatch")
        identity = dict(
            snapshot=snapshot,
            inventory=[(encoded_path(p), *proved[p]) for p in sorted(proved)],
            request_sha256=manifest["request_sha256"],
            builder=manifest["builder"]["reader_recipe_sha256"],
        )
        if digest(identity) != manifest["build_input_sha256"]:
            raise ValueError("build input identity mismatch")
        return manifest
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        AttributeError,
        UnicodeError,
        NavError,
    ) as error:
        raise NavError(
            "index_mismatch", "Invalid native manifest, proof or relationships."
        ) from error


@contextmanager
def open_image(index, image):
    with captured.open_image(
        index, image, _validate, max_bytes=MAX_INDEX_BYTES
    ) as (connection, manifest):
        yield Generation(index, connection, manifest)


@contextmanager
def open_generation(index):
    image = captured.read_image(index, max_bytes=MAX_INDEX_BYTES)
    with open_image(index, image) as generation:
        yield generation


def _capture(request, connection):
    snapshot, entries = git_source.snapshot({**request, "corpus_path": "."})
    repository = request["repository"]
    trees = {snapshot["tree"]} | {
        entry.oid for entry in entries if entry.kind == "tree"
    }
    objects = {
        snapshot["commit"]: (
            "commit",
            git_source.run(
                repository, "cat-file", "commit", snapshot["commit"]
            ),
        )
    }
    objects.update(
        (tree, ("tree", git_source.run(repository, "cat-file", "tree", tree)))
        for tree in sorted(trees)
    )
    proved = _proof_inventory(snapshot, objects)
    if proved != {
        entry.path: (entry.mode, entry.kind, entry.oid) for entry in entries
    }:
        raise NavError(
            "source_missing", "Git inventory and root-tree proof disagree."
        )
    by_path = {entry.path: entry for entry in entries}
    selected = {
        path
        for path in by_path
        if path in rircon.CONTEXT or rircon.document_kind(path) is not None
    }
    if not rircon.CONTEXT <= selected:
        raise NavError("source_missing", "Required native context is missing.")
    captured = {}
    total = sum(len(raw) for _, raw in objects.values())
    for path in sorted(selected):
        entry = by_path[path]
        if entry.kind != "blob" or entry.mode not in ("100644", "100755"):
            raise NavError(
                "unsupported_structure",
                "Required native source is not an ordinary blob.",
            )
        if entry.size > request["settings"]["source_bytes"]:
            raise NavError(
                "invalid_source",
                "Required native source exceeds selected limit.",
            )
        if total + entry.size > request["settings"]["capture_bytes"]:
            raise NavError(
                "invalid_source",
                "Required native capture exceeds selected limit.",
            )
        data = git_source.blob(repository, entry)
        rircon.utf8(data)
        if object_id("blob", data, snapshot["object_format"]) != entry.oid:
            raise NavError(
                "source_missing", "Captured Git blob identity differs."
            )
        captured[path] = data
        total += len(data)
    for path in rircon.CONTEXT:
        if (
            sha(captured[path])
            != request["required_context"][path.decode("ascii")]
        ):
            raise NavError(
                "unsupported_format", "Required native context hash differs."
            )
    connection.executemany(
        "INSERT INTO objects VALUES(?,?,?)",
        [(name, kind, data) for name, (kind, data) in objects.items()],
    )
    connection.executemany(
        "INSERT INTO inventory VALUES(?,?,?,?,?)",
        [
            (
                entry.path,
                entry.mode,
                entry.kind,
                entry.oid,
                len(captured[entry.path]) if entry.path in captured else None,
            )
            for entry in entries
        ],
    )
    for path, data in captured.items():
        connection.execute(
            "INSERT INTO sources VALUES(?,?,?)", (path, sha(data), data)
        )
        kind = rircon.document_kind(path)
        if kind is None:
            continue
        title, headings = rircon.headings(data)
        connection.execute(
            "INSERT INTO documents VALUES(?,?,?,?)",
            (path, kind[1], kind[0], title),
        )
        connection.execute(
            "INSERT INTO membership VALUES(?,?,?)", (path, path, "primary")
        )
        connection.executemany(
            "INSERT INTO membership VALUES(?,?,?)",
            [
                (path, context, "context")
                for context in rircon.context_paths(kind[0])
            ],
        )
        connection.executemany(
            "INSERT INTO headings VALUES(?,?,?,?,?,?)",
            [
                (path, h.ordinal, h.level, h.label, h.start, h.end)
                for h in headings
            ],
        )
        for start, end in rircon.unit_ranges(
            data, request["settings"]["unit_bytes"]
        ):
            cursor = connection.execute(
                "INSERT INTO units(document,start,end) VALUES(?,?,?)",
                (path, start, end),
            )
            connection.execute(
                "INSERT INTO source_fts(rowid,text) VALUES(?,?)",
                (cursor.lastrowid, data[start:end].decode("utf-8")),
            )
    return snapshot, proved


def _result(request, generation, residue):
    result = dict(
        build_id=request["build_id"],
        context=generation.context(),
        build_input_sha256=generation.manifest["build_input_sha256"],
        residue=residue,
    )
    # The format owns its complete wire envelope. A shared publisher cannot
    # size a native result using the other reader's schema prefix.
    if not fits("build", result, request["max_bytes"]):
        raise NavError("budget_too_small")
    return result


def _preflight(request, reservation, staging):
    huge = 2**63 - 1
    context = dict(
        index=dict(
            path=str(reservation / ("f" * 64 + ".sqlite")), sha256="f" * 64
        ),
        snapshot=dict(
            corpus_id=request["corpus_id"],
            object_format="sha256",
            commit="f" * 64,
            tree="f" * 64,
            corpus_path=".",
        ),
        reader_recipe_sha256="f" * 64,
        builder_recipe_sha256="f" * 64,
        coverage=dict(
            captured_files=huge,
            manifest_only_files=huge,
            tree_entries=huge,
            documents=huge,
            document_kinds=dict(
                comprehensive=huge, focused=huge, reference=huge
            ),
        ),
        metadata_state="not_extracted",
    )
    if not fits(
        "build",
        dict(
            build_id=request["build_id"],
            context=context,
            build_input_sha256="f" * 64,
            residue=[str(staging)],
        ),
        request["max_bytes"],
    ):
        raise NavError(
            "budget_too_small",
            "Native build success cannot fit before reservation.",
        )


def _make_image(request):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.enable_load_extension(False)
    connection.execute("PRAGMA temp_store=MEMORY")
    try:
        for statement in DDL.values():
            connection.execute(statement)
        snapshot, proved = _capture(request, connection)
        builder = dict(
            python=sys.version, reader_recipe_sha256=reader_identity()
        )
        request_sha = digest(semantic(request))
        identity = dict(
            snapshot=snapshot,
            inventory=[
                (encoded_path(path), *proved[path]) for path in sorted(proved)
            ],
            request_sha256=request_sha,
            builder=builder["reader_recipe_sha256"],
        )
        manifest = dict(
            schema=SCHEMA,
            complete=True,
            build_id=request["build_id"],
            semantic_request=semantic(request),
            request_sha256=request_sha,
            snapshot=snapshot,
            builder=builder,
            build_input_sha256=digest(identity),
            coverage=_coverage(connection),
        )
        connection.execute(
            "INSERT INTO manifest VALUES(?)",
            (canonical(manifest).decode("ascii"),),
        )
        _validate(connection)
        connection.commit()
        return connection.serialize()
    finally:
        connection.close()


def build(request):
    if request["reader"] != READER:
        raise NavError("unsupported_format")
    return publishing.build(
        request,
        namespaces=("docs-indexes", "docs-builds"),
        make_image=_make_image,
        open_image=open_image,
        project_result=_result,
        preflight=_preflight,
        max_image_bytes=MAX_INDEX_BYTES,
    )
