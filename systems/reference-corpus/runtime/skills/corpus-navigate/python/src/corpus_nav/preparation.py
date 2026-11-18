"""Explicit capability boundary for the optional preparation phase."""

from .response import NavError


def prepare(request: dict) -> dict:
    raise NavError("unsupported_capability",
                   "Optional preparation is unavailable in this source-only preview.")
