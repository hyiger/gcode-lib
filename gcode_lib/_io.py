"""Text I/O, thumbnail comment helpers, and template rendering."""

from __future__ import annotations

import base64
import os
import re
import struct
import tempfile
from typing import Dict, List, Tuple

from gcode_lib._constants import (
    _BGCODE_MAGIC,
    _IMG_MAGIC,
    _IMG_PNG,
    _THUMB_B64_LINE_LEN,
    _THUMB_BEGIN_RE,
    _THUMB_END_RE,
    _THUMB_FMT_KEYWORD,
    _THUMB_KEYWORD_FMT,
)
from gcode_lib._types import GCodeFile, GCodeLine, Thumbnail
from gcode_lib._parsing import parse_lines
from gcode_lib._bgcode import _bgcode_reassemble, _is_bgcode_file, _load_bgcode


# ---------------------------------------------------------------------------
# Plain-text thumbnail helpers (private)
# ---------------------------------------------------------------------------

def _parse_text_thumbnails(
    lines: List[GCodeLine],
) -> Tuple[List[GCodeLine], List[Thumbnail]]:
    """Extract thumbnail comment blocks from plain-text G-code lines."""
    result: List[GCodeLine] = []
    thumbnails: List[Thumbnail] = []
    i = 0
    while i < len(lines):
        m = _THUMB_BEGIN_RE.match(lines[i].raw)
        if not m:
            result.append(lines[i])
            i += 1
            continue

        keyword, w_str, h_str = m.group(1), m.group(2), m.group(3)
        width, height = int(w_str), int(h_str)

        b64_parts: List[str] = []
        i += 1
        while i < len(lines):
            raw = lines[i].raw
            if _THUMB_END_RE.match(raw):
                i += 1
                break
            if raw.startswith("; "):
                b64_parts.append(raw[2:])
            elif raw.startswith(";"):
                b64_parts.append(raw[1:])
            else:
                b64_parts.append(raw)
            i += 1

        try:
            img_data = base64.b64decode("".join(b64_parts))
        except Exception:
            continue

        fmt_code = _THUMB_KEYWORD_FMT.get(keyword.lower(), -1)
        if fmt_code == -1:
            fmt_code = _IMG_PNG
            for magic, code in _IMG_MAGIC:
                if img_data[: len(magic)] == magic:
                    fmt_code = code
                    break

        params = struct.pack("<HHH", width, height, fmt_code)
        thumbnails.append(Thumbnail(params=params, data=img_data, _raw_block=b""))

    return result, thumbnails


def _render_text_thumbnails(thumbnails: List[Thumbnail]) -> str:
    """Render *thumbnails* as plain-text G-code comment blocks."""
    parts: List[str] = []
    for thumb in thumbnails:
        keyword = _THUMB_FMT_KEYWORD.get(thumb.format_code, "thumbnail")
        b64 = base64.b64encode(thumb.data).decode("ascii")
        parts.append(
            f"; {keyword} begin {thumb.width}x{thumb.height} {len(b64)}"
        )
        for off in range(0, len(b64), _THUMB_B64_LINE_LEN):
            parts.append("; " + b64[off : off + _THUMB_B64_LINE_LEN])
        parts.append(f"; {keyword} end")
        parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def from_text(text: str) -> GCodeFile:
    """Create a :class:`GCodeFile` from a G-code text string."""
    lines, thumbnails = _parse_text_thumbnails(parse_lines(text))
    return GCodeFile(lines=lines, thumbnails=thumbnails, source_format="text")


def to_text(gf: GCodeFile) -> str:
    """Render a :class:`GCodeFile` back to a G-code text string."""
    gcode = "\n".join(line.raw for line in gf.lines) + "\n"
    if not gf.thumbnails:
        return gcode
    return _render_text_thumbnails(gf.thumbnails) + "\n" + gcode


def load(path: str) -> GCodeFile:
    """Load a G-code file from *path*, auto-detecting text vs binary format."""
    if _is_bgcode_file(path):
        with open(path, "rb") as fh:
            return _load_bgcode(fh.read())
    with open(path, "rb") as fh:
        head = fh.read(512)
    if b"\x00" in head:
        raise ValueError(
            f"{path!r} appears to be binary but is not a valid .bgcode file "
            "(expected 'GCDE' magic).  Supported formats: text .gcode and Prusa .bgcode."
        )
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    lines, thumbnails = _parse_text_thumbnails(parse_lines(text))
    return GCodeFile(lines=lines, thumbnails=thumbnails, source_format="text")


def save(gf: GCodeFile, path: str) -> None:
    """Atomically write *gf* to *path*, preserving the original file format."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    text = to_text(gf)
    if gf.source_format == "bgcode" and gf._bgcode_file_hdr is not None:
        data = _bgcode_reassemble(
            gf._bgcode_file_hdr,
            gf._bgcode_nongcode_blocks or [],
            text,
        )
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    else:
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# §7 — Thumbnail comment block (public API)
# ---------------------------------------------------------------------------

def encode_thumbnail_comment_block(
    width: int,
    height: int,
    png_bytes: bytes,
) -> str:
    """Encode a PNG image as a PrusaSlicer-compatible thumbnail comment block."""
    params = struct.pack("<HHH", width, height, _IMG_PNG)
    thumb = Thumbnail(params=params, data=png_bytes, _raw_block=b"")
    return _render_text_thumbnails([thumb])


# ---------------------------------------------------------------------------
# §6 — Template rendering
# ---------------------------------------------------------------------------

_TEMPLATE_VAR_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def render_template(template_text: str, variables: Dict[str, object]) -> str:
    """Substitute ``{key}`` placeholders in *template_text* from *variables*."""
    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        key = m.group(1)
        if key in variables:
            return str(variables[key])
        return m.group(0)

    return _TEMPLATE_VAR_RE.sub(_replace, template_text)
