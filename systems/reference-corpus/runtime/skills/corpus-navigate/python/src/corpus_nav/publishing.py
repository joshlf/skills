"""One immutable publication protocol for the two trusted corpus formats."""

from __future__ import annotations

import errno

import os
from pathlib import Path
import re
import sqlite3
import stat

from . import captured
from .response import NavError, semantic, sha


class _ChangedNamespace(Exception):
    pass


def _identity(fd):
    observed = os.fstat(fd)
    return observed.st_dev, observed.st_ino


def _directory(path):
    try:
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise _ChangedNamespace from error
        raise


def _child_directory(parent, name, create=False):
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
    try:
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                       dir_fd=parent)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise _ChangedNamespace from error
        raise


def residue(staging: Path) -> list[str]:
    """Observe a pathname; this inventory grants no ownership or deletion right."""
    return [str(staging)] if os.path.lexists(staging) else []


def _check_directories(bindings):
    for path, expected in bindings:
        try:
            current = path.lstat()
        except OSError as error:
            raise _ChangedNamespace from error
        if (not stat.S_ISDIR(current.st_mode)
                or (current.st_dev, current.st_ino) != expected):
            raise _ChangedNamespace


def _observe_index(index, reservation_fd, bindings, payload_identity,
                   max_image_bytes):
    """Observe named bindings after descriptor-based work, without a lease.

    Descriptors survive rename; a returned pathname does not. These checks
    cannot promise future liveness against a writer after the observations.
    Every later reader checks its selected bytes again.
    """
    fd = None
    name = Path(index["path"]).name
    try:
        _check_directories(bindings)
        if os.listdir(reservation_fd) != [name]:
            raise _ChangedNamespace
        fd = os.open(index["path"], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        if (_identity(fd) != payload_identity
                or sha(captured.read_fd(fd, max_image_bytes)) != index["sha256"]):
            raise _ChangedNamespace
        if os.listdir(reservation_fd) != [name]:
            raise _ChangedNamespace
        _check_directories(bindings)
    except (OSError, NavError) as error:
        raise _ChangedNamespace from error
    finally:
        if fd is not None:
            os.close(fd)


def _recover(request, reservation, reservation_fd, staging, bindings,
             open_image, project_result, max_image_bytes, expected_inode=None):
    names = os.listdir(reservation_fd)
    if not names:
        raise NavError("attempt_incomplete", "Reserved build has no published payload.")
    if len(names) != 1 or not re.fullmatch(r"[0-9a-f]{64}\.sqlite", names[0]):
        raise NavError("attempt_conflict", "Unexpected reservation contents.")
    try:
        fd = os.open(names[0], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=reservation_fd)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise NavError("attempt_conflict", "Published entry is not ordinary.") from error
        raise
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise NavError("attempt_conflict", "Published entry is not ordinary.")
        payload_identity = _identity(fd)
        if expected_inode is not None and payload_identity != expected_inode:
            raise _ChangedNamespace
        image = captured.read_fd(fd, max_image_bytes)
    finally:
        os.close(fd)
    index = dict(path=str(reservation / names[0]), sha256=names[0][:-7])
    with open_image(index, image) as generation:
        if (generation.manifest["build_id"] != request["build_id"]
                or generation.manifest["semantic_request"] != semantic(request)):
            raise NavError("attempt_conflict", "Build ID is bound to another request.")
        result = project_result(request, generation, residue(staging))
        _observe_index(index, reservation_fd, bindings, payload_identity,
                       max_image_bytes)
        return result


def build(request, *, namespaces, make_image, open_image, project_result,
          preflight, max_image_bytes=None):
    """Publish a trusted format's image or recover a known completed build.

    The two format callers supply four ordinary functions: make_image(request)
    returns bytes; open_image(index, bytes) validates and yields its Generation;
    project_result(request, generation, residue) checks its own wire budget
    and returns the bounded result, or raises budget_too_small;
    preflight(request, reservation, staging) checks supported construction
    inputs and the prospective output cap before reserving a new build.
    No source callback runs during recovery. Staging is retained as explicit
    residue, avoiding automatic deletion of a path whose ownership may change.
    """
    captured.require_image_support()
    indexes_name, builds_name = namespaces
    cache = Path(request["cache"])
    reservation = cache / indexes_name / request["build_id"]
    staging = cache / builds_name / request["build_id"]
    descriptors = []
    link_attempted = False
    try:
        preflighted = not os.path.lexists(reservation)
        if preflighted:
            preflight(request, reservation, staging)
        cache.mkdir(parents=True, mode=0o700, exist_ok=True)
        cache_fd = _directory(cache)
        descriptors.append(cache_fd)
        indexes_fd = _child_directory(cache_fd, indexes_name, create=True)
        descriptors.append(indexes_fd)
        bindings = [(cache, _identity(cache_fd)),
                    (cache / indexes_name, _identity(indexes_fd))]
        # Existing completed builds use their actual bounded result rather
        # than the construction preflight's worst-case count placeholders.
        if not preflighted and request["build_id"] not in os.listdir(indexes_fd):
            preflight(request, reservation, staging)
        try:
            os.mkdir(request["build_id"], mode=0o700, dir_fd=indexes_fd)
        except FileExistsError:
            reservation_fd = _child_directory(indexes_fd, request["build_id"])
            descriptors.append(reservation_fd)
            bindings.append((reservation, _identity(reservation_fd)))
            return _recover(request, reservation, reservation_fd, staging,
                            bindings, open_image, project_result,
                            max_image_bytes)
        os.fsync(indexes_fd)
        reservation_fd = _child_directory(indexes_fd, request["build_id"])
        descriptors.append(reservation_fd)
        bindings.append((reservation, _identity(reservation_fd)))
        builds_fd = _child_directory(cache_fd, builds_name, create=True)
        descriptors.append(builds_fd)
        try:
            os.mkdir(request["build_id"], mode=0o700, dir_fd=builds_fd)
        except FileExistsError as error:
            raise NavError("attempt_conflict", "Existing staging is never reused.") from error
        os.fsync(builds_fd)
        stage_fd = _child_directory(builds_fd, request["build_id"])
        descriptors.append(stage_fd)
        bindings.extend([(cache / builds_name, _identity(builds_fd)),
                         (staging, _identity(stage_fd))])
        image = make_image(request)
        if max_image_bytes is not None and len(image) > max_image_bytes:
            raise NavError("unsupported_capability", "Built image exceeds reader limit.")
        image_hash = sha(image)
        index = dict(path=str(reservation / (image_hash + ".sqlite")),
                     sha256=image_hash)
        with open_image(index, image) as generation:
            project_result(request, generation, [str(staging)])
        _check_directories(bindings)
        payload_fd = os.open("payload.sqlite",
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=stage_fd)
        try:
            payload_identity = _identity(payload_fd)
            view = memoryview(image)
            while view:
                written = os.write(payload_fd, view)
                if not written:
                    raise OSError("short payload write")
                view = view[written:]
            os.fsync(payload_fd)
        finally:
            os.close(payload_fd)
        os.fsync(stage_fd)
        _check_directories(bindings)
        if os.listdir(reservation_fd):
            raise NavError("attempt_conflict", "Reservation changed before publication.")
        # A link exception can arrive after creation. Once attempted, no error
        # may imply that publication did nothing; recovery inspects it.
        link_attempted = True
        os.link("payload.sqlite", image_hash + ".sqlite", src_dir_fd=stage_fd,
                dst_dir_fd=reservation_fd, follow_symlinks=False)
        os.fsync(reservation_fd)
        try:
            return _recover(request, reservation, reservation_fd, staging, bindings,
                            open_image, project_result, max_image_bytes,
                            expected_inode=payload_identity)
        except NavError as error:
            if error.code in ("attempt_incomplete", "attempt_conflict"):
                # These namespace shapes are conflicts during ordinary recovery.
                # After this call attempted a link, they cannot mean no effect.
                raise _ChangedNamespace from error
            raise
    except _ChangedNamespace as error:
        raise NavError("publication_unknown" if link_attempted else "attempt_conflict",
                       "Cache namespace changed; inspect the known reservation.",
                       build_id=request["build_id"], residue=residue(staging)) from error
    except NavError as error:
        error.details.update(build_id=request["build_id"], residue=residue(staging))
        raise
    except (OSError, sqlite3.Error, ValueError) as error:
        raise NavError("publication_unknown" if link_attempted else "io_error",
                       "Build failed; inspect its known reservation before retry.",
                       build_id=request["build_id"], residue=residue(staging)) from error
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
