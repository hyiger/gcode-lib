"""Tests for plain-text thumbnail parsing, rendering, and interchangeability
with binary .bgcode thumbnails."""

from __future__ import annotations

import base64
import struct
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gcode_lib as gl

# ---------------------------------------------------------------------------
# Minimal fake image bytes for each format (valid magic, arbitrary payload)
# ---------------------------------------------------------------------------

PNG_DATA = b"\x89PNG\r\n\x1a\n" + b"\x00" * 56   # 64 bytes
JPG_DATA = b"\xff\xd8\xff\xe0" + b"\x00" * 60    # 64 bytes
QOI_DATA = b"qoif" + b"\x00" * 60                # 64 bytes


def _thumb_block(keyword: str, width: int, height: int, data: bytes) -> str:
    """Build a plain-text thumbnail comment block."""
    b64 = base64.b64encode(data).decode("ascii")
    lines = [f"; {keyword} begin {width}x{height} {len(data)}"]
    for i in range(0, len(b64), 76):
        lines.append("; " + b64[i : i + 76])
    lines.append(f"; {keyword} end")
    lines.append("")
    return "\n".join(lines)


GCODE_BODY = "G28\nG90\nG1 X10 Y10 Z0.2 F3000\n"


# ---------------------------------------------------------------------------
# Parsing: _parse_text_thumbnails (via from_text)
# ---------------------------------------------------------------------------

class TestParseTextThumbnails:
    def test_single_png_extracted(self):
        text = _thumb_block("thumbnail", 16, 16, PNG_DATA) + GCODE_BODY
        gf = gl.from_text(text)
        assert len(gf.thumbnails) == 1
        t = gf.thumbnails[0]
        assert t.width == 16
        assert t.height == 16
        assert t.format_code == gl._IMG_PNG
        assert t.data == PNG_DATA

    def test_thumbnail_lines_removed_from_lines(self):
        text = _thumb_block("thumbnail", 8, 8, PNG_DATA) + GCODE_BODY
        gf = gl.from_text(text)
        # No thumbnail comment lines should remain
        for line in gf.lines:
            assert "thumbnail" not in line.raw.lower()
        # G-code lines are present
        assert any(line.command == "G28" for line in gf.lines)

    def test_jpg_keyword_sets_format_code(self):
        text = _thumb_block("thumbnail_JPG", 32, 32, JPG_DATA) + GCODE_BODY
        gf = gl.from_text(text)
        assert len(gf.thumbnails) == 1
        assert gf.thumbnails[0].format_code == gl._IMG_JPG

    def test_qoi_keyword_sets_format_code(self):
        text = _thumb_block("thumbnail_QOI", 32, 32, QOI_DATA) + GCODE_BODY
        gf = gl.from_text(text)
        assert len(gf.thumbnails) == 1
        assert gf.thumbnails[0].format_code == gl._IMG_QOI

    def test_plain_thumbnail_keyword_always_means_png(self):
        # "thumbnail" keyword is authoritative: always PNG regardless of payload
        text = _thumb_block("thumbnail", 16, 16, JPG_DATA) + GCODE_BODY
        gf = gl.from_text(text)
        assert gf.thumbnails[0].format_code == gl._IMG_PNG

    def test_format_inferred_from_magic_for_unknown_keyword(self):
        # Build a block with an unrecognised keyword; format falls back to magic
        raw_block = (
            f"; thumbnail_WEBP begin 16x16 {len(JPG_DATA)}\n"
            + "".join(
                "; " + base64.b64encode(JPG_DATA).decode("ascii")[i : i + 76] + "\n"
                for i in range(0, len(base64.b64encode(JPG_DATA)), 76)
            )
            + "; thumbnail_WEBP end\n\n"
        )
        text = raw_block + GCODE_BODY
        gf = gl.from_text(text)
        assert len(gf.thumbnails) == 1
        assert gf.thumbnails[0].format_code == gl._IMG_JPG

    def test_multiple_thumbnails(self):
        text = (
            _thumb_block("thumbnail", 16, 16, PNG_DATA)
            + _thumb_block("thumbnail_JPG", 32, 32, JPG_DATA)
            + GCODE_BODY
        )
        gf = gl.from_text(text)
        assert len(gf.thumbnails) == 2
        assert gf.thumbnails[0].width == 16
        assert gf.thumbnails[1].width == 32
        assert gf.thumbnails[0].format_code == gl._IMG_PNG
        assert gf.thumbnails[1].format_code == gl._IMG_JPG

    def test_no_thumbnail_gives_empty_list(self):
        gf = gl.from_text(GCODE_BODY)
        assert gf.thumbnails == []

    def test_thumbnail_png_keyword_alias(self):
        text = _thumb_block("thumbnail_PNG", 16, 16, PNG_DATA) + GCODE_BODY
        gf = gl.from_text(text)
        assert gf.thumbnails[0].format_code == gl._IMG_PNG

    def test_raw_block_is_empty_for_text_source(self):
        text = _thumb_block("thumbnail", 16, 16, PNG_DATA) + GCODE_BODY
        gf = gl.from_text(text)
        assert gf.thumbnails[0]._raw_block == b""


# ---------------------------------------------------------------------------
# Rendering: to_text re-emits thumbnail blocks
# ---------------------------------------------------------------------------

class TestRenderTextThumbnails:
    def test_thumbnails_emitted_at_top(self):
        text = _thumb_block("thumbnail", 16, 16, PNG_DATA) + GCODE_BODY
        gf = gl.from_text(text)
        out = gl.to_text(gf)
        assert out.index("thumbnail begin") < out.index("G28")

    def test_png_uses_thumbnail_keyword(self):
        text = _thumb_block("thumbnail", 16, 16, PNG_DATA) + GCODE_BODY
        gf = gl.from_text(text)
        out = gl.to_text(gf)
        assert "; thumbnail begin 16x16" in out
        assert "thumbnail_PNG" not in out  # canonical keyword is bare "thumbnail"

    def test_jpg_uses_thumbnail_jpg_keyword(self):
        text = _thumb_block("thumbnail_JPG", 32, 32, JPG_DATA) + GCODE_BODY
        gf = gl.from_text(text)
        out = gl.to_text(gf)
        assert "; thumbnail_JPG begin 32x32" in out

    def test_qoi_uses_thumbnail_qoi_keyword(self):
        text = _thumb_block("thumbnail_QOI", 32, 32, QOI_DATA) + GCODE_BODY
        gf = gl.from_text(text)
        out = gl.to_text(gf)
        assert "; thumbnail_QOI begin 32x32" in out

    def test_no_thumbnails_no_header(self):
        gf = gl.from_text(GCODE_BODY)
        out = gl.to_text(gf)
        assert "thumbnail" not in out

    def test_size_in_header_is_b64_char_count(self):
        # PrusaSlicer stores the base64 character count, not the raw byte count
        text = _thumb_block("thumbnail", 16, 16, PNG_DATA) + GCODE_BODY
        gf = gl.from_text(text)
        out = gl.to_text(gf)
        expected_size = len(base64.b64encode(PNG_DATA))
        assert f"; thumbnail begin 16x16 {expected_size}" in out


# ---------------------------------------------------------------------------
# Round-trip: text → parse → render → parse
# ---------------------------------------------------------------------------

class TestTextRoundTrip:
    def test_data_preserved(self):
        text = _thumb_block("thumbnail", 16, 16, PNG_DATA) + GCODE_BODY
        gf = gl.from_text(text)
        gf2 = gl.from_text(gl.to_text(gf))
        assert len(gf2.thumbnails) == 1
        assert gf2.thumbnails[0].data == PNG_DATA
        assert gf2.thumbnails[0].width == 16
        assert gf2.thumbnails[0].height == 16
        assert gf2.thumbnails[0].format_code == gl._IMG_PNG

    def test_multiple_thumbnails_round_trip(self):
        text = (
            _thumb_block("thumbnail", 16, 16, PNG_DATA)
            + _thumb_block("thumbnail_JPG", 32, 32, JPG_DATA)
            + GCODE_BODY
        )
        gf = gl.from_text(text)
        gf2 = gl.from_text(gl.to_text(gf))
        assert len(gf2.thumbnails) == 2
        assert gf2.thumbnails[0].data == PNG_DATA
        assert gf2.thumbnails[1].data == JPG_DATA

    def test_gcode_lines_unchanged_after_round_trip(self):
        text = _thumb_block("thumbnail", 16, 16, PNG_DATA) + GCODE_BODY
        gf = gl.from_text(text)
        gf2 = gl.from_text(gl.to_text(gf))
        cmds = [l.command for l in gf2.lines if l.command]
        assert cmds == ["G28", "G90", "G1"]

    def test_load_save_round_trip(self, tmp_path):
        text = _thumb_block("thumbnail", 16, 16, PNG_DATA) + GCODE_BODY
        src = tmp_path / "in.gcode"
        src.write_text(text, encoding="utf-8")

        gf = gl.load(str(src))
        assert len(gf.thumbnails) == 1
        assert gf.thumbnails[0].data == PNG_DATA

        dst = tmp_path / "out.gcode"
        gl.save(gf, str(dst))

        gf2 = gl.load(str(dst))
        assert len(gf2.thumbnails) == 1
        assert gf2.thumbnails[0].data == PNG_DATA
        assert gf2.thumbnails[0].width == 16


# ---------------------------------------------------------------------------
# Interchangeability: text and bgcode Thumbnail objects have the same API
# ---------------------------------------------------------------------------

class TestInterchangeability:
    def _make_bgcode_with_thumb(self, width: int, height: int, data: bytes) -> bytes:
        """Build a minimal .bgcode with a PNG thumbnail block."""
        MAGIC      = b"GCDE"
        BLK_GCODE  = 1
        BLK_THUMB  = 5
        COMP_NONE  = 0
        ENC_RAW    = 0
        IMG_PNG    = 0

        file_hdr = MAGIC + struct.pack("<IH", 1, 1)

        # Thumbnail block
        t_params  = struct.pack("<HHH", width, height, IMG_PNG)
        t_payload = data
        t_hdr     = struct.pack("<HHI", BLK_THUMB, COMP_NONE, len(t_payload))
        t_cksum   = zlib.crc32(t_hdr) & 0xFFFFFFFF
        t_cksum   = zlib.crc32(t_params, t_cksum) & 0xFFFFFFFF
        t_cksum   = zlib.crc32(t_payload, t_cksum) & 0xFFFFFFFF
        thumb_block = t_hdr + t_params + t_payload + struct.pack("<I", t_cksum)

        # GCode block
        payload  = GCODE_BODY.encode("utf-8")
        g_hdr    = struct.pack("<HHI", BLK_GCODE, COMP_NONE, len(payload))
        g_params = struct.pack("<H", ENC_RAW)
        g_cksum  = zlib.crc32(g_hdr) & 0xFFFFFFFF
        g_cksum  = zlib.crc32(g_params, g_cksum) & 0xFFFFFFFF
        g_cksum  = zlib.crc32(payload, g_cksum) & 0xFFFFFFFF
        gcode_block = g_hdr + g_params + payload + struct.pack("<I", g_cksum)

        return file_hdr + thumb_block + gcode_block

    def test_thumbnail_api_identical(self, tmp_path):
        """Text and bgcode thumbnails expose the same .width/.height/.format_code/.data."""
        # Text source
        text = _thumb_block("thumbnail", 16, 16, PNG_DATA) + GCODE_BODY
        gf_text = gl.from_text(text)
        t_text = gf_text.thumbnails[0]

        # Binary source
        bgcode = self._make_bgcode_with_thumb(16, 16, PNG_DATA)
        p = tmp_path / "test.bgcode"
        p.write_bytes(bgcode)
        gf_bin = gl.load(str(p))
        t_bin = gf_bin.thumbnails[0]

        assert t_text.width  == t_bin.width  == 16
        assert t_text.height == t_bin.height == 16
        assert t_text.format_code == t_bin.format_code == gl._IMG_PNG
        assert t_text.data == t_bin.data == PNG_DATA

    def test_thumbnails_populated_for_both_formats(self, tmp_path):
        """GCodeFile.thumbnails is never empty when the source has thumbnail data."""
        text = _thumb_block("thumbnail", 8, 8, PNG_DATA) + GCODE_BODY
        gf_text = gl.from_text(text)
        assert len(gf_text.thumbnails) == 1

        bgcode = self._make_bgcode_with_thumb(8, 8, PNG_DATA)
        p = tmp_path / "test.bgcode"
        p.write_bytes(bgcode)
        gf_bin = gl.load(str(p))
        assert len(gf_bin.thumbnails) == 1

    def test_thumbnail_lines_absent_from_gf_lines(self, tmp_path):
        """Neither format leaves thumbnail comment lines in gf.lines."""
        text = _thumb_block("thumbnail", 8, 8, PNG_DATA) + GCODE_BODY
        gf_text = gl.from_text(text)
        for line in gf_text.lines:
            assert "thumbnail" not in line.raw.lower()

        bgcode = self._make_bgcode_with_thumb(8, 8, PNG_DATA)
        p = tmp_path / "test.bgcode"
        p.write_bytes(bgcode)
        gf_bin = gl.load(str(p))
        for line in gf_bin.lines:
            assert "thumbnail" not in line.raw.lower()
