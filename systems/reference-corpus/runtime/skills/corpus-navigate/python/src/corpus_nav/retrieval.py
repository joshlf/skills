"""Eligibility, report ranking and byte-preserving paginated reads."""

from __future__ import annotations

import base64
import binascii
import json
import sqlite3

from .generation import Generation
from .paging import paginate_items
from .reference_format import boundary
from .response import (NavError, SECTIONS, canonical, digest, encoded_path, fits,
                       raw_path, record, semantic, strict_json)


def _operation(request: dict) -> str:
    return request["schema"][len("corpus-nav-"):-2]


def _effective(request: dict) -> dict:
    return semantic(request)


def _base(g: Generation, request: dict) -> dict:
    return dict(context=g.context(), effective_request=_effective(request))


def _cursor(g: Generation, request: dict, next_value: dict) -> str:
    value = dict(schema="corpus-nav-cursor/1", operation=_operation(request),
                 index_sha256=g.index["sha256"],
                 request_sha256=digest(_effective(request)),
                 reader_recipe_sha256=g.reader_recipe_sha256, next=next_value)
    return base64.b64encode(canonical(value)).decode("ascii")


def _position(g: Generation, request: dict, kind: str) -> dict | None:
    if "continuation" not in request:
        return None
    try:
        data = base64.b64decode(request["continuation"], validate=True)
        if base64.b64encode(data).decode("ascii") != request["continuation"]:
            raise ValueError("noncanonical cursor encoding")
        value = strict_json(data)
        if canonical(value) != data:
            raise ValueError("noncanonical cursor JSON")
        record(value, {"schema", "operation", "index_sha256", "request_sha256",
                       "reader_recipe_sha256", "next"},
               {"schema", "operation", "index_sha256", "request_sha256",
                "reader_recipe_sha256", "next"})
        if (value["schema"] != "corpus-nav-cursor/1"
                or value["operation"] != _operation(request)
                or value["index_sha256"] != g.index["sha256"]
                or value["request_sha256"] != digest(_effective(request))
                or value["reader_recipe_sha256"] != g.reader_recipe_sha256
                or not isinstance(value["next"], dict)
                or value["next"].get("kind") != kind):
            raise ValueError("cursor binding mismatch")
        fields = {"report": {"kind", "package"}, "source": {"kind", "path_b64"},
                  "rank": {"kind", "ordinal"},
                  "admission": {"kind", "package", "recipe_sha256", "requested_card_sha256"},
                  "read": {"kind", "section_ordinal", "byte_offset"}}[kind]
        record(value["next"], fields, fields)
        return value["next"]
    except (ValueError, KeyError, TypeError, binascii.Error, NavError) as exc:
        raise NavError("cursor_mismatch", "Cursor does not bind this request/reader.") from exc


def metadata_matches(metadata: dict, filters: dict) -> bool:
    topics = filters["topics_any"]
    return ((not topics or any(t in metadata["topics"] for t in topics))
            and all(any(all(subject["identity"].get(k) == v
                            for k, v in selector.items())
                        for subject in metadata["subjects"])
                    for selector in filters["subjects_all"]))


def eligible_reports(g: Generation, filters: dict) -> list[sqlite3.Row]:
    # Closed requests can contain more coordinates than SQLite accepts in one
    # expression. Exact eligibility therefore precedes the fixed SQL ranking
    # query, without adding an undocumented filter-array limit.
    result = []
    for row in g.connection.execute("SELECT * FROM reports ORDER BY package"):
        if not metadata_matches(json.loads(row["metadata"]), filters):
            continue
        if filters["literals_all"]:
            # Validated source paths bind ownership to this package prefix.
            # Its BLOB primary key avoids scanning the whole inventory per
            # report. Slash (0x2f) precedes '0' (0x30), so these bounds include
            # every raw child suffix and exclude similarly named packages.
            base = b"reports/" + row["package"].encode("ascii")
            sources = [r[0].decode("utf-8") for r in g.connection.execute(
                "SELECT data FROM sources WHERE path>=? AND path<? AND role IN ('prose','support') AND data IS NOT NULL",
                (base + b"/", base + b"0"))]
            if not all(any(literal in source for source in sources)
                       for literal in filters["literals_all"]):
                continue
        result.append(row)
    return result


def _key(item: dict, kind: str) -> dict:
    if kind == "report":
        return dict(kind=kind, package=item["package"])
    if kind == "source":
        return dict(kind=kind, path_b64=item["path_b64"])
    return dict(kind=kind, package=item["package"],
                recipe_sha256=item["recipe_sha256"],
                requested_card_sha256=item["requested_card_sha256"])


def _page_items(g: Generation, request: dict, items: list[dict],
                kind: str, offset: int = 0, partial: bool = False) -> dict:
    base = _base(g, request)
    operation = _operation(request)
    cap = request["max_bytes"]

    def continuation_for(next_index: int) -> str:
        position = (dict(kind="rank", ordinal=next_index) if kind == "rank"
                    else _key(items[next_index - 1], kind))
        return _cursor(g, request, position)

    def fit_page(proposed: list[dict], page: dict) -> dict | None:
        result = {**base, "items": proposed, "page": page}
        return result if fits(operation, result, cap) else None

    return paginate_items(
        items, offset=offset, limit=request["limit"], partial=partial,
        max_bytes=cap, continuation_for=continuation_for, fit_page=fit_page)


def list_items(g: Generation, request: dict) -> dict:
    selection = request["items"]
    kind = {"reports": "report", "sources": "source", "admissions": "admission"}[selection]
    position = _position(g, request, kind)
    connection = g.connection
    if selection == "reports":
        rows = eligible_reports(g, request["filters"])
        items = [dict(package=r["package"], title=r["title"], metadata=json.loads(r["metadata"])) for r in rows]
        keys = [i["package"] for i in items]
        key = position["package"] if position else None
    elif selection == "sources":
        sql = "SELECT path,package,mode,kind,oid,size,role,hash,data IS NOT NULL AS captured,reason FROM sources"
        params = []
        if "package" in request:
            sql += " WHERE package=?"
            params.append(request["package"])
        items = []
        for row in connection.execute(sql + " ORDER BY path", params):
            item = dict(path_b64=encoded_path(row["path"]), package=row["package"],
                        mode=row["mode"], object_kind=row["kind"], oid=row["oid"],
                        size=row["size"], role=row["role"])
            if not row["captured"]:
                item.update(state="manifest_only", reason=row["reason"])
            else:
                item.update(state="captured", file_sha256=row["hash"], handle=g.handle(row))
            items.append(item)
        keys = [raw_path(i["path_b64"]) for i in items]
        try:
            key = raw_path(position["path_b64"]) if position else None
        except NavError as exc:
            raise NavError("cursor_mismatch") from exc
    else:
        items, keys, key = [], [], None
    if position is not None:
        if key not in keys:
            raise NavError("cursor_mismatch", "Cursor ordering key is absent.")
        items = items[keys.index(key) + 1:]
    return _page_items(g, request, items, kind)


def _verify_handle(g: Generation, handle: dict) -> tuple[sqlite3.Row, int, int]:
    try:
        path = raw_path(handle["path_b64"])
        row = g.connection.execute("SELECT * FROM sources WHERE path=?", (path,)).fetchone()
        if row is None:
            raise ValueError("unknown source")
        known = g.handle(row, 0, 0)
        identity_fields = ("index_sha256", "corpus_id", "commit", "package", "path_b64", "blob")
        if any(handle[k] != known[k] for k in identity_fields):
            raise ValueError("source identity mismatch")
        if row["data"] is None:
            raise NavError("source_unavailable", "Source was inventoried without capture.")
        start, end = handle["start_byte"], handle["end_byte"]
        if (not 0 <= start <= end <= row["size"]
                or handle != g.handle(row, start, end)):
            raise ValueError("handle identity mismatch")
        if not boundary(row["data"], start):
            raise ValueError("range splits a Unicode scalar")
        row["data"][start:end].decode("utf-8")
        return row, start, end
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise NavError("invalid_handle", "Handle does not identify this captured range.") from exc


def read(g: Generation, request: dict) -> dict:
    selection = request["select"]
    other = []
    ranges = []
    if selection["kind"] == "handle":
        ranges = [_verify_handle(g, selection["handle"])]
    else:
        rows = g.connection.execute("SELECT * FROM sections WHERE package=? ORDER BY ordinal",
                                    (selection["package"],)).fetchall()
        if not rows:
            raise NavError("source_unavailable", "No captured report package.")
        for section in rows:
            row = g.connection.execute("SELECT * FROM sources WHERE path=?", (section["path"],)).fetchone()
            if section["name"] in selection["sections"]:
                ranges.append((row, section["start"], section["end"]))
            else:
                other.append(dict(section=section["name"], handle=g.handle(row, section["start"], section["end"])))
    position = _position(g, request, "read")
    ordinal, offset = 0, ranges[0][1]
    if position:
        ordinal, offset = position["section_ordinal"], position["byte_offset"]
        if (type(ordinal) is not int or not 0 <= ordinal < len(ranges)
                or type(offset) is not int or not ranges[ordinal][1] <= offset < ranges[ordinal][2]):
            raise NavError("cursor_mismatch", "Read position is outside selected ranges.")
        if not boundary(ranges[ordinal][0]["data"], offset):
            raise NavError("cursor_mismatch", "Read position splits Unicode scalar.")
    result = {**_base(g, request), "segments": [], "other_sections": other,
              "page": dict(kind="complete")}
    cap = request["max_bytes"]
    while ordinal < len(ranges):
        row, start, end = ranges[ordinal]
        data = row["data"]

        def trial(stop):
            segment = dict(handle=g.handle(row, offset, stop),
                           text=data[offset:stop].decode("utf-8"),
                           fragment=offset != start or stop != end)
            if stop < end:
                next_value = dict(kind="read", section_ordinal=ordinal, byte_offset=stop)
            elif ordinal + 1 < len(ranges):
                next_value = dict(kind="read", section_ordinal=ordinal + 1, byte_offset=ranges[ordinal + 1][1])
            else:
                next_value = None
            page = (dict(kind="more", reason="output_budget", continuation=_cursor(g, request, next_value))
                    if next_value is not None else dict(kind="complete"))
            return {**result, "segments": result["segments"] + [segment], "page": page}

        complete = trial(end) if end - offset <= cap else None
        if complete is not None and fits("read", complete, cap):
            result = complete
            ordinal += 1
            if ordinal < len(ranges):
                offset = ranges[ordinal][1]
            continue
        # Search scalar positions, counting JSON escaping, handles and cursors.
        boundaries = [offset]
        cursor = offset
        upper = min(end, offset + cap)
        while not boundary(data, upper):
            upper -= 1
        for char in data[offset:upper].decode("utf-8"):
            cursor += len(char.encode("utf-8"))
            boundaries.append(cursor)
        lo, hi = 1, len(boundaries) - 1
        best = None
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = trial(boundaries[mid])
            if fits("read", candidate, cap):
                best = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        if best is not None:
            return best
        if result["segments"] and fits("read", result, cap):
            return result
        raise NavError("budget_too_small", "No useful source segment fits.")
    if not fits("read", result, cap):
        raise NavError("budget_too_small")
    return result


def _query(request: dict, settings: dict) -> str | None:
    if "query" not in request:
        return None
    query = request["query"]
    terms = sorted(set(query.split()))
    if (not terms or len(query.encode("utf-8")) > settings["query_bytes"]
            or len(terms) > settings["query_terms"]):
        raise NavError("invalid_query", "Query is empty, unsearchable or exceeds limits.")
    request["query"] = " ".join(terms)
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)


def _has_tokens(query: str, progress) -> bool:
    # Python's Unicode database and unicode61 need not classify new characters
    # alike. Ask the selected SQLite tokenizer, using only an in-memory index.
    connection = sqlite3.connect(":memory:")
    connection.set_progress_handler(progress, 1)
    try:
        connection.execute("CREATE VIRTUAL TABLE tokens USING fts5(text,tokenize='unicode61')")
        connection.execute("CREATE VIRTUAL TABLE vocabulary USING fts5vocab(tokens,'row')")
        connection.execute("INSERT INTO tokens VALUES(?)", (query,))
        return connection.execute("SELECT 1 FROM vocabulary LIMIT 1").fetchone() is not None
    finally:
        connection.close()


def _targets(metadata: dict, selectors: list[dict]) -> list[dict]:
    result = []
    for selector in selectors:
        ordinals = [i for i, s in enumerate(metadata["subjects"])
                    if all(s["identity"].get(k) == v for k, v in selector.items())]
        result.append(dict(selector=selector, state="recorded_match", subject_ordinals=ordinals)
                      if ordinals else dict(selector=selector, state="not_recorded"))
    return result


def search(g: Generation, request: dict) -> dict:
    expression = _query(request, g.manifest["semantic_request"]["settings"])
    kind = "rank" if expression is not None else "report"
    position = _position(g, request, kind)
    connection = g.connection
    bound = request["bounds"]["sqlite_steps"]
    steps = 0

    def progress(amount=1000):
        nonlocal steps
        steps += amount
        return steps >= bound

    connection.set_progress_handler(progress, 1000)
    try:
        if expression is not None and not _has_tokens(request["query"], lambda: progress(1)):
            raise NavError("invalid_query", "Query has no tokenizer-recognized term.")
        eligible = {row["package"]: row
                    for row in eligible_reports(g, request["filters"])}
        reports = {}
        partial = False
        if expression is None:
            for count, row in enumerate(eligible.values(), 1):
                unit = connection.execute("SELECT u.* FROM units u WHERE package=? ORDER BY id LIMIT 1", (row["package"],)).fetchone()
                if unit is None:
                    raise NavError("index_mismatch", "Report lacks original source unit.")
                reports[row["package"]] = (unit, None)
                if count >= request["bounds"]["unit_matches"]:
                    partial = True
                    break
        else:
            # Report facts already have one owner in eligible. Sorting only
            # unit facts avoids copying the report metadata into every match.
            sql = ("SELECT u.*,bm25(source_fts) AS score FROM source_fts "
                   "JOIN units u ON u.id=source_fts.rowid "
                   "WHERE source_fts MATCH ? ORDER BY score,u.package,u.id")
            rows = connection.execute(sql, (expression,))
            count = 0
            for row in rows:
                if row["package"] not in eligible:
                    continue
                count += 1
                if row["package"] not in reports:
                    reports[row["package"]] = (row, row["score"])
                if count >= request["bounds"]["unit_matches"]:
                    partial = True
                    break
        items = []
        for ordinal, (package, (unit, score)) in enumerate(reports.items(), 1):
            report = eligible[package]
            source = connection.execute("SELECT * FROM sources WHERE path=?", (unit["path"],)).fetchone()
            handle = g.handle(source, unit["start"], unit["end"])
            items.append(dict(package=package, title=report["title"],
                              rank=ordinal if expression is not None else None,
                              score=dict(kind="bm25", value=score) if score is not None else None,
                              channels=["source"], handles=[handle], quotes=[], routes=[],
                              targets=_targets(json.loads(report["metadata"]), request["target_subjects"])))
    except sqlite3.OperationalError as exc:
        if steps >= bound or "interrupt" in str(exc).lower():
            raise NavError("work_exhausted", "SQLite instruction budget exhausted.") from exc
        raise NavError("invalid_query", "SQLite could not execute quoted query.") from exc
    finally:
        connection.set_progress_handler(None, 0)
    offset = 0
    if position:
        if partial:
            raise NavError("cursor_mismatch", "A partial ranking cannot be continued exactly.")
        if expression is not None:
            offset = position["ordinal"]
            if type(offset) is not int or not 0 < offset < len(items):
                raise NavError("cursor_mismatch", "Rank cursor is outside complete ranking.")
        else:
            keys = [i["package"] for i in items]
            if position["package"] not in keys:
                raise NavError("cursor_mismatch", "Report cursor key missing.")
            offset = keys.index(position["package"]) + 1
    return _page_items(g, request, items, kind, offset, partial)
