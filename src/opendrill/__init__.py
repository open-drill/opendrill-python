"""Soil and borehole log PDF generator.

Depths are metres. Strength values are kilopascals. Percent fields are
literal percent. SPT N is ``spt2 + spt3`` (the template's 6-inch blow
counts) and is not N60. Hatches are drawing categories, not a
classification system.

Importing this package does not import the PDF or Excel libraries. Those
load when you render or read a workbook.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from opendrill.errors import InputError, PayloadError
from opendrill.synthetic import SYNTHETIC_PAYLOAD, synthetic_payload
from opendrill.validate import (
    SOIL_TYPES,
    SU_KINDS,
    TEST_TYPES,
    Validation,
    validate_log,
    validate_payload,
)

try:
    __version__ = version("opendrill")
except PackageNotFoundError:
    __version__ = "0.1.2"

__all__ = [
    "InputError",
    "PayloadError",
    "SOIL_TYPES",
    "SU_KINDS",
    "SYNTHETIC_PAYLOAD",
    "TEST_TYPES",
    "Validation",
    "__version__",
    "build_pdf",
    "render_log",
    "synthetic_payload",
    "validate_log",
    "validate_payload",
]


def build_pdf(payload: dict, text_scale: float | None = None) -> bytes:
    """Render a payload to PDF bytes."""
    from opendrill.render import build_pdf as _build_pdf

    return _build_pdf(payload, text_scale=text_scale)


def render_log(payload: dict, text_scale: float | None = None):
    """Render a payload and return PDF bytes, warnings, and page count."""
    from opendrill.render import render_log as _render_log

    return _render_log(payload, text_scale=text_scale)
