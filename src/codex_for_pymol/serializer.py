"""Bounded conversion of tool results to JSON-safe values."""

from itertools import islice
import math
from pathlib import Path


def to_jsonable(value, depth=0, max_depth=6, max_items=2000, max_string=20000):
    """Convert a value without invoking arbitrary ``repr`` implementations."""
    if depth > max_depth:
        return {"_truncated": "maximum depth reached"}
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return {"_nonfinite_float": str(value)}
    if isinstance(value, str):
        if len(value) <= max_string:
            return value
        return value[:max_string] + "…"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        result = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                result["_truncated"] = "maximum items reached"
                break
            result[str(key)[:200]] = to_jsonable(
                item, depth + 1, max_depth, max_items, max_string
            )
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(islice(iter(value), max_items + 1))
        truncated = len(items) > max_items
        result = [
            to_jsonable(item, depth + 1, max_depth, max_items, max_string)
            for item in items[:max_items]
        ]
        if truncated:
            try:
                omitted = max(1, len(value) - max_items)
            except TypeError:
                omitted = "additional items"
            result.append({"_truncated": omitted})
        return result

    # Common array-like values can be converted without calling repr.
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return to_jsonable(tolist(), depth + 1, max_depth, max_items, max_string)
        except Exception:
            pass

    return {
        "_type": "{}.{}".format(type(value).__module__, type(value).__name__),
        "_unserialized": True,
    }
