"""YAML comments for a template, written after the thing they describe.

    from cfn_typed import note

    "Jobs": sqs.queue(VisibilityTimeout=60) @ note("Receives order events"),

`value @ note("text")` gives back `value`, a copy that remembers the text. `to_yaml` writes it as a `# text` line
above the key (or the list item) that holds the value; `to_json` and every check see an ordinary dict, list or string,
so nothing but the YAML changes. Several comments on one value are lines of one comment, and a list of strings is
one line each:

    queue @ note("Receives order events") @ note("Owner: orders")
    queue @ note(["Receives order events", "Owner: orders"])

Only values that can carry the text work: a dict, a list, a str, an int or a float. A bool or `None` cannot be
subclassed, so annotating one raises `TypeError`.
"""

from collections.abc import Sequence
from typing import Any

__all__ = ["Note", "comment_of", "note"]


class _Carrier:
    """Mixin for the value subclasses: the lines of the comment that goes above the value."""

    comment: tuple[str, ...] = ()


class _Dict(_Carrier, dict[str, Any]):
    pass


class _List(_Carrier, list[Any]):
    pass


class _Str(_Carrier, str):
    pass


class _Int(_Carrier, int):
    pass


class _Float(_Carrier, float):
    pass


# exact types only: a bool is an int, but `int(True)` would quietly lose it
_CARRIERS: dict[type, type] = {dict: _Dict, list: _List, str: _Str, int: _Int, float: _Float}


class Note:
    """What `note()` returns. `value @ note(...)` is the one thing it does."""

    __slots__ = ("lines",)

    def __init__(self, lines: tuple[str, ...]) -> None:
        self.lines = lines

    def __rmatmul__[T](self, value: T) -> T:
        base = type(value)
        carrier = base if issubclass(base, _Carrier) else _CARRIERS.get(base)
        if carrier is None:
            raise TypeError(f"cannot attach a comment to a {base.__name__}; it works on a dict, list, str, int or float")
        out: Any = carrier(value)  # a copy: the original stays as it was
        out.comment = (*getattr(value, "comment", ()), *self.lines)
        return out

    def __repr__(self) -> str:
        return f"note({'/'.join(self.lines)!r})"


def note(text: str | Sequence[str]) -> Note:
    """The comment for `value @ note("text")`. A string with newlines, or a list of strings, is several lines."""
    parts = [text] if isinstance(text, str) else list(text)
    lines = tuple(line.rstrip() for part in parts for line in part.split("\n"))
    return Note(lines)


def comment_of(value: object) -> tuple[str, ...]:
    """The lines a value carries, or an empty tuple. What the YAML renderer asks."""
    return value.comment if isinstance(value, _Carrier) else ()
