"""Closed native requests and byte-counted JSON responses."""

from __future__ import annotations

import re

from corpus_nav.response import (
    NavError,
    absolute,
    array,
    canonical,
    digest,
    encoded_path,
    hashed,
    index_ref,
    integer,
    oid,
    raw_path,
    record,
    semantic,
    sha,
    strict_json,
    text,
)

OPERATIONS = ("doctor", "build", "list", "read", "search", "prepare")
READER = "rircon-prior-art/1"
MAX_INDEX_BYTES = 256 * 1024 * 1024
CONTEXT_PATHS = (
    "docs/README.md",
    "docs/prior-art.md",
    "docs/prior-art/AGENTS.md",
    "docs/prior-art/README.md",
)
SETTINGS = dict(
    unit_bytes=4096,
    query_bytes=4096,
    query_terms=64,
    source_bytes=16777216,
    capture_bytes=1073741824,
)
BOUNDS = dict(unit_matches=100000, sqlite_steps=5000000)


def source_handle(value):
    keys = {
        "index_sha256",
        "corpus_id",
        "commit",
        "path_b64",
        "blob",
        "file_sha256",
        "start_byte",
        "end_byte",
    }
    value = record(value, keys, keys)
    for key in ("index_sha256", "file_sha256"):
        hashed(value[key])
    for key in ("commit", "blob"):
        oid(value[key])
    text(value["corpus_id"])
    raw_path(value["path_b64"])
    for key in ("start_byte", "end_byte"):
        integer(value[key], 0, 2**63 - 1)
    if value["start_byte"] > value["end_byte"]:
        raise NavError("invalid_request", "Reversed source range.")
    return value


def parse_request(operation, data):
    if operation not in OPERATIONS or len(data) > 1048576:
        raise NavError(
            "invalid_request", "Unknown operation or oversized request."
        )
    fields = {
        "doctor": {"repository", "cache"},
        "build": {
            "build_id",
            "corpus_id",
            "repository",
            "ref",
            "reader",
            "required_context",
            "cache",
            "settings",
            "recipe",
            "card_selections",
        },
        "list": {
            "index",
            "items",
            "document",
            "container",
            "limit",
            "continuation",
        },
        "read": {"index", "handle", "continuation"},
        "search": {
            "index",
            "query",
            "document",
            "container",
            "literals_all",
            "bounds",
            "limit",
            "continuation",
        },
        "prepare": set(),
    }
    required = {
        "doctor": set(),
        "prepare": set(),
        "build": {
            "build_id",
            "corpus_id",
            "repository",
            "ref",
            "reader",
            "required_context",
            "cache",
        },
        "list": {"index"},
        "read": {"index", "handle"},
        "search": {"index"},
    }
    r = record(
        strict_json(data),
        fields[operation] | {"schema", "max_bytes"},
        required[operation] | {"schema"},
    )
    if r["schema"] != f"corpus-docs-{operation}/1":
        raise NavError("invalid_request", "Wrong native request schema.")
    r["max_bytes"] = integer(r.get("max_bytes", 16384), 0, 1048576)
    for key in ("repository", "cache"):
        if key in r:
            r[key] = absolute(r[key])
    if "index" in r:
        r["index"] = index_ref(r["index"])
    for key in ("document", "container"):
        if key in r:
            raw_path(r[key])
    if "continuation" in r:
        text(r["continuation"])
    if operation in ("list", "search"):
        r["limit"] = integer(r.get("limit", 10), 1, 100)
    if operation == "build":
        if not re.fullmatch(r"[0-9a-f]{32}", text(r["build_id"])):
            raise NavError("invalid_request", "Invalid caller-known build ID.")
        text(r["corpus_id"])
        text(r["ref"])
        if "\0" in r["ref"]:
            raise NavError("invalid_request", "Git ref contains NUL.")
        if text(r["reader"]) != READER:
            raise NavError(
                "unsupported_format", "Unknown native interpretation."
            )
        r["recipe"] = text(r.get("recipe", "source-only/1"))
        cards = r.get("card_selections", [])
        if not isinstance(cards, list):
            raise NavError(
                "invalid_request", "Card selections must be an array."
            )
        if r["recipe"] != "source-only/1" or cards:
            raise NavError(
                "unsupported_capability", "Native preparation is unsupported."
            )
        r["card_selections"] = []
        context = record(
            r["required_context"], set(CONTEXT_PATHS), set(CONTEXT_PATHS)
        )
        r["required_context"] = {
            path: hashed(context[path]) for path in CONTEXT_PATHS
        }
        settings = record(r.get("settings", {}), set(SETTINGS))
        r["settings"] = {
            k: integer(settings.get(k, v), 1, 2147483647)
            for k, v in SETTINGS.items()
        }
    elif operation == "list":
        r["items"] = r.get("items", "documents")
        if r["items"] not in ("documents", "sources", "headings"):
            raise NavError("invalid_request", "Unknown native listing.")
        if (
            r["items"] == "headings"
            and ("document" not in r or "container" in r)
            or r["items"] == "sources"
            and "container" in r
        ):
            raise NavError("invalid_request", "Invalid listing selector.")
    elif operation == "read":
        r["handle"] = source_handle(r["handle"])
    elif operation == "search":
        if "query" in r:
            text(r["query"], False)
        r["literals_all"] = array(r.get("literals_all", []), text)
        bounds = record(r.get("bounds", {}), set(BOUNDS))
        r["bounds"] = {
            k: integer(bounds.get(k, v), 1, 2147483647)
            for k, v in BOUNDS.items()
        }
    return r


def envelope(operation, result):
    return dict(
        schema="corpus-docs-result/1",
        operation=operation,
        status="ok",
        result=result,
    )


def fits(operation, result, cap):
    return len(canonical(envelope(operation, result))) + 1 <= cap


def error_bytes(operation, error, cap):
    value = dict(
        schema="corpus-docs-result/1",
        operation=operation,
        status="error",
        error=dict(code=error.code),
    )
    details = {**error.details}
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
