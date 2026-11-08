"""Errors raised for bad opendrill input.

PayloadError is for a structured payload that failed validation.
InputError is for a file the reader could not use (missing, wrong type,
unreadable workbook, duplicate keys, formula with no cached value).
"""
from __future__ import annotations


class PayloadError(Exception):
    """Validation failed.

    ``errors`` is a list of ``(loc, message, value)`` tuples. ``loc`` is a
    path such as ``("layers", 2, "depth_end_m")`` or ``()`` for a check that
    applies to the whole log.
    """

    def __init__(self, errors: list[tuple[tuple, str, object]]):
        self.errors = errors
        super().__init__(
            "; ".join(
                f"{_format_loc(loc)}: {msg}" if loc else msg
                for loc, msg, _value in errors
            )
        )


class InputError(Exception):
    """The input file cannot be read. The message is safe to show as-is."""


def _format_loc(loc: tuple) -> str:
    return ".".join(str(part) for part in loc)
