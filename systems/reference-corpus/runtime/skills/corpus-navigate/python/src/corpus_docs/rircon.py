"""Trusted native path and Markdown interpretation, without source effects."""

from __future__ import annotations

from dataclasses import dataclass
import re

from markdown_it import MarkdownIt

from corpus_nav.reference_format import boundary, fragments

from .wire import CONTEXT_PATHS, NavError

FOCUSED = frozenset(
    (
        b"docs/netstack3/architecture.md",
        b"docs/netstack3/architectural-decisions.md",
        b"docs/netstack3/state-synchronization.md",
    )
)
REFERENCE = b"docs/zircon/architecture-evolution.md"
CONTEXT = frozenset(path.encode("ascii") for path in CONTEXT_PATHS)


def document_kind(path):
    if re.fullmatch(rb"docs/prior-art/[^/]+/README\.md", path):
        return "comprehensive", path.rsplit(b"/", 1)[0]
    if path in FOCUSED:
        return "focused", b"docs/netstack3"
    if path == REFERENCE:
        return "reference", b"docs/zircon"
    return None


def context_paths(kind):
    # Related context does not grant authoring authority outside its native scope.
    return (
        tuple(sorted(CONTEXT))
        if kind == "comprehensive"
        else (b"docs/README.md",)
    )


def utf8(data):
    try:
        return data.decode("utf-8")
    except UnicodeError as error:
        raise NavError(
            "invalid_source", "Required native source is not UTF-8."
        ) from error


@dataclass(frozen=True)
class Heading:
    ordinal: int
    level: int
    label: str
    start: int
    end: int


def headings(data):
    text = utf8(data)
    # CommonMark normalizes CRLF and CR before tokenization. Its line numbers
    # still select the corresponding original byte lines, including their EOLs.
    starts = [0] + [m.end() for m in re.finditer(rb"\r\n|\r|\n", data)]
    if starts[-1] != len(data):
        starts.append(len(data))
    tokens = MarkdownIt("commonmark").disable("inline").parse(text)
    found = []
    title = None
    for i, token in enumerate(tokens):
        if token.type != "heading_open" or token.map is None:
            continue
        level = int(token.tag[1:])
        label = tokens[i + 1].content
        start = starts[token.map[0]]
        found.append((level, label, start))
        if title is None and level == 1 and token.level == 0:
            title = label
    result = []
    for ordinal, (level, label, start) in enumerate(found):
        end = next(
            (
                other_start
                for other_level, _, other_start in found[ordinal + 1 :]
                if other_level <= level
            ),
            len(data),
        )
        result.append(Heading(ordinal, level, label, start, end))
    return title, result


def unit_ranges(data, maximum):
    yield from fragments(data, 0, len(data), maximum)
