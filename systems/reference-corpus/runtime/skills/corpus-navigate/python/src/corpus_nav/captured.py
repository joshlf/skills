"""Exact captured bytes and trusted SQLite image checks shared by both readers."""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
import errno
import os
import sqlite3
import stat

from .response import NavError, sha

FTS_DDL = "CREATE VIRTUAL TABLE source_fts USING fts5(text,tokenize='unicode61')"
FTS_SHADOWS = frozenset({
    "source_fts_data", "source_fts_idx", "source_fts_content",
    "source_fts_docsize", "source_fts_config",
})


def require_image_support() -> None:
    """Fail before effects when this SQLite build lacks exact-image support."""
    if not all(hasattr(sqlite3.Connection, name)
               for name in ("serialize", "deserialize")):
        raise NavError("unsupported_capability",
                       "SQLite serialize/deserialize support is required.")


def read_fd(fd: int, max_bytes: int | None = None) -> bytes:
    """Read a newly opened regular descriptor, optionally enforcing an image cap.

    The caller owns the descriptor. No pathname is reopened after these bytes
    are selected; the expected payload hash is checked before SQLite sees them.
    """
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise NavError("index_mismatch", "Index is not an ordinary file.")
    if max_bytes is not None and before.st_size > max_bytes:
        raise NavError("unsupported_capability", "Image exceeds the reader limit.")
    chunks = []
    total = 0
    while True:
        amount = 1048576 if max_bytes is None else min(1048576, max_bytes + 1 - total)
        block = os.read(fd, amount)
        if not block:
            break
        chunks.append(block)
        total += len(block)
        if max_bytes is not None and total > max_bytes:
            raise NavError("unsupported_capability", "Image grew beyond the reader limit.")
    after = os.fstat(fd)
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
         before.st_ctime_ns) !=
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
             after.st_ctime_ns) or total != after.st_size):
        raise NavError("index_mismatch", "Image changed while being read.")
    return b"".join(chunks)


def read_image(index: dict, max_bytes: int | None = None) -> bytes:
    """Select bytes without following a final symlink or blocking on a FIFO."""
    require_image_support()
    fd = None
    try:
        fd = os.open(index["path"], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        return read_fd(fd, max_bytes)
    except FileNotFoundError as error:
        raise NavError("index_missing", "Selected generation is missing.") from error
    except OSError as error:
        # A symlink/non-directory path is a bad selection, not a usable image.
        code = "index_mismatch" if error.errno in (errno.ELOOP, errno.ENOTDIR) else "io_error"
        raise NavError(code, "Cannot read selected generation.") from error
    finally:
        if fd is not None:
            os.close(fd)


@contextmanager
def open_image(index: dict, image: bytes, validate, max_bytes: int | None = None):
    """Yield a validated private connection to precisely the supplied image.

    ``validate(connection)`` is trusted format code and returns its manifest.
    It may run integrity checks before the connection becomes query-only.
    """
    require_image_support()
    if max_bytes is not None and len(image) > max_bytes:
        raise NavError("unsupported_capability", "Image exceeds the reader limit.")
    if sha(image) != index["sha256"]:
        raise NavError("index_mismatch", "Index payload hash differs.")
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(image)
        connection.row_factory = sqlite3.Row
        connection.enable_load_extension(False)
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute("PRAGMA trusted_schema=OFF")
        manifest = validate(connection)
        connection.commit()
        connection.execute("PRAGMA query_only=ON")
        yield connection, manifest
    except sqlite3.Error as error:
        raise NavError("index_mismatch", "Unreadable or inconsistent SQLite image.") from error
    finally:
        connection.close()


def _columns(connection, name):
    return tuple((row[1], row[2], row[3], row[5], row[6])
                 for row in connection.execute("PRAGMA table_xinfo(" + name + ")"))


@lru_cache(maxsize=1)
def _fts_schema():
    # SQLite owns the physical shadow layout. Derive it from trusted DDL on
    # this runtime, without copying or executing SQL supplied by an image.
    probe = sqlite3.connect(":memory:")
    try:
        probe.enable_load_extension(False)
        probe.execute(FTS_DDL)
        return {name: (probe.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()[0],
            _columns(probe, name)) for name in FTS_SHADOWS}
    finally:
        probe.close()


def validate_fts(connection) -> None:
    """Check fixed internal-content source_fts shadows, tokens and doc sizes.

    This mutating integrity command runs only in a private in-memory database,
    during construction/validation, before callers enable query-only access.
    """
    actual = {row[0]: (row[1], row[2]) for row in connection.execute(
        "SELECT name,type,sql FROM sqlite_master WHERE name LIKE 'source_fts%'")}
    if set(actual) != FTS_SHADOWS | {"source_fts"}:
        raise NavError("index_mismatch", "Unexpected FTS schema objects.")
    if actual["source_fts"] != ("table", FTS_DDL):
        raise NavError("index_mismatch", "Unexpected FTS definition.")
    for name, (sql, columns) in _fts_schema().items():
        if actual[name] != ("table", sql) or _columns(connection, name) != columns:
            raise NavError("index_mismatch", "FTS shadow schema differs from this runtime.")
    connection.execute("INSERT INTO source_fts(source_fts,rank) VALUES('integrity-check',1)")
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise NavError("index_mismatch", "SQLite integrity check failed.")
