"""Command boundary for trusted native corpus navigation."""

from __future__ import annotations

import argparse
import sqlite3
import sys

from corpus_nav.cli import doctor as shared_doctor

from . import generation, retrieval
from .wire import (
    MAX_INDEX_BYTES,
    OPERATIONS,
    READER,
    NavError,
    canonical,
    envelope,
    error_bytes,
    fits,
    parse_request,
    strict_json,
)


def doctor(request):
    generation.require_image_support()
    result = shared_doctor(request)
    result["native"] = dict(
        reader=READER,
        max_index_bytes=MAX_INDEX_BYTES,
        image_loading="exact-hashed-bytes-deserialize",
        sqlite=sqlite3.sqlite_version,
    )
    return result


def execute(operation, request):
    if operation == "doctor":
        result = doctor(request)
    elif operation == "prepare":
        raise NavError(
            "unsupported_capability", "Native preparation is unsupported."
        )
    elif operation == "build":
        result = generation.build(request)
    else:
        with generation.open_generation(request["index"]) as view:
            result = {
                "list": retrieval.list_items,
                "read": retrieval.read,
                "search": retrieval.search,
            }[operation](view, request)
    if not fits(operation, result, request["max_bytes"]):
        raise NavError("budget_too_small")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    parser.add_argument("--request", choices=["-"], default="-")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    cap = 16384
    try:
        data = sys.stdin.buffer.read(1048577)
        if len(data) <= 1048576:
            raw = strict_json(data)
            if (
                isinstance(raw, dict)
                and type(raw.get("max_bytes")) is int
                and 0 <= raw["max_bytes"] <= 1048576
            ):
                cap = raw["max_bytes"]
        request = parse_request(args.operation, data)
        cap = request["max_bytes"]
        result = execute(args.operation, request)
        sys.stdout.buffer.write(
            canonical(envelope(args.operation, result)) + b"\n"
        )
        return 0
    except NavError as error:
        output, code, diagnostic = error_bytes(args.operation, error, cap)
        sys.stdout.buffer.write(output)
        sys.stderr.buffer.write(diagnostic)
        return code
    except OSError:
        output, code, diagnostic = error_bytes(
            args.operation, NavError("io_error"), cap
        )
        sys.stdout.buffer.write(output)
        sys.stderr.buffer.write(diagnostic)
        return code


if __name__ == "__main__":
    raise SystemExit(main())
