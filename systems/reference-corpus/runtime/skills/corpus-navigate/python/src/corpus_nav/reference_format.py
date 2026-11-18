"""Trusted native validation and original-byte Markdown ranges."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from markdown_it import MarkdownIt

from ._vendor import reference
from .response import NavError, SECTIONS, strict_json


@dataclass(frozen=True)
class Section:
    name: str
    start: int
    end: int


def utf8(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeError as exc:
        raise NavError("invalid_report", "Required source is not UTF-8.") from exc


def metadata(data: bytes, path: bytes) -> dict:
    try:
        value = strict_json(data)
    except NavError as exc:
        raise NavError("invalid_report", "Invalid report JSON.") from exc
    problems = reference._validate_metadata(value, Path(path.decode("ascii")))
    if problems:
        raise NavError("invalid_report", problems[0].message)
    return value


def prose(data: bytes, path: bytes) -> tuple[str, list[Section], list[tuple[int, int]]]:
    text = utf8(data)
    problems = reference._validate_prose(text, Path(path.decode("ascii")))
    if problems:
        raise NavError("invalid_report", problems[0].message)
    lines = data.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    # Extraction uses block maps and raw heading content, never rendered inline
    # children. Keep normalization and block parsing; omit the unused child tree.
    tokens = MarkdownIt("commonmark").disable("inline").parse(text)
    headings = []
    blocks = []
    title = None
    for i, token in enumerate(tokens):
        if token.level == 0 and token.map:
            a, b = token.map
            blocks.append((starts[a], starts[b]))
        if token.type != "heading_open" or token.level != 0 or not token.map:
            continue
        content = tokens[i + 1].content
        if token.tag == "h1":
            title = content
        elif token.tag == "h2":
            headings.append((content, starts[token.map[0]]))
    # Native validation remains authoritative. A parser disagreement is an
    # extraction limitation, never a reason to silently alter that contract.
    if title is None or [name for name, _ in headings] != list(SECTIONS):
        raise NavError("unsupported_structure", "Cannot map native sections safely.")
    sections = [Section(name, start, headings[i + 1][1] if i + 1 < len(headings)
                        else len(data)) for i, (name, start) in enumerate(headings)]
    return title, sections, sorted(set(blocks))


def fragments(data: bytes, start: int, end: int, maximum: int):
    cursor = start
    while cursor < end:
        stop = min(end, cursor + maximum)
        while stop > cursor:
            try:
                data[cursor:stop].decode("utf-8")
                break
            except UnicodeDecodeError:
                stop -= 1
        if stop == cursor:
            # A tiny unit setting cannot split one Unicode scalar.
            stop = cursor + 1
            while stop < end and data[stop] & 0xC0 == 0x80:
                stop += 1
        yield cursor, stop
        cursor = stop


def boundary(data: bytes, offset: int) -> bool:
    return 0 <= offset <= len(data) and (offset == len(data) or data[offset] & 0xC0 != 0x80)


def units(data: bytes, blocks: list[tuple[int, int]], maximum: int):
    # Block maps come from the parser; gaps still belong to captured source.
    cursor = 0
    for _, end in blocks:
        if end <= cursor:
            continue
        for a, b in fragments(data, cursor, end, maximum):
            yield a, b, b - a < end - cursor
        cursor = end
    if cursor < len(data):
        yield from ((a, b, True) for a, b in fragments(data, cursor, len(data), maximum))
