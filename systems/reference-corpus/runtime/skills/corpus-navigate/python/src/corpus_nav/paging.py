"""Bounded item-page assembly with caller-owned wire envelopes."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .response import NavError, canonical


def paginate_items(
    items: Sequence[dict],
    *,
    offset: int,
    limit: int,
    partial: bool,
    max_bytes: int,
    continuation_for: Callable[[int], str],
    fit_page: Callable[[list[dict], dict], dict | None],
) -> dict:
    """Return the largest fitting prefix, or raise ``budget_too_small``.

    The caller validates the request and its continuation position, including
    ``0 <= offset <= len(items)`` and ``1 <= limit <= 100``. It also owns the
    cursor binding and the full wire envelope: ``continuation_for`` receives
    the absolute next item index, and ``fit_page`` returns the caller's result
    only when the full envelope, including its newline, fits ``max_bytes``.
    The callback must preserve the items as a canonical JSON array and must
    not mutate the item records. Each call receives a fresh list and page.

    Partial sequences have a unit-budget reason and cannot be continued. An
    empty suffix still requires a fitting terminal envelope.
    """
    if offset == len(items):
        page = (dict(kind="partial", reasons=["unit_budget"])
                if partial else dict(kind="complete"))
        result = fit_page([], page)
        if result is None:
            raise NavError("budget_too_small")
        return result

    proposed = []
    best = None
    item_bytes = 2
    stop = min(len(items), offset + limit)
    for ordinal in range(offset, stop):
        item = items[ordinal]
        item_bytes += len(canonical(item)) + (1 if proposed else 0)
        # Bare array bytes only grow. Cursor envelopes can shrink between
        # prefixes, so an earlier failed fit cannot justify stopping here.
        if item_bytes > max_bytes:
            break
        proposed.append(item)
        more = ordinal + 1 < len(items)
        reason = "page_limit" if len(proposed) == limit else "output_budget"
        if partial:
            reasons = ["unit_budget"] + ([reason] if more else [])
            page = dict(kind="partial", reasons=reasons)
        elif more:
            page = dict(kind="more", reason=reason,
                        continuation=continuation_for(ordinal + 1))
        else:
            page = dict(kind="complete")
        result = fit_page(list(proposed), page)
        if result is not None:
            best = result
    if best is None:
        raise NavError("budget_too_small", "No complete useful item fits.")
    return best
