"""Bounded native listings and original-byte range reads."""

from __future__ import annotations

import base64
import binascii
import sqlite3

from corpus_nav.retrieval import _has_tokens
from corpus_nav.paging import paginate_items
from . import rircon
from .wire import (
    NavError,
    canonical,
    digest,
    encoded_path,
    fits,
    integer,
    raw_path,
    record,
    semantic,
    strict_json,
)


def _operation(request):
    return request["schema"][len("corpus-docs-") : -2]


def _base(generation, request):
    return dict(
        context=generation.context(), effective_request=semantic(request)
    )


def _cursor(generation, request, position):
    data = dict(
        schema="corpus-docs-cursor/1",
        operation=_operation(request),
        index_sha256=generation.index["sha256"],
        reader_recipe_sha256=generation.reader_recipe_sha256,
        request_sha256=digest(semantic(request)),
        next=position,
    )
    return base64.b64encode(canonical(data)).decode("ascii")


def _position(generation, request, kind):
    if "continuation" not in request:
        return None
    try:
        data = base64.b64decode(request["continuation"], validate=True)
        if base64.b64encode(data).decode("ascii") != request["continuation"]:
            raise ValueError("noncanonical cursor encoding")
        value = strict_json(data)
        keys = {
            "schema",
            "operation",
            "index_sha256",
            "reader_recipe_sha256",
            "request_sha256",
            "next",
        }
        record(value, keys, keys)
        if (
            canonical(value) != data
            or value["schema"] != "corpus-docs-cursor/1"
            or value["operation"] != _operation(request)
            or value["index_sha256"] != generation.index["sha256"]
            or value["reader_recipe_sha256"] != generation.reader_recipe_sha256
            or value["request_sha256"] != digest(semantic(request))
        ):
            raise ValueError("cursor binding mismatch")
        fields = (
            {"kind", "offset"} if kind == "items" else {"kind", "byte_offset"}
        )
        position = record(value["next"], fields, fields)
        if position["kind"] != kind:
            raise ValueError("cursor position kind mismatch")
        integer(
            position["offset" if kind == "items" else "byte_offset"],
            0,
            2**63 - 1,
        )
        return position
    except (ValueError, KeyError, TypeError, binascii.Error, NavError) as error:
        raise NavError(
            "cursor_mismatch", "Cursor does not bind this native request/view."
        ) from error


def page_items(generation, request, items, partial=False):
    position = _position(generation, request, "items")
    offset = position["offset"] if position is not None else 0
    if position is not None and (partial or not 0 < offset < len(items)):
        raise NavError(
            "cursor_mismatch", "Cursor is outside this complete item sequence."
        )
    base = _base(generation, request)
    operation = _operation(request)

    def continuation_for(next_index):
        return _cursor(
            generation, request, dict(kind="items", offset=next_index)
        )

    def fit_page(selected, page):
        result = {**base, "items": selected, "page": page}
        return result if fits(operation, result, request["max_bytes"]) else None

    return paginate_items(
        items,
        offset=offset,
        limit=request["limit"],
        partial=partial,
        max_bytes=request["max_bytes"],
        continuation_for=continuation_for,
        fit_page=fit_page,
    )


def list_items(generation, request):
    connection = generation.connection
    selection = request["items"]
    items = []
    if selection == "documents":
        sql = "SELECT d.*,i.mode,i.kind AS object_kind,i.oid,i.size,s.hash,s.data FROM documents d JOIN inventory i USING(path) JOIN sources s USING(path)"
        clauses, params = [], []
        for field, column in (
            ("document", "d.path"),
            ("container", "d.container"),
        ):
            if field in request:
                clauses.append(column + "=?")
                params.append(raw_path(request[field]))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        for row in connection.execute(sql + " ORDER BY d.path", params):
            context = [
                encoded_path(r[0])
                for r in connection.execute(
                    "SELECT source FROM membership WHERE document=? AND role='context' ORDER BY source",
                    (row["path"],),
                )
            ]
            items.append(
                dict(
                    path_b64=encoded_path(row["path"]),
                    container_b64=encoded_path(row["container"]),
                    kind=row["kind"],
                    title=row["title"],
                    context_paths_b64=context,
                    handle=generation.handle(row),
                )
            )
    elif selection == "sources":
        sql = "SELECT i.*,s.hash,s.data FROM inventory i LEFT JOIN sources s USING(path) WHERE i.kind!='tree'"
        params = []
        if "document" in request:
            sql += " AND i.path IN (SELECT source FROM membership WHERE document=?)"
            params.append(raw_path(request["document"]))
        for row in connection.execute(sql + " ORDER BY i.path", params):
            item = dict(
                path_b64=encoded_path(row["path"]),
                mode=row["mode"],
                object_kind=row["kind"],
                oid=row["oid"],
                size=row["size"],
            )
            if row["data"] is None:
                item.update(state="manifest_only", reason="not_native_source")
            else:
                item.update(
                    state="captured",
                    file_sha256=row["hash"],
                    handle=generation.handle(row),
                )
            items.append(item)
    else:
        path = raw_path(request["document"])
        source = connection.execute(
            "SELECT i.*,s.hash,s.data FROM inventory i JOIN sources s USING(path) WHERE i.path=?",
            (path,),
        ).fetchone()
        for heading in connection.execute(
            "SELECT * FROM headings WHERE document=? ORDER BY ordinal", (path,)
        ):
            items.append(
                dict(
                    document_b64=encoded_path(path),
                    ordinal=heading["ordinal"],
                    level=heading["level"],
                    label=heading["label"],
                    handle=generation.handle(
                        source, heading["start"], heading["end"]
                    ),
                )
            )
    return page_items(generation, request, items)


def verify_handle(generation, handle):
    try:
        path = raw_path(handle["path_b64"])
        source = generation.connection.execute(
            "SELECT i.*,s.hash,s.data FROM inventory i LEFT JOIN sources s USING(path) WHERE i.path=?",
            (path,),
        ).fetchone()
        if source is None:
            raise ValueError("unknown source")
        if source["data"] is None:
            raise NavError(
                "source_unavailable",
                "Native source was inventoried without capture.",
            )
        start, end = handle["start_byte"], handle["end_byte"]
        if (
            not 0 <= start <= end <= len(source["data"])
            or handle != generation.handle(source, start, end)
            or not rircon.boundary(source["data"], start)
            or not rircon.boundary(source["data"], end)
        ):
            raise ValueError("source/range identity mismatch")
        return source, start, end
    except (ValueError, TypeError, KeyError, UnicodeError) as error:
        raise NavError(
            "invalid_handle",
            "Handle does not identify this captured original range.",
        ) from error


def read(generation, request):
    source, start, end = verify_handle(generation, request["handle"])
    position = _position(generation, request, "read")
    offset = start if position is None else position["byte_offset"]
    data = source["data"]
    if position is not None and (
        not start <= offset < end or not rircon.boundary(data, offset)
    ):
        raise NavError(
            "cursor_mismatch",
            "Read position is outside the selected original range.",
        )
    base = _base(generation, request)

    def trial(stop):
        segment = dict(
            handle=generation.handle(source, offset, stop),
            text=data[offset:stop].decode("utf-8"),
            fragment=offset != start or stop != end,
        )
        page = (
            dict(
                kind="more",
                reason="output_budget",
                continuation=_cursor(
                    generation, request, dict(kind="read", byte_offset=stop)
                ),
            )
            if stop < end
            else dict(kind="complete")
        )
        return {**base, "segments": [segment], "page": page}

    cap = request["max_bytes"]
    if end - offset <= cap:
        result = trial(end)
        if fits("read", result, cap):
            return result
    upper = min(end, offset + cap)
    while not rircon.boundary(data, upper):
        upper -= 1
    boundaries = []
    cursor = offset
    for character in data[offset:upper].decode("utf-8"):
        cursor += len(character.encode("utf-8"))
        boundaries.append(cursor)
    low, high, best = 0, len(boundaries) - 1, None
    while low <= high:
        middle = (low + high) // 2
        candidate = trial(boundaries[middle])
        if fits("read", candidate, cap):
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    if best is None:
        raise NavError(
            "budget_too_small", "No useful native source scalar fits."
        )
    return best


def _query(request, settings):
    if "query" not in request:
        return None
    query = request["query"]
    terms = sorted(set(query.split()))
    if (
        not terms
        or len(query.encode("utf-8")) > settings["query_bytes"]
        or len(terms) > settings["query_terms"]
    ):
        raise NavError(
            "invalid_query", "Native query is empty or exceeds selected limits."
        )
    request["query"] = " ".join(terms)
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)


def eligible_documents(generation, request):
    """Apply exact native and literal eligibility before match/result limits."""
    sql = (
        "SELECT d.*, s.data FROM documents d " "JOIN sources s ON s.path=d.path"
    )
    clauses, params = [], []
    for field, column in (("document", "d.path"), ("container", "d.container")):
        if field in request:
            clauses.append(column + "=?")
            params.append(raw_path(request[field]))
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    literals = [value.encode("utf-8") for value in request["literals_all"]]
    # Captured data and literal encodings are valid UTF-8. Exact byte substring
    # matches therefore preserve scalar substring meaning without decoding a
    # complete source copy for every literal. These scans are not SQLite steps.
    return {
        row["path"]: row
        for row in generation.connection.execute(
            sql + " ORDER BY d.path", params
        )
        if all(literal in row["data"] for literal in literals)
    }


def search(generation, request):
    settings = generation.manifest["semantic_request"]["settings"]
    expression = _query(request, settings)
    connection = generation.connection
    steps = 0
    bound = request["bounds"]["sqlite_steps"]

    def progress():
        nonlocal steps
        steps += 1
        return steps >= bound

    # Count this query's SQLite progress callbacks across eligibility, tokenizer
    # recognition and ranking. The budget does not purport to cap Python heap,
    # original-byte literal scans or the work of opening/validating the image.
    connection.set_progress_handler(progress, 1)
    try:
        if expression is not None and not _has_tokens(
            request["query"], progress
        ):
            raise NavError(
                "invalid_query", "Query has no SQLite-tokenizer term."
            )
        eligible = eligible_documents(generation, request)
        selected = {}
        partial = False
        if expression is None:
            # This is document inventory, not a source-match ranking. Empty
            # documents remain visible and consume no invented match units.
            for path, document in eligible.items():
                unit = connection.execute(
                    "SELECT * FROM units WHERE document=? ORDER BY start,id LIMIT 1",
                    (path,),
                ).fetchone()
                # Empty native documents remain valid and inventory-visible.
                # Their whole-source empty interval needs no fabricated unit.
                selected[path] = (unit, None)
        else:
            unit_limit = request["bounds"]["unit_matches"]
            sql = (
                "SELECT u.*,bm25(source_fts) AS score FROM source_fts "
                "JOIN units u ON u.id=source_fts.rowid "
                "WHERE source_fts MATCH ? ORDER BY score,u.document,u.id"
            )
            count = 0
            for unit in connection.execute(sql, (expression,)):
                path = unit["document"]
                if path not in eligible:
                    continue
                # One overflow observation distinguishes an exact complete
                # boundary from truncation. It consumes SQLite work, but is
                # neither admitted nor included in the reported ranking.
                if count == unit_limit:
                    partial = True
                    break
                count += 1
                if path not in selected:
                    selected[path] = (unit, unit["score"])
        items = []
        for rank, (path, (unit, score)) in enumerate(selected.items(), 1):
            document = eligible[path]
            source = connection.execute(
                "SELECT i.*,s.hash,s.data FROM inventory i "
                "JOIN sources s USING(path) WHERE i.path=?",
                (path,),
            ).fetchone()
            handle = (
                generation.handle(source, unit["start"], unit["end"])
                if unit is not None
                else generation.handle(source)
            )
            items.append(
                dict(
                    path_b64=encoded_path(path),
                    container_b64=encoded_path(document["container"]),
                    kind=document["kind"],
                    title=document["title"],
                    rank=rank if expression is not None else None,
                    score=(
                        dict(kind="bm25", value=score)
                        if score is not None
                        else None
                    ),
                    handles=[handle],
                )
            )
    except sqlite3.OperationalError as error:
        if steps >= bound or "interrupt" in str(error).lower():
            raise NavError(
                "work_exhausted", "Native SQLite query budget exhausted."
            ) from error
        raise NavError(
            "invalid_query", "SQLite could not execute the native quoted query."
        ) from error
    finally:
        connection.set_progress_handler(None, 0)
    return page_items(generation, request, items, partial=partial)
