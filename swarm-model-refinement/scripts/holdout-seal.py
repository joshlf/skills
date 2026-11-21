#!/usr/bin/env python3
"""Optional opaque at-rest envelope helper for blind holdout partitions.

Seals UTF-8 holdout files behind a clear warning banner and SHA-256-verified
compressed payload so accidental Coordinator reads or post-compaction directory
scans do not expose plaintext holdout premises. Cooperative safeguard only, not
an OS privilege boundary and not workflow or publication authority.
"""

# Threat model and scope
#
# Executing agents invoke this script as a CLI (`seal`, `open`, `verify`) rather
# than reading its source into context. It prevents accidental cooperative leaks
# by a synthesizing Coordinator (for example, calling `read_file` on a plaintext
# holdout file after context compaction) while allowing each pass's ephemeral
# Holdout Evaluator to decode authorized partitions on demand. Same-UID files
# and `0400` permissions do not resist a hostile same-UID process and do not
# enforce OS sandboxing or action authority.
#
# Compatibility assumptions
#
# - This script depends only on the Python 3.8+ standard library; do not add
#   third-party packages or Python 3.9+ string/Path methods such as
#   `removeprefix` or `is_relative_to`.
# - Behavior must stay portable across Linux and macOS, including symlinked
#   ancestor directories (such as macOS `/var -> /private/var`) and non-UTF-8
#   host locales (such as `LC_ALL=C` or `PYTHONIOENCODING=latin-1`).
#
# On-disk `.sealed` envelope format (schema v1)
#
# - Line 1: `BANNER`, ending with LF (`\n`).
# - Line 2: compact single-line JSON object with exact keys `bytes`,
#   `content_sha256`, `label`, and `schema` (`1`), ending with LF.
# - Lines 3..N: standard RFC 4648 Base64 encoding of `zlib.compress(payload, 9)`
#   wrapped at 76 ASCII characters per line, with no blank lines and one
#   trailing LF.
# - Neither the header, stdout JSON metadata, nor stderr diagnostics ever emit
#   plaintext holdout content.

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import List, Optional, Tuple
import unicodedata
import zlib

# Place a warning banner on line 1 so any accidental file peek or truncated
# preview immediately identifies the file as a sealed holdout rather than
# ordinary workspace text.
BANNER = "# STOP — DO NOT READ OR DECODE: SEALED SWARM-MODEL-REFINEMENT HOLDOUT\n"

# Reject Unicode control (`Cc`), format/bidi (`Cf`), surrogate (`Cs`), and
# line/paragraph separator (`Zl`, `Zp`) characters in CLI paths and envelope
# lines. Excluding `Zl`/`Zp` (`U+2028`/`U+2029`) prevents mismatches between
# `str.splitlines()` and explicit `\n` splitting; excluding `Cf` blocks
# invisible bidi overrides in filenames or tampered envelope lines.
FORBIDDEN_CATS = {"Cc", "Cf", "Cs", "Zl", "Zp"}

# Require the JSON header to contain this exact key set. Exact-set matching
# blocks both missing required fields and spoofed extra keys (such as
# `"verified": false`) that would collide when merged into CLI JSON output.
HEADER_KEYS = {"schema", "label", "bytes", "content_sha256"}

# Restrict unsealed `--label` metadata to short ASCII IDs (`<= 64` chars, no
# whitespace) so callers cannot leak holdout premise text into plaintext
# headers or stdout JSON. `\A...\Z` is mandatory instead of `^...$` because `$`
# matches before a trailing newline in Python regexes and would accept
# JSON-escaped newlines such as `"P1\n"`.
LABEL_RE = re.compile(r"\A[A-Za-z0-9_.:-]{0,64}\Z")

# Cap plaintext and envelope sizes to protect against accidental binary dumps
# and decompression bombs while staying well above realistic text holdout
# partitions. `MAX_ENV_BYTES` leaves headroom above `MAX_PLAIN_BYTES` for
# worst-case incompressible data under Base64's 4/3 expansion plus line
# wrapping and header framing.
MAX_PLAIN_BYTES = 12 * 1024 * 1024
MAX_ENV_BYTES = 18 * 1024 * 1024


class SealError(ValueError):
    """Fail-closed validation or integrity error."""


# Centralize fail-closed invariant checks so every violated precondition raises
# `SealError`, which `__main__` reports concisely on stderr with exit code 1
# without printing a traceback or payload fragments.
def require(cond: bool, msg: str) -> None:
    if not cond:
        raise SealError(msg)


# Validate CLI paths and envelope framing lines (never the decoded holdout
# payload itself, which may legitimately contain tabs or arbitrary valid UTF-8
# text).
def check_clean_text(text: str, label: str) -> None:
    for idx, ch in enumerate(text):
        require(unicodedata.category(ch) not in FORBIDDEN_CATS, f"Control char U+{ord(ch):04X} in {label} at {idx}")


# Remove a destination file on a best-effort basis after partial writes,
# interrupted runs, or failed post-write `--unlink-input` steps so no orphan
# file remains to block retries under `O_EXCL`.
#
# Newly created `.sealed` files are mode `0o400` (read-only), so we restore
# `0o600` before unlinking on environments that disallow unlinking read-only
# files. Guarding with `not os.path.islink` ensures `chmod` never follows a
# symlink.
def safe_unlink(path: Path) -> None:
    try:
        if not os.path.islink(str(path)) and path.exists():
            os.chmod(path, 0o600)
        os.unlink(path)
    except OSError:
        pass


# Canonicalize a caller-supplied file path while tolerating symlinked ancestor
# directories (common on macOS and symlinked scratch mounts) and strictly
# rejecting symlinks at the final leaf path.
#
# `..` segments must be rejected before `os.path.abspath`, because `abspath`
# collapses `symlink_dir/../target` lexically without resolving `symlink_dir`;
# under `--unlink-input`, that mismatch could seal one file and unlink an
# unrelated bystander in the lexical parent directory.
#
# Checking `islink` both before and after resolving `abs_p.parent` via
# `realpath` rejects leaf symlinks immediately and returns a single canonical
# parent path for distinct-path comparisons (`input` vs. `--output`). The
# remaining narrow race window before opening is closed by `O_NOFOLLOW` in
# `read_regular_utf8` and `write_create_new`.
def resolve_leaf_path(raw_str: str) -> Path:
    check_clean_text(raw_str, "path")
    expanded = Path(os.path.expanduser(raw_str))
    require(bool(raw_str.strip()) and ".." not in expanded.parts, f"Unsafe or '..' path forbidden: {raw_str!r}")
    abs_p = Path(os.path.abspath(str(expanded)))
    require(not os.path.islink(str(abs_p)), f"Symlink target forbidden: {abs_p}")
    require(abs_p.parent.is_dir(), f"Parent directory does not exist: {abs_p.parent}")
    resolved = Path(os.path.realpath(str(abs_p.parent))) / abs_p.name
    require(not os.path.islink(str(resolved)), f"Symlink target forbidden: {resolved}")
    return resolved


# Read a regular, non-symlink UTF-8 file up to `max_bytes`, returning its
# canonical leaf path and exact unmodified raw bytes.
#
# - `O_NOFOLLOW` closes any symlink swap after `resolve_leaf_path`.
# - `O_NONBLOCK` prevents blocking indefinitely if the path points to a FIFO or
#   named pipe before `fstat` verifies `S_ISREG`.
# - `single_link=True` (enabled for `seal --unlink-input`) requires
#   `st_nlink == 1` on the open descriptor: unlinking one hardlink would leave
#   another plaintext directory entry pointing at the same holdout inode.
# - Size is checked both via `st_size` upfront and cumulatively on every read
#   chunk to handle concurrent growth or filesystems with zero or inaccurate
#   `st_size`.
# - UTF-8 decoding is validated here without replacing the returned raw bytes so
#   non-UTF-8 binaries fail closed while valid text preserves exact byte layout
#   and line endings.
def read_regular_utf8(path_str: str, max_bytes: int, *, single_link: bool = False) -> Tuple[Path, bytes]:
    path = resolve_leaf_path(path_str)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise SealError(f"Cannot open regular non-symlink file {path}: {exc}") from exc
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode), f"Not a regular file: {path}")
        require(not single_link or st.st_nlink == 1, f"Refusing hardlinked file with --unlink-input: {path}")
        require(st.st_size <= max_bytes, f"File exceeds {max_bytes} byte limit: {path}")
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            require(total <= max_bytes, f"File exceeds {max_bytes} byte limit: {path}")
            chunks.append(chunk)
    finally:
        os.close(fd)
    raw = b"".join(chunks)
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SealError(f"File must be valid UTF-8: {path}") from exc
    return path, raw


# Atomically create a new destination file at `dest_str` with exact permissions
# `mode`, refusing to overwrite any existing file or follow a symlink.
#
# - `O_CREAT | O_EXCL | O_NOFOLLOW` prevents accidental clobbering of prior
#   sealed partitions or opened outputs and closes symlink races at creation.
# - Looping over a `memoryview` handles partial POSIX `os.write` calls without
#   repeatedly slicing and copying `bytes`.
# - `os.fchmod(fd, mode)` enforces the exact requested mode on the open
#   descriptor regardless of process `umask` (falling back to `os.chmod` only on
#   platforms lacking `fchmod`).
# - Catching `BaseException` (including `KeyboardInterrupt`) closes `fd` and
#   unlinks the partial file so interrupted runs leave no stale artifact.
def write_create_new(dest_str: str, data: bytes, mode: int) -> Path:
    dest = resolve_leaf_path(dest_str)
    try:
        fd = os.open(str(dest), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    except FileExistsError as exc:
        raise SealError(f"Refusing to overwrite existing destination: {dest}") from exc
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        if hasattr(os, "fchmod"):
            os.fchmod(fd, mode)
    except BaseException:
        os.close(fd)
        safe_unlink(dest)
        raise
    os.close(fd)
    if not hasattr(os, "fchmod"):
        os.chmod(dest, mode)
    return dest


# Read, validate, and decode a schema-v1 `.sealed` envelope, returning a fresh
# copy of its verified header dict and the exact raw UTF-8 payload bytes.
#
# Line splitting uses explicit `\n` rather than `str.splitlines()` so embedded
# `\r`, vertical tabs, or Unicode line separators cannot silently alter framing
# (`check_clean_text` also rejects them).
def decode_envelope(path_str: str) -> Tuple[dict, bytes]:
    text = read_regular_utf8(path_str, MAX_ENV_BYTES)[1].decode("utf-8")
    require(text.startswith(BANNER) and text.endswith("\n"), "Missing banner or trailing newline")
    lines = text[len(BANNER):-1].split("\n")
    require(len(lines) >= 2 and all(lines), "Truncated or blank-line sealed envelope")
    for line in lines:
        check_clean_text(line, "envelope line")
    try:
        hdr = json.loads(lines[0])
    except Exception as exc:
        raise SealError(f"Malformed envelope header: {exc}") from exc
    # Use `type(...) is int` rather than `isinstance(..., int)` because Python's
    # `bool` subclasses `int`, which would otherwise accept `"schema": true` or
    # `"bytes": true`. Re-validate `label` with `LABEL_RE` so tampered headers
    # carrying newlines or premise text fail closed on `verify` and `open`; the
    # 64-char `content_sha256` check is tightened to exact lowercase hex
    # equality after decompression.
    require(
        isinstance(hdr, dict) and set(hdr) == HEADER_KEYS and type(hdr["schema"]) is int and hdr["schema"] == 1
        and type(hdr["bytes"]) is int and 1 <= hdr["bytes"] <= MAX_PLAIN_BYTES and type(hdr["label"]) is str
        and bool(LABEL_RE.fullmatch(hdr["label"])) and type(hdr["content_sha256"]) is str
        and len(hdr["content_sha256"]) == 64,
        "Invalid sealed holdout header",
    )
    # Decompress via a bounded `decompressobj` instead of `zlib.decompress` so a
    # crafted decompression bomb cannot allocate unbounded memory. Passing
    # `MAX_PLAIN_BYTES + 1` lets an exact `MAX_PLAIN_BYTES` payload succeed
    # while any larger output leaves `unconsumed_tail` or exceeds the cap.
    #
    # Requiring `dec.eof and not dec.unused_data` rejects both truncated streams
    # (such as a `Z_SYNC_FLUSH` payload missing `Z_STREAM_END`) and
    # unauthenticated trailing bytes appended after `Z_STREAM_END`.
    try:
        dec = zlib.decompressobj()
        payload = dec.decompress(base64.b64decode("".join(lines[1:]), validate=True), MAX_PLAIN_BYTES + 1)
        require(not dec.unconsumed_tail and len(payload) <= MAX_PLAIN_BYTES, "Decompressed payload exceeds size limit")
        payload += dec.flush(MAX_PLAIN_BYTES + 1 - len(payload))
        require(dec.eof and not dec.unused_data and len(payload) <= MAX_PLAIN_BYTES, "Malformed compressed stream")
        payload.decode("utf-8")
    except SealError:
        raise
    except Exception as exc:
        raise SealError(f"Corrupted sealed holdout payload: {exc}") from exc
    require(
        len(payload) == hdr["bytes"] and hashlib.sha256(payload).hexdigest() == hdr["content_sha256"],
        "Sealed holdout SHA-256 or byte-length mismatch",
    )
    return dict(hdr), payload


# Run the `seal`, `open`, or `verify` subcommand and return a process exit code.
#
# `allow_abbrev=False` is set on the root parser and every subparser so
# mistyped options fail closed instead of matching an unintended flag prefix.
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_seal = sub.add_parser("seal", help="Create a new 0400 .sealed holdout file from UTF-8 input", allow_abbrev=False)
    p_seal.add_argument("input", help="Non-empty plaintext UTF-8 holdout file")
    p_seal.add_argument("--output", required=True, help="New destination .sealed path (never overwrites)")
    p_seal.add_argument("--label", default="", help="Short partition ID (unsealed metadata, e.g. P1; no premise text)")
    p_seal.add_argument("--unlink-input", action="store_true", help="Unlink plaintext input after verified seal")
    p_open = sub.add_parser("open", help="Verify and decode a .sealed holdout file", allow_abbrev=False)
    p_open.add_argument("sealed", help="Path to .sealed holdout file")
    out_grp = p_open.add_mutually_exclusive_group(required=True)
    out_grp.add_argument("--output", help="New 0600 destination file in Holdout Evaluator scratch (never overwrites)")
    out_grp.add_argument("--stdout", action="store_true", help="Write decoded UTF-8 bytes to stdout")
    sub.add_parser("verify", help="Verify .sealed integrity without exposing content", allow_abbrev=False).add_argument(
        "sealed", help="Path to .sealed holdout file"
    )

    args = parser.parse_args(argv)
    if args.cmd == "seal":
        # Reject empty or whitespace-only inputs so a blank file cannot be
        # sealed as a valid holdout partition, and reject identical input/output
        # paths before opening `--output` or considering `--unlink-input`.
        src, payload = read_regular_utf8(args.input, MAX_PLAIN_BYTES, single_link=args.unlink_input)
        require(bool(payload.strip()), f"Holdout input is empty or whitespace-only: {src}")
        require(src != resolve_leaf_path(args.output), "Input and --output must be distinct paths")
        label = args.label.strip()
        require(bool(LABEL_RE.fullmatch(label)), "Invalid --label: use <=64 ASCII id chars [A-Za-z0-9_.:-]")
        hdr = {
            "schema": 1, "label": label, "bytes": len(payload),
            "content_sha256": hashlib.sha256(payload).hexdigest(),
        }
        # Wrap Base64 at 76 columns for clean ASCII envelopes and create the
        # sealed file with mode `0o400` (owner read-only) as a cooperative guard
        # against accidental in-place edits.
        b64 = base64.b64encode(zlib.compress(payload, 9)).decode("ascii")
        body = "\n".join(b64[i:i + 76] for i in range(0, len(b64), 76))
        dst = write_create_new(args.output, f"{BANNER}{json.dumps(hdr, sort_keys=True)}\n{body}\n".encode(), 0o400)
        # Round-trip verify the on-disk envelope before unlinking the plaintext
        # source. If verification or `os.unlink(src)` fails (for example, when
        # the source directory is read-only), roll back `dst` so no orphan
        # `.sealed` file blocks a clean retry after permissions are fixed.
        try:
            require(decode_envelope(str(dst))[1] == payload, "Post-write seal verification failed")
            if args.unlink_input:
                os.unlink(src)
        except BaseException:
            safe_unlink(dst)
            raise
        print(json.dumps({**hdr, "sealed": str(dst)}, sort_keys=True))
    elif args.cmd == "open":
        hdr, payload = decode_envelope(args.sealed)
        if args.stdout:
            # Write raw UTF-8 bytes directly to `sys.stdout.buffer` rather than
            # printing decoded `str` so non-UTF-8 locales (`LC_ALL=C`,
            # `PYTHONIOENCODING=latin-1`) cannot raise `UnicodeEncodeError` or
            # transcode holdout characters.
            sys.stdout.buffer.write(payload)
            sys.stdout.buffer.flush()
        else:
            # Decoded scratch outputs use mode `0o600` (owner read/write only)
            # so Holdout Evaluator scratch files are not group- or
            # world-readable.
            print(json.dumps({**hdr, "opened": str(write_create_new(args.output, payload, 0o600))}, sort_keys=True))
    else:
        # `verify` runs full decode and SHA-256 checks without emitting payload
        # bytes, keeping it safe for Coordinator integrity verification.
        print(json.dumps({**decode_envelope(args.sealed)[0], "verified": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    # Report expected validation and filesystem errors concisely on stderr with
    # exit status 1, avoiding tracebacks or accidental payload echoes.
    try:
        raise SystemExit(main())
    except (SealError, OSError) as err:
        print(f"holdout-seal: {err}", file=sys.stderr)
        raise SystemExit(1)
