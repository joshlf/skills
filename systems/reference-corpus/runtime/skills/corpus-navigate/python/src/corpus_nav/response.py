"""Closed wire requests, canonical identities and bounded output."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
from typing import Any

OPERATIONS = ("doctor", "build", "list", "read", "search", "prepare")
SECTIONS = ("Summary", "Applicability", "Findings", "Boundaries", "Evidence",
            "Revalidation")
DEFAULT_SETTINGS = dict(unit_bytes=4096, query_bytes=4096, query_terms=64,
                        metadata_bytes=1048576, report_bytes=16777216,
                        capture_bytes=1073741824, support={"mode": "inventory"})
DEFAULT_BOUNDS = dict(unit_matches=100000, sqlite_steps=5000000)
EMPTY_FILTERS = dict(topics_any=[], subjects_all=[], literals_all=[])
HASH = re.compile(r"[0-9a-f]{64}\Z")
OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class NavError(Exception):
    def __init__(self, code: str, message: str = "", **details: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("nonfinite JSON number")


def scalar(value: Any) -> None:
    if isinstance(value, str):
        value.encode("utf-8")
    elif isinstance(value, dict):
        for key, item in value.items():
            key.encode("utf-8")
            scalar(item)
    elif isinstance(value, list):
        for item in value:
            scalar(item)
    elif isinstance(value, float):
        canonical(value)


def strict_json(data: bytes) -> Any:
    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                            parse_constant=_constant)
        scalar(result)
        return result
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise NavError("invalid_request", "Invalid scalar UTF-8 JSON.") from exc


def record(value: Any, allowed: set[str], required: set[str] = frozenset()) -> dict:
    if (not isinstance(value, dict) or set(value) - allowed
            or required - set(value)):
        raise NavError("invalid_request", "Unknown or missing record fields.")
    return dict(value)


def text(value: Any, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise NavError("invalid_request", "Expected a string.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise NavError("invalid_request", "Expected Unicode scalar text.") from exc
    return value


def integer(value: Any, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise NavError("invalid_request", "Integer outside supported bounds.")
    return value


def enum(value: Any, choices) -> str:
    if not isinstance(value, str) or value not in choices:
        raise NavError("invalid_request", "Unknown variant.")
    return value


def hashed(value: Any) -> str:
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise NavError("invalid_request", "Expected lowercase SHA-256.")
    return value


def oid(value: Any) -> str:
    if not isinstance(value, str) or not OID.fullmatch(value):
        raise NavError("invalid_request", "Expected full Git object ID.")
    return value


def absolute(value: Any) -> str:
    value = text(value)
    if not os.path.isabs(value) or "\0" in value:
        raise NavError("invalid_request", "Expected explicit absolute path.")
    return value


def raw_path(value: Any) -> bytes:
    try:
        value = text(value)
        raw = base64.b64decode(value, validate=True)
        if base64.b64encode(raw).decode("ascii") != value:
            raise ValueError("noncanonical base64")
        if (not raw or b"\0" in raw or raw.startswith(b"/")
                or any(p in (b"", b".", b"..") for p in raw.split(b"/"))):
            raise ValueError("nonrelative path")
        return raw
    except (ValueError, binascii.Error) as exc:
        raise NavError("invalid_request", "Invalid raw path.") from exc


def encoded_path(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def array(value: Any, parser, unique: bool = True) -> list:
    if not isinstance(value, list):
        raise NavError("invalid_request", "Expected an array.")
    items = [parser(item) for item in value]
    if unique:
        return [v for _, v in sorted({canonical(v): v for v in items}.items())]
    return items


def selector(value: Any) -> dict:
    if not isinstance(value, dict) or not value:
        raise NavError("invalid_request", "Expected nonempty selector.")
    return {text(k): text(v) for k, v in sorted(value.items())}


def filters(value: Any) -> dict:
    result = record(value, set(EMPTY_FILTERS))
    return {k: array(result.get(k, []), selector if k == "subjects_all" else text)
            for k in EMPTY_FILTERS}


def index_ref(value: Any) -> dict:
    value = record(value, {"path", "sha256"}, {"path", "sha256"})
    return dict(path=absolute(value["path"]), sha256=hashed(value["sha256"]))


def handle(value: Any) -> dict:
    keys = {"index_sha256", "corpus_id", "commit", "package", "path_b64",
            "blob", "file_sha256", "start_byte", "end_byte"}
    value = record(value, keys, keys)
    for k in ("index_sha256", "file_sha256"):
        hashed(value[k])
    for k in ("commit", "blob"):
        oid(value[k])
    text(value["corpus_id"])
    if value["package"] is not None:
        text(value["package"])
    raw_path(value["path_b64"])
    for k in ("start_byte", "end_byte"):
        integer(value[k], 0, 2**63 - 1)
    if value["start_byte"] > value["end_byte"]:
        raise NavError("invalid_request", "Reversed byte range.")
    return value


def card(value: Any) -> dict:
    keys = {"package", "recipe_sha256", "path", "sha256"}
    value = record(value, keys, keys)
    return dict(package=text(value["package"]),
                recipe_sha256=hashed(value["recipe_sha256"]),
                path=absolute(value["path"]), sha256=hashed(value["sha256"]))


def parse_request(operation: str, data: bytes) -> dict:
    if operation not in OPERATIONS:
        raise NavError("invalid_request", "Unknown operation.")
    if len(data) > 1048576:
        raise NavError("invalid_request", "Request exceeds 1 MiB.")
    fields = {
        "doctor": {"repository", "cache"},
        "build": {"build_id", "corpus_id", "repository", "ref", "corpus_path",
                  "format", "cache", "recipe", "settings", "card_selections"},
        "list": {"index", "items", "package", "filters", "limit", "continuation"},
        "read": {"index", "select", "continuation"},
        "search": {"index", "query", "filters", "target_subjects", "bounds",
                   "limit", "continuation"},
        "prepare": {"index", "recipe_sha256", "cards_directory", "packages",
                    "selected_cards", "limit", "continuation"},
    }
    required = {
        "doctor": set(), "build": {"build_id", "corpus_id", "repository", "ref",
                                  "corpus_path", "format", "cache"},
        "list": {"index"}, "read": {"index", "select"}, "search": {"index"},
        "prepare": {"index", "recipe_sha256", "cards_directory"},
    }
    r = record(strict_json(data), fields[operation] | {"schema", "max_bytes"},
               required[operation] | {"schema"})
    enum(r["schema"], [f"corpus-nav-{operation}/1"])
    r["max_bytes"] = integer(r.get("max_bytes", 16384), 0, 1048576)
    for key in ("repository", "cache", "cards_directory"):
        if key in r:
            r[key] = absolute(r[key])
    if "index" in r:
        r["index"] = index_ref(r["index"])
    if operation in ("list", "search", "prepare"):
        r["limit"] = integer(r.get("limit", 10), 1, 100)
    if "continuation" in r:
        text(r["continuation"])
    if operation in ("list", "search"):
        r["filters"] = filters(r.get("filters", {}))
    if operation == "list":
        r["items"] = enum(r.get("items", "reports"),
                          ("reports", "admissions", "sources"))
        if "package" in r:
            text(r["package"])
            if r["items"] != "sources":
                raise NavError("invalid_request", "Package applies to sources only.")
        if r["items"] != "reports" and any(r["filters"].values()):
            raise NavError("invalid_request", "Filters apply to reports only.")
    if operation == "search":
        if "query" in r:
            text(r["query"], False)
        r["target_subjects"] = array(r.get("target_subjects", []), selector)
        b = record(r.get("bounds", {}), set(DEFAULT_BOUNDS))
        r["bounds"] = {k: integer(b.get(k, v), 1, 2147483647)
                       for k, v in DEFAULT_BOUNDS.items()}
    if operation == "read":
        s = record(r["select"], {"kind", "handle", "package", "sections"}, {"kind"})
        kind = enum(s["kind"], ("handle", "package"))
        if kind == "handle":
            record(s, {"kind", "handle"}, {"kind", "handle"})
            s["handle"] = handle(s["handle"])
        else:
            record(s, {"kind", "package", "sections"}, {"kind", "package"})
            text(s["package"])
            selected = array(s.get("sections", ["Summary", "Applicability", "Boundaries"]),
                             lambda v: enum(v, SECTIONS), False)
            if len(set(selected)) != len(selected) or not selected:
                raise NavError("invalid_request", "Sections must be nonempty and unique.")
            s["sections"] = [v for v in SECTIONS if v in selected]
        r["select"] = s
    if operation == "build":
        if not re.fullmatch(r"[0-9a-f]{32}", text(r["build_id"])):
            raise NavError("invalid_request", "Invalid build ID.")
        for key in ("corpus_id", "ref"):
            text(r[key])
        if "\0" in r["ref"]:
            raise NavError("invalid_request", "Git ref contains NUL.")
        path = text(r["corpus_path"])
        if path != ".":
            if not path.isascii():
                raise NavError("invalid_request", "Structural path must be ASCII.")
            raw_path(encoded_path(path.encode("ascii")))
        f = record(r["format"], {"reader", "sha256"}, {"reader", "sha256"})
        text(f["reader"])
        hashed(f["sha256"])
        r["recipe"] = enum(r.get("recipe", "source-only/1"),
                           ("source-only/1", "hinted/1"))
        settings = record(r.get("settings", {}), set(DEFAULT_SETTINGS))
        r["settings"] = {k: integer(settings.get(k, v), 1, 2147483647)
                         for k, v in DEFAULT_SETTINGS.items() if k != "support"}
        support = record(settings.get("support", {"mode": "inventory"}),
                         {"mode", "max_file_bytes"}, {"mode"})
        mode = enum(support["mode"], ("inventory", "utf8"))
        if mode == "inventory":
            record(support, {"mode"}, {"mode"})
        else:
            record(support, {"mode", "max_file_bytes"}, {"mode", "max_file_bytes"})
            integer(support["max_file_bytes"], 1, 2147483647)
        r["settings"]["support"] = support
        r["card_selections"] = array(r.get("card_selections", []), card, False)
        keys = [(v["package"], v["recipe_sha256"]) for v in r["card_selections"]]
        if len(set(keys)) != len(keys):
            raise NavError("invalid_request", "Duplicate card selection key.")
        r["card_selections"].sort(key=canonical)
        if r["recipe"] == "source-only/1" and keys:
            raise NavError("invalid_request", "Source-only rejects cards.")
    if operation == "prepare":
        hashed(r["recipe_sha256"])
        r["packages"] = array(r.get("packages", []), text)
        r["selected_cards"] = array(r.get("selected_cards", []), card)
    return r


def semantic(request: dict) -> dict:
    return {k: v for k, v in request.items()
            if k not in ("max_bytes", "limit", "continuation", "build_id")}


def envelope(operation: str, result: dict) -> dict:
    return dict(schema="corpus-nav-result/1", operation=operation, status="ok",
                result=result)


def fits(operation: str, result: dict, cap: int) -> bool:
    return len(canonical(envelope(operation, result))) + 1 <= cap


def error_bytes(operation: str, error: NavError, cap: int) -> tuple[bytes, int, bytes]:
    value = dict(schema="corpus-nav-result/1", operation=operation, status="error",
                 error=dict(code=error.code))
    # The fixed code survives detail reduction; it controls caller recovery.
    details = dict(error.details)
    if error.message:
        details["message"] = error.message
    for key in ("build_id", "checks", "residue", "message"):
        if key in details:
            trial = {**value, "error": {**value["error"], key: details[key]}}
            if len(canonical(trial)) + 1 <= cap:
                value = trial
    data = canonical(value) + b"\n"
    if len(data) > cap:
        return b"", 2, b"budget_too_small\n"
    return data, 1, b""
