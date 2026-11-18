"""Captured immutable SQLite files and caller-known publication reservations."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

from . import __version__, captured, git_source, publishing, reference_format
from .response import (CONTRACT_PATHS, NavError, canonical, digest, encoded_path, fits, hashed,
                       integer, oid, parse_request, raw_path, record, semantic,
                       sha, strict_json, text)

SCHEMA = "corpus-nav-index/2"
INTERPRETATION = "reference-corpus/1"
CONTRACT_FILES = tuple(path.encode("ascii") for path in CONTRACT_PATHS)
TABLES = {
    "manifest": ("data",),
    "reports": ("package", "title", "metadata"),
    "sources": ("path", "package", "mode", "kind", "oid", "size", "role", "hash", "data", "reason"),
    "sections": ("package", "ordinal", "name", "path", "start", "end"),
    "subjects": ("package", "ordinal", "name"),
    "coordinates": ("package", "ordinal", "key", "value"),
    "topics": ("package", "topic"),
    "units": ("id", "package", "path", "start", "end", "fragment"),
    "routes": ("package", "text", "anchors"),
    "source_fts": ("text",),
}
DDL = (
    "CREATE TABLE manifest(data TEXT NOT NULL)",
    "CREATE TABLE reports(package TEXT PRIMARY KEY,title TEXT NOT NULL,metadata TEXT NOT NULL)",
    "CREATE TABLE sources(path BLOB PRIMARY KEY,package TEXT,mode TEXT NOT NULL,kind TEXT NOT NULL,oid TEXT NOT NULL,size INTEGER,role TEXT NOT NULL,hash TEXT,data BLOB,reason TEXT)",
    "CREATE TABLE sections(package TEXT,ordinal INTEGER,name TEXT,path BLOB,start INTEGER,end INTEGER,PRIMARY KEY(package,ordinal))",
    "CREATE TABLE subjects(package TEXT,ordinal INTEGER,name TEXT,PRIMARY KEY(package,ordinal))",
    "CREATE TABLE coordinates(package TEXT,ordinal INTEGER,key TEXT,value TEXT,PRIMARY KEY(package,ordinal,key))",
    "CREATE TABLE topics(package TEXT,topic TEXT,PRIMARY KEY(package,topic))",
    "CREATE TABLE units(id INTEGER PRIMARY KEY,package TEXT,path BLOB,start INTEGER,end INTEGER,fragment INTEGER)",
    "CREATE TABLE routes(package TEXT,text TEXT,anchors TEXT)",
    captured.FTS_DDL,
)


def reader_identity() -> str:
    root = Path(__file__).parent
    sources = {p.relative_to(root).as_posix(): sha(p.read_bytes())
               for p in sorted(root.rglob("*.py"))}
    return digest(dict(distribution="corpus-nav/" + __version__, sources=sources,
                       sqlite=sqlite3.sqlite_version,
                       markdown_it=importlib.metadata.version("markdown-it-py"),
                       tokenizer="unicode61", query="quoted-whitespace-or/1"))


def recipe_identity(request: dict, reader: str) -> str:
    return digest(dict(recipe=request["recipe"], settings=request["settings"],
                       format=request["format"], reader=reader))


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def coverage(connection: sqlite3.Connection, recipe: str) -> dict:
    captured, excluded = connection.execute(
        "SELECT sum(data IS NOT NULL),sum(data IS NULL) FROM sources").fetchone()
    return dict(captured_files=captured or 0, manifest_only_files=excluded or 0,
                hints=dict(kind="disabled" if recipe == "source-only/1" else "none_selected"))


class Generation:
    def __init__(self, index: dict, connection: sqlite3.Connection, manifest: dict):
        self.index = index
        self.connection = connection
        self.manifest = manifest
        # Context and every cursor from this opened view name the same reader.
        # The stored builder identity remains a separate historical fact.
        self.reader_recipe_sha256 = reader_identity()

    def context(self) -> dict:
        return dict(index=self.index, snapshot=self.manifest["snapshot"],
                    format=self.manifest["semantic_request"]["format"],
                    recipe_sha256=self.manifest["recipe_sha256"],
                    reader_recipe_sha256=self.reader_recipe_sha256,
                    coverage=self.manifest["coverage"])

    def handle(self, row: sqlite3.Row, start: int = 0, end: int | None = None) -> dict:
        return dict(index_sha256=self.index["sha256"],
                    corpus_id=self.manifest["snapshot"]["corpus_id"],
                    commit=self.manifest["snapshot"]["commit"], package=row["package"],
                    path_b64=encoded_path(row["path"]), blob=row["oid"],
                    file_sha256=row["hash"], start_byte=start,
                    end_byte=row["size"] if end is None else end)


def _validate(connection: sqlite3.Connection) -> dict:
    # SQLite's internal prefix contains a literal underscore; GLOB preserves it.
    # LIKE would also exclude caller-created names such as sqliteXextra.
    objects = connection.execute(
        "SELECT name,type,sql FROM sqlite_master "
        "WHERE name NOT GLOB 'sqlite_*'").fetchall()
    expected = set(TABLES) | {"source_fts_data", "source_fts_idx", "source_fts_content",
                              "source_fts_docsize", "source_fts_config"}
    if set(r[0] for r in objects) != expected or any(r[1] != "table" for r in objects):
        raise NavError("index_mismatch", "Unexpected index schema objects.")
    stored_sql = {r[0]: r[2] for r in objects}
    for table, statement in zip(TABLES, DDL):
        if stored_sql[table] != statement:
            raise NavError("index_mismatch", "Index schema differs from the trusted reader.")
    captured.validate_fts(connection)
    for table, columns in TABLES.items():
        if tuple(r[1] for r in connection.execute("PRAGMA table_info(" + table + ")")) != columns:
            raise NavError("index_mismatch", "Unexpected index columns.")
    rows = connection.execute("SELECT data FROM manifest").fetchall()
    if len(rows) != 1:
        raise NavError("index_mismatch", "Missing unique manifest.")
    try:
        manifest = strict_json(rows[0][0].encode("utf-8"))
        if isinstance(manifest, dict) and isinstance(manifest.get("schema"), str) and manifest["schema"] != SCHEMA:
            raise NavError("unsupported_format", "Unsupported index format; select its qualified reader explicitly.")
        required = {"schema", "complete", "build_id", "semantic_request", "request_sha256",
                    "snapshot", "recipe_sha256", "build_input_sha256", "coverage",
                    "report_count", "builder", "contracts"}
        if (set(manifest) != required or manifest["schema"] != SCHEMA
                or manifest["complete"] is not True
                or digest(manifest["semantic_request"]) != manifest["request_sha256"]
                or coverage(connection, manifest["semantic_request"]["recipe"]) != manifest["coverage"]
                or connection.execute("SELECT count(*) FROM reports").fetchone()[0] != manifest["report_count"]):
            raise ValueError("invalid manifest")
        request = parse_request("build", canonical({**manifest["semantic_request"],
                                                     "build_id": manifest["build_id"]}))
        if request["format"]["reader"] != INTERPRETATION:
            raise ValueError("unsupported captured interpretation")
        if semantic(request) != manifest["semantic_request"]:
            raise ValueError("noncanonical stored request")
        snapshot = record(manifest["snapshot"],
                          {"corpus_id", "object_format", "commit", "tree", "corpus_path"},
                          {"corpus_id", "object_format", "commit", "tree", "corpus_path"})
        if (snapshot["corpus_id"] != request["corpus_id"]
                or snapshot["corpus_path"] != request["corpus_path"]
                or snapshot["object_format"] not in ("sha1", "sha256")):
            raise ValueError("snapshot mismatch")
        size = 40 if snapshot["object_format"] == "sha1" else 64
        if any(len(oid(snapshot[k])) != size for k in ("commit", "tree")):
            raise ValueError("object format mismatch")
        for key in ("recipe_sha256", "build_input_sha256"):
            hashed(manifest[key])
        builder = record(manifest["builder"], {"python", "reader_recipe_sha256"},
                         {"python", "reader_recipe_sha256"})
        text(builder["python"])
        hashed(builder["reader_recipe_sha256"])
        if manifest["recipe_sha256"] != digest(dict(
                recipe=request["recipe"], settings=request["settings"],
                format=request["format"], reader=builder["reader_recipe_sha256"])):
            raise ValueError("stored recipe mismatch")
        integer(manifest["report_count"], 0, 2**63 - 1)
        packages = {r[0] for r in connection.execute("SELECT package FROM reports")}
        source_ids = []
        for row in connection.execute("SELECT * FROM sources"):
            raw_path(encoded_path(row["path"]))
            if (len(oid(row["oid"])) != size or row["kind"] not in ("blob", "commit")
                    or row["mode"] not in ("100644", "100755", "120000", "160000")
                    or row["role"] not in ("metadata", "prose", "contract", "support")
                    or (row["kind"] == "commit") != (row["mode"] == "160000")):
                raise ValueError("invalid source facts")
            if row["kind"] == "blob":
                integer(row["size"], 0, 2**63 - 1)
            elif row["size"] is not None:
                raise ValueError("commit entry has a size")
            parts = row["path"].split(b"/")
            package = parts[1].decode("ascii") if len(parts) > 2 and parts[0] == b"reports" else None
            if row["package"] != package:
                raise ValueError("source package relationship mismatch")
            if package is not None and package not in packages:
                raise ValueError("source has no owning report")
            expected_role = ("contract" if row["path"] in CONTRACT_FILES
                             else "metadata" if package is not None and parts[2:] == [b"REPORT.json"]
                             else "prose" if package is not None and parts[2:] == [b"REPORT.md"]
                             else "support")
            if row["role"] != expected_role or (expected_role != "support" and row["data"] is None):
                raise ValueError("source role/capture mismatch")
            source_ids.append(dict(path_b64=encoded_path(row["path"]), mode=row["mode"],
                                   kind=row["kind"], oid=row["oid"]))
            if row["data"] is not None:
                if sha(row["data"]) != row["hash"] or len(row["data"]) != row["size"]:
                    raise ValueError("invalid captured bytes")
                if (row["kind"] != "blob" or row["mode"] not in ("100644", "100755")
                        or row["reason"] is not None
                        or row["package"] is None and row["role"] != "contract"):
                    raise ValueError("invalid captured source state")
                # A source handle's Git blob identity names these exact bytes.
                blob_hash = hashlib.new(snapshot["object_format"])
                blob_hash.update(f"blob {len(row['data'])}\0".encode("ascii"))
                blob_hash.update(row["data"])
                if blob_hash.hexdigest() != row["oid"]:
                    raise ValueError("captured Git blob identity mismatch")
                row["data"].decode("utf-8")
            elif row["hash"] is not None or not row["reason"]:
                raise ValueError("invalid manifest-only source state")
        source_ids.sort(key=lambda item: raw_path(item["path_b64"]))
        if digest(dict(snapshot=snapshot, sources=source_ids,
                       recipe=manifest["recipe_sha256"])) != manifest["build_input_sha256"]:
            raise ValueError("build input mismatch")
        contracts = {r["path"].decode("ascii"): r["hash"] for r in connection.execute(
            "SELECT path,hash FROM sources WHERE role='contract'")}
        if (set(contracts) != set(CONTRACT_PATHS)
                or contracts != manifest["contracts"]
                or contracts != request["format"]["resources"]):
            raise ValueError("contract capture mismatch")
        policy_bytes = connection.execute(
            "SELECT data FROM sources WHERE path=?", (b"CORPUS.json",)).fetchone()[0]
        policy = reference_format.policy(policy_bytes)
        expected_subjects, expected_coordinates, expected_topics = [], [], []
        for report in connection.execute("SELECT * FROM reports"):
            package = report["package"]
            if not reference_format.reference.PACKAGE_RE.fullmatch(package):
                raise ValueError("invalid package")
            base = b"reports/" + package.encode("ascii") + b"/"
            sources = {r["path"]: r for r in connection.execute(
                "SELECT * FROM sources WHERE path IN (?,?)",
                (base + b"REPORT.json", base + b"REPORT.md"))}
            meta = reference_format.metadata(sources[base + b"REPORT.json"]["data"],
                                             base + b"REPORT.json", policy)
            title, sections, _ = reference_format.prose(sources[base + b"REPORT.md"]["data"],
                                                        base + b"REPORT.md")
            if canonical(meta).decode("ascii") != report["metadata"] or title != report["title"]:
                raise ValueError("report relationship mismatch")
            actual = [tuple(r) for r in connection.execute(
                "SELECT ordinal,name,path,start,end FROM sections WHERE package=? ORDER BY ordinal", (package,))]
            wanted = [(i, s.name, base + b"REPORT.md", s.start, s.end)
                      for i, s in enumerate(sections)]
            if actual != wanted:
                raise ValueError("section relationship mismatch")
            expected_topics.extend((package, topic) for topic in meta["topics"])
            for ordinal, subject in enumerate(meta["subjects"]):
                expected_subjects.append((package, ordinal, subject["name"]))
                expected_coordinates.extend((package, ordinal, k, v)
                                            for k, v in subject["identity"].items())
        for table, expected_rows in (("topics", expected_topics),
                                     ("subjects", expected_subjects),
                                     ("coordinates", expected_coordinates)):
            if sorted(tuple(r) for r in connection.execute("SELECT * FROM " + table)) != sorted(expected_rows):
                raise ValueError("metadata relationship mismatch")
        if (connection.execute("SELECT count(*) FROM sections").fetchone()[0] != len(packages) * 6
                or connection.execute("SELECT count(*) FROM routes").fetchone()[0] != 0):
            raise ValueError("unexpected section/route coverage")
        searchable = {r[0]: r[1] for r in connection.execute(
            "SELECT path,length(data) FROM sources WHERE package IS NOT NULL AND data IS NOT NULL AND role IN ('prose','support')")}
        covered = dict.fromkeys(searchable, 0)
        # Locally valid slices are insufficient: a missing slice would silently
        # remove evidence from a complete index. Sort only interval facts, not
        # the source BLOB repeated by the detailed relationship check below.
        for path, start, end in connection.execute(
                "SELECT path,start,end FROM units ORDER BY path,start,end,id"):
            if (path not in covered or start != covered[path]
                    or not start < end <= searchable[path]):
                raise ValueError("search units have a gap or overlap")
            covered[path] = end
        if covered != searchable:
            raise ValueError("search units do not cover captured source")
        units = connection.execute("SELECT u.*,s.data,s.package AS source_package,s.role,f.text FROM units u LEFT JOIN sources s ON s.path=u.path LEFT JOIN source_fts f ON f.rowid=u.id")
        count = 0
        for row in units:
            if row["data"] is None or not 0 <= row["start"] < row["end"] <= len(row["data"]):
                raise ValueError("invalid unit range")
            if (row["package"] not in packages or row["package"] != row["source_package"]
                    or row["role"] not in ("prose", "support")
                    or row["fragment"] not in (0, 1)
                    or not reference_format.boundary(row["data"], row["start"])):
                raise ValueError("invalid unit relation")
            if row["data"][row["start"]:row["end"]].decode("utf-8") != row["text"]:
                raise ValueError("unit text mismatch")
            count += 1
        if connection.execute("SELECT count(*) FROM source_fts").fetchone()[0] != count:
            raise ValueError("unrelated search rows")
        return manifest
    except NavError as exc:
        if exc.code == "unsupported_format":
            raise
        raise NavError("index_mismatch", "Invalid complete index manifest or relations.") from exc
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise NavError("index_mismatch", "Invalid complete index manifest or relations.") from exc


@contextmanager
def open_image(index: dict, image: bytes):
    with captured.open_image(index, image, _validate) as (connection, manifest):
        yield Generation(index, connection, manifest)


@contextmanager
def open_generation(index: dict):
    # SQLite consumes this captured image, not another resolution of its path.
    with open_image(index, captured.read_image(index)) as generation:
        yield generation


def _capture(request: dict, snapshot: dict, entries: list[git_source.Entry], connection):
    by_path = {e.path: e for e in entries}
    # Navigation selects governing context and reports. The native publication
    # validator separately owns the complete authoring candidate's root shape.
    required_files = list(CONTRACT_FILES)
    packages = []
    if b"reports" in by_path:
        if by_path[b"reports"].kind != "tree":
            raise NavError("unsupported_structure", "reports must be an ordinary tree.")
        for entry in entries:
            parts = entry.path.split(b"/")
            if len(parts) == 2 and parts[0] == b"reports":
                try:
                    name = parts[1].decode("ascii")
                except UnicodeError as exc:
                    raise NavError("invalid_report", "Invalid package name.") from exc
                if entry.kind != "tree" or not reference_format.reference.PACKAGE_RE.fullmatch(name):
                    raise NavError("invalid_report", "Invalid package tree/name.")
                packages.append(name)
                required_files.extend([entry.path + b"/REPORT.json", entry.path + b"/REPORT.md"])
    required = set(required_files)
    captured = {}
    total = 0
    for path in required_files:
        entry = by_path.get(path)
        if entry is None or entry.kind != "blob" or entry.mode not in ("100644", "100755"):
            raise NavError("unsupported_structure", "Required regular source missing.")
        maximum = (request["settings"]["metadata_bytes"] if path.endswith(b"REPORT.json")
                   else request["settings"]["report_bytes"])
        if entry.size > maximum:
            raise NavError("invalid_report", "Required source exceeds selected limit.")
        data = git_source.blob(request["repository"], entry)
        reference_format.utf8(data)
        total += len(data)
        if total > request["settings"]["capture_bytes"]:
            raise NavError("invalid_report", "Required capture exceeds selected limit.")
        captured[path] = data
    for path in CONTRACT_PATHS:
        if sha(captured[path.encode("ascii")]) != request["format"]["resources"][path]:
            raise NavError("unsupported_format", "Pinned interpretation resource hash differs.")
    policy = reference_format.policy(captured[b"CORPUS.json"])
    for entry in entries:
        if entry.kind == "tree":
            continue
        parts = entry.path.split(b"/")
        package = parts[1].decode("ascii") if len(parts) > 2 and parts[0] == b"reports" else None
        role = ("metadata" if entry.path in required and entry.path.endswith(b"REPORT.json")
                else "prose" if entry.path in required and entry.path.endswith(b"REPORT.md")
                else "contract" if entry.path in CONTRACT_FILES
                else "support")
        data = captured.get(entry.path)
        reason = "inventory_only"
        support = request["settings"]["support"]
        if data is None and support["mode"] == "utf8" and package is not None:
            if entry.mode not in ("100644", "100755"):
                reason = "not_regular"
            elif entry.size > support["max_file_bytes"]:
                reason = "file_limit"
            elif total + entry.size > request["settings"]["capture_bytes"]:
                reason = "capture_limit"
            else:
                candidate = git_source.blob(request["repository"], entry)
                try:
                    candidate.decode("utf-8")
                    data = candidate
                    total += len(data)
                except UnicodeError:
                    reason = "not_utf8"
        connection.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (entry.path, package, entry.mode, entry.kind, entry.oid,
                            entry.size, role, None if data is None else sha(data),
                            data, reason if data is None else None))
    for package in sorted(packages):
        base = b"reports/" + package.encode("ascii") + b"/"
        meta = reference_format.metadata(captured[base + b"REPORT.json"], base + b"REPORT.json", policy)
        data = captured[base + b"REPORT.md"]
        title, sections, blocks = reference_format.prose(data, base + b"REPORT.md")
        connection.execute("INSERT INTO reports VALUES(?,?,?)", (package, title, canonical(meta).decode("ascii")))
        for ordinal, subject in enumerate(meta["subjects"]):
            connection.execute("INSERT INTO subjects VALUES(?,?,?)", (package, ordinal, subject["name"]))
            for key, value in subject["identity"].items():
                connection.execute("INSERT INTO coordinates VALUES(?,?,?,?)", (package, ordinal, key, value))
        connection.executemany("INSERT INTO topics VALUES(?,?)", [(package, t) for t in meta["topics"]])
        for ordinal, section in enumerate(sections):
            connection.execute("INSERT INTO sections VALUES(?,?,?,?,?,?)",
                               (package, ordinal, section.name, base + b"REPORT.md", section.start, section.end))
    for row in connection.execute("SELECT * FROM sources WHERE package IS NOT NULL AND data IS NOT NULL AND role IN ('prose','support')").fetchall():
        if row["role"] == "prose":
            _, _, blocks = reference_format.prose(row["data"], row["path"])
        else:
            blocks = [(0, len(row["data"]))]
        for start, end, fragment in reference_format.units(row["data"], blocks, request["settings"]["unit_bytes"]):
            if start == end:
                continue
            cur = connection.execute("INSERT INTO units(package,path,start,end,fragment) VALUES(?,?,?,?,?)",
                                     (row["package"], row["path"], start, end, int(fragment)))
            connection.execute("INSERT INTO source_fts(rowid,text) VALUES(?,?)", (cur.lastrowid, row["data"][start:end].decode("utf-8")))


def _result(request: dict, generation: Generation, residue: list[str]) -> dict:
    m = generation.manifest
    result = dict(build_id=request["build_id"], context=generation.context(),
                  build_input_sha256=m["build_input_sha256"],
                  report_count=m["report_count"], residue=residue)
    if not fits("build", result, request["max_bytes"]):
        raise NavError("budget_too_small")
    return result


def _preflight(request: dict, reservation: Path, staging: Path) -> None:
    if request["format"]["reader"] != INTERPRETATION:
        raise NavError("unsupported_format", "Unsupported selected reader.")
    if request["card_selections"]:
        raise NavError("unsupported_capability", "Card admission is not implemented in this source-only preview.")
    n = 2**63 - 1
    fake = dict(index=dict(path=str(reservation / ("f" * 64 + ".sqlite")), sha256="f" * 64),
                format=request["format"],
                snapshot=dict(corpus_id=request["corpus_id"], object_format="sha256", commit="f" * 64,
                              tree="f" * 64, corpus_path=request["corpus_path"]),
                recipe_sha256="f" * 64, reader_recipe_sha256="f" * 64,
                coverage=dict(captured_files=n, manifest_only_files=n,
                              hints=dict(kind="disabled" if request["recipe"] == "source-only/1" else "none_selected")))
    result = dict(build_id=request["build_id"], context=fake, build_input_sha256="f" * 64,
                  report_count=n, residue=[str(staging)])
    if not fits("build", result, request["max_bytes"]):
        raise NavError("budget_too_small", "Build success cannot fit before reservation.")


def _make_image(request: dict) -> bytes:
    snapshot, entries = git_source.snapshot(request)
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.enable_load_extension(False)
    connection.execute("PRAGMA temp_store=MEMORY")
    try:
        for statement in DDL:
            connection.execute(statement)
        _capture(request, snapshot, entries, connection)
        source_ids = [dict(path_b64=encoded_path(e.path), mode=e.mode, kind=e.kind, oid=e.oid)
                      for e in entries if e.kind != "tree"]
        source_ids.sort(key=lambda item: raw_path(item["path_b64"]))
        reader = reader_identity()
        recipe = recipe_identity(request, reader)
        manifest = dict(schema=SCHEMA, complete=True, build_id=request["build_id"],
                        semantic_request=semantic(request), request_sha256=digest(semantic(request)),
                        snapshot=snapshot, recipe_sha256=recipe,
                        build_input_sha256=digest(dict(snapshot=snapshot, sources=source_ids,
                                                       recipe=recipe)),
                        coverage=coverage(connection, request["recipe"]),
                        report_count=connection.execute("SELECT count(*) FROM reports").fetchone()[0],
                        builder=dict(python=sys.version, reader_recipe_sha256=reader),
                        contracts={r["path"].decode("ascii"): r["hash"] for r in connection.execute(
                            "SELECT path,hash FROM sources WHERE role='contract'")})
        connection.execute("INSERT INTO manifest VALUES(?)", (canonical(manifest).decode("ascii"),))
        _validate(connection)
        connection.commit()
        return connection.serialize()
    finally:
        connection.close()


def build(request: dict) -> dict:
    return publishing.build(request, namespaces=("indexes", "builds"),
                            make_image=_make_image, open_image=open_image,
                            project_result=_result, preflight=_preflight)
