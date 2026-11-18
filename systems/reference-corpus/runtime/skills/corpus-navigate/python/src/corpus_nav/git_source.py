"""Local Git object reads; this is the only module that spawns Git."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
import subprocess

from .response import NavError


@dataclass(frozen=True)
class Entry:
    path: bytes
    mode: str
    kind: str
    oid: str
    size: int | None


def run(repository: str, *args: str) -> bytes:
    # Repository objects are inputs, but config cannot enable network recovery.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1",
               GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_ATTR_NOSYSTEM="1")
    command = ["git", "--no-replace-objects", "-c", "protocol.allow=never",
               "-c", "credential.interactive=false", "-c", "core.hooksPath=" + os.devnull,
               "-C", repository, *args]
    try:
        result = subprocess.run(command, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                check=False)
    except OSError as exc:
        raise NavError("unsupported_capability", "Git is unavailable.") from exc
    if result.returncode:
        raise NavError("source_missing", "Selected local Git objects unavailable.")
    return result.stdout


def check(repository: str) -> str:
    version = run(repository, "--version").decode("ascii", "replace").strip()
    match = re.search(r"(\d+)\.(\d+)", version)
    if match is None or tuple(map(int, match.groups())) < (2, 45):
        raise NavError("unsupported_capability", "Git >=2.45 is required for no-lazy-fetch.")
    run(repository, "rev-parse", "--git-dir")
    return version + "; replacement objects, lazy fetch and prompts disabled"


def snapshot(request: dict) -> tuple[dict, list[Entry]]:
    repository = request["repository"]
    check(repository)
    fmt = run(repository, "rev-parse", "--show-object-format").strip().decode("ascii")
    if fmt not in ("sha1", "sha256"):
        raise NavError("unsupported_capability", "Unknown Git object format.")
    commit = run(repository, "rev-parse", "--verify", "--end-of-options",
                 request["ref"] + "^{commit}").strip().decode("ascii")
    selected = commit if request["corpus_path"] == "." else commit + ":" + request["corpus_path"]
    tree = run(repository, "rev-parse", "--verify", "--end-of-options",
               selected + ("^{tree}" if request["corpus_path"] == "." else "")).strip().decode("ascii")
    if run(repository, "cat-file", "-t", tree).strip() != b"tree":
        raise NavError("unsupported_structure", "Corpus root is not a Git tree.")
    entries = []
    for line in run(repository, "ls-tree", "-rztl", "--full-tree", tree).split(b"\0"):
        if not line:
            continue
        facts, path = line.split(b"\t", 1)
        mode, kind, obj, size = facts.split()
        # ls-tree can succeed while reporting BAD for an absent blob. Treat
        # that as unavailable source, rather than letting int() escape the API.
        try:
            byte_count = None if size == b"-" else int(size)
        except ValueError as exc:
            raise NavError("source_missing", "Selected Git blob is missing.") from exc
        if byte_count is not None and byte_count < 0:
            raise NavError("source_missing", "Selected Git blob size is invalid.")
        entries.append(Entry(path, mode.decode("ascii"), kind.decode("ascii"),
                             obj.decode("ascii"), byte_count))
    return dict(corpus_id=request["corpus_id"], object_format=fmt, commit=commit,
                tree=tree, corpus_path=request["corpus_path"]), entries


def blob(repository: str, entry: Entry) -> bytes:
    data = run(repository, "cat-file", "blob", entry.oid)
    if len(data) != entry.size:
        raise NavError("source_missing", "Blob size disagrees with pinned tree.")
    return data
