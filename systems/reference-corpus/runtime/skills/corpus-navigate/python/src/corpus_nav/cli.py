"""Command boundary for the closed corpus navigator API."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

from . import captured, generation, git_source, preparation, publishing, retrieval
from .response import (NavError, OPERATIONS, canonical, envelope, error_bytes,
                       fits, parse_request, strict_json)


def doctor(request: dict) -> dict:
    checks = []
    residue = []
    try:
        captured.require_image_support()
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
            connection.execute("INSERT INTO probe VALUES('token')")
            if connection.execute("SELECT count(*) FROM probe WHERE probe MATCH 'token'").fetchone()[0] != 1:
                raise ValueError("FTS5 query failed")
        finally:
            connection.close()
        checks.append(dict(name="runtime", state="passed", detail="Python >=3.11; exact SQLite images; SQLite " + sqlite3.sqlite_version + "; FTS5 available"))
    except (sqlite3.Error, ValueError, NavError):
        checks.append(dict(name="runtime", state="failed", detail="SQLite image API or FTS5 unavailable"))
    if "repository" not in request:
        checks.append(dict(name="git", state="not_examined", detail="No repository selected"))
    else:
        try:
            detail = git_source.check(request["repository"])
            checks.append(dict(name="git", state="passed", detail=detail))
        except NavError as exc:
            checks.append(dict(name="git", state="failed", detail=exc.message))
    if "cache" not in request:
        checks.append(dict(name="publication", state="not_examined", detail="No cache selected"))
    else:
        probe = None
        descriptors = []
        try:
            cache = Path(request["cache"])
            # Only the selected cache is probed. Corpus objects stay read-only.
            cache.mkdir(parents=True, exist_ok=True)
            cache_fd = publishing._directory(cache)
            descriptors.append(cache_fd)
            probe = Path(tempfile.mkdtemp(prefix=".corpus-nav-probe-", dir=cache))
            probe_fd = publishing._directory(probe)
            descriptors.append(probe_fd)
            bindings = [(cache, publishing._identity(cache_fd)),
                        (probe, publishing._identity(probe_fd))]
            # Names may change while the probe runs. Exclusive descriptor-based
            # writes preserve a replacement file rather than truncating it.
            source_fd = os.open("source", os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                os.O_NOFOLLOW, 0o600, dir_fd=probe_fd)
            descriptors.append(source_fd)
            payload = b"publication probe\n"
            if os.write(source_fd, payload) != len(payload):
                raise OSError("short publication probe write")
            os.fsync(source_fd)
            source_identity = publishing._identity(source_fd)
            os.link("source", "target", src_dir_fd=probe_fd,
                    dst_dir_fd=probe_fd, follow_symlinks=False)
            try:
                os.link("source", "target", src_dir_fd=probe_fd,
                        dst_dir_fd=probe_fd, follow_symlinks=False)
            except FileExistsError:
                pass
            else:
                raise OSError("publication overwrote a destination")
            target_fd = os.open("target", os.O_RDONLY | os.O_NOFOLLOW |
                                os.O_NONBLOCK, dir_fd=probe_fd)
            descriptors.append(target_fd)
            if (publishing._identity(target_fd) != source_identity or
                    captured.read_fd(target_fd, 64) != payload):
                raise OSError("link contents differ")
            os.fsync(probe_fd)
            publishing._check_directories(bindings)
            target = os.stat("target", dir_fd=probe_fd, follow_symlinks=False)
            if (target.st_dev, target.st_ino) != source_identity:
                raise OSError("probe target changed")
            checks.append(dict(name="publication", state="passed", detail="Local mkdir, hard-link no-clobber and fsync probe passed"))
        except (OSError, NavError, publishing._ChangedNamespace):
            checks.append(dict(name="publication", state="failed", detail="Local publication probe failed"))
        finally:
            for fd in reversed(descriptors):
                os.close(fd)
            if probe is not None:
                # The last known path is useful for reconciliation, but is not
                # a receipt granting permission to delete its current contents.
                residue.append(str(probe))
    if any(c["state"] == "failed" for c in checks):
        raise NavError("unsupported_capability", "Requested capability checks failed.", checks=checks, residue=residue)
    return dict(checks=checks, residue=residue)


def execute(operation: str, request: dict) -> dict:
    if operation == "doctor":
        result = doctor(request)
    elif operation == "build":
        result = generation.build(request)
    elif operation == "prepare":
        result = preparation.prepare(request)
    else:
        with generation.open_generation(request["index"]) as g:
            if operation == "list":
                result = retrieval.list_items(g, request)
            elif operation == "read":
                result = retrieval.read(g, request)
            elif operation == "search":
                result = retrieval.search(g, request)
            else:
                raise NavError("invalid_request", "Unknown operation.")
    if not fits(operation, result, request["max_bytes"]):
        raise NavError("budget_too_small")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    parser.add_argument("--request", choices=["-"], default="-")
    parser.add_argument("--json", action="store_true",
                        help="emit the stable JSON wire representation")
    args = parser.parse_args(argv)
    cap = 16384
    try:
        data = sys.stdin.buffer.read(1048577)
        # Honor a valid cap even when another field makes the request invalid.
        if len(data) <= 1048576:
            raw = strict_json(data)
            if isinstance(raw, dict) and type(raw.get("max_bytes")) is int and 0 <= raw["max_bytes"] <= 1048576:
                cap = raw["max_bytes"]
        request = parse_request(args.operation, data)
        cap = request["max_bytes"]
        result = execute(args.operation, request)
        sys.stdout.buffer.write(canonical(envelope(args.operation, result)) + b"\n")
        return 0
    except NavError as exc:
        output, code, diagnostic = error_bytes(args.operation, exc, cap)
        sys.stdout.buffer.write(output)
        sys.stderr.buffer.write(diagnostic)
        return code
    except OSError:
        output, code, diagnostic = error_bytes(args.operation, NavError("io_error"), cap)
        sys.stdout.buffer.write(output)
        sys.stderr.buffer.write(diagnostic)
        return code


if __name__ == "__main__":
    raise SystemExit(main())
