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

    def test_invalid_thumbnail_block_is_preserved(self):
        text = (
            "; thumbnail begin 16x16 12\n"
            "; not_base64$$\n"
            "; thumbnail end\n"
            "G1 X10 Y10\n"
        )
        gf = gl.from_text(text)
        assert gf.thumbnails == []
        assert [ln.raw for ln in gf.lines] == [
            "; thumbnail begin 16x16 12",
            "; not_base64$$",
            "; thumbnail end",
            "G1 X10 Y10",
        ]

    def test_thumbnail_begin_without_end_does_not_consume_lines(self):
        text = (
            "G90\n"
            "; thumbnail begin 16x16 12\n"
            "; not_base64$$\n"
            "G1 X10 Y10\n"
        )
        gf = gl.from_text(text)
        assert gf.thumbnails == []
        assert [ln.raw for ln in gf.lines] == [
            "G90",
            "; thumbnail begin 16x16 12",
            "; not_base64$$",
            "G1 X10 Y10",
        ]

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
        t_params  = struct.pack("<HHH", IMG_PNG, width, height)
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


# ---------------------------------------------------------------------------
# §13 — STL thumbnail rendering & injection
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock, patch
import warnings as _warnings_mod


class TestThumbnailSpec:
    def test_dataclass_fields(self):
        spec = gl.ThumbnailSpec(width=16, height=16)
        assert spec.width == 16
        assert spec.height == 16


class TestParseThumbnailSpecs:
    def test_two_specs(self):
        result = gl.parse_thumbnail_specs("16x16/PNG,220x124/PNG")
        assert len(result) == 2
        assert result[0].width == 16
        assert result[0].height == 16
        assert result[1].width == 220
        assert result[1].height == 124

    def test_empty_string(self):
        assert gl.parse_thumbnail_specs("") == []

    def test_whitespace_only(self):
        assert gl.parse_thumbnail_specs("  ") == []

    def test_no_format_suffix(self):
        result = gl.parse_thumbnail_specs("16x16")
        assert len(result) == 1
        assert result[0].width == 16
        assert result[0].height == 16

    def test_invalid_spec_warns_and_returns_empty(self):
        with _warnings_mod.catch_warnings(record=True) as w:
            _warnings_mod.simplefilter("always")
            result = gl.parse_thumbnail_specs("abc")
            assert result == []
            assert len(w) == 1
            assert "invalid thumbnail spec" in str(w[0].message).lower()

    def test_non_positive_dimensions_warn_and_are_skipped(self):
        with _warnings_mod.catch_warnings(record=True) as w:
            _warnings_mod.simplefilter("always")
            result = gl.parse_thumbnail_specs("0x16,-8x32,16x0,32x32")
            assert len(result) == 1
            assert result[0].width == 32
            assert result[0].height == 32
            assert len(w) == 3


class TestFallbackPng:
    def test_returns_png_magic(self):
        data = gl._fallback_png(16, 16)
        assert data[:4] == b"\x89PNG"

    def test_returns_bytes(self):
        data = gl._fallback_png(16, 16)
        assert isinstance(data, bytes)

    def test_zero_dimensions_clamped(self):
        # width=0, height=0 → clamped to 1x1
        data = gl._fallback_png(0, 0)
        assert data[:4] == b"\x89PNG"
        assert len(data) > 8


class TestBuildThumbnailBlock:
    def test_returns_bytes(self):
        block = gl.build_thumbnail_block(PNG_DATA, 16, 16)
        assert isinstance(block, bytes)

    def test_first_two_bytes_are_block_type_5(self):
        block = gl.build_thumbnail_block(PNG_DATA, 16, 16)
        btype = struct.unpack_from("<H", block, 0)[0]
        assert btype == 5

    def test_contains_png_data(self):
        block = gl.build_thumbnail_block(PNG_DATA, 16, 16)
        assert PNG_DATA in block

    def test_params_order_format_width_height(self):
        """build_thumbnail_block must write params as (format, width, height)
        matching the libbgcode spec so that firmware can decode them."""
        block = gl.build_thumbnail_block(PNG_DATA, 220, 124)
        # params start at offset 8 (after 8-byte header)
        fmt, w, h = struct.unpack_from("<HHH", block, 8)
        assert fmt == gl._IMG_PNG
        assert w == 220
        assert h == 124

    def test_round_trip_via_read_bgcode(self):
        """Thumbnail built by build_thumbnail_block should round-trip through
        read_bgcode with correct width, height, and format_code."""
        thumb_block = gl.build_thumbnail_block(PNG_DATA, 64, 48)

        # Build a minimal bgcode with this thumbnail + a gcode block
        MAGIC = b"GCDE"
        file_hdr = MAGIC + struct.pack("<IH", 1, 1)
        payload = GCODE_BODY.encode("utf-8")
        g_hdr = struct.pack("<HHI", 1, 0, len(payload))
        g_params = struct.pack("<H", 0)
        g_cksum = zlib.crc32(g_hdr) & 0xFFFFFFFF
        g_cksum = zlib.crc32(g_params, g_cksum) & 0xFFFFFFFF
        g_cksum = zlib.crc32(payload, g_cksum) & 0xFFFFFFFF
        gcode_block = g_hdr + g_params + payload + struct.pack("<I", g_cksum)

        raw = file_hdr + thumb_block + gcode_block
        gf = gl.read_bgcode(raw)
        assert len(gf.thumbnails) == 1
        t = gf.thumbnails[0]
        assert t.width == 64
        assert t.height == 48
        assert t.format_code == gl._IMG_PNG
        assert t.data == PNG_DATA


class TestFindThumbnailInsertPos:
    def test_empty_list(self):
        assert gl._find_thumbnail_insert_pos([]) == 0

    def test_after_file_metadata_block(self):
        # Block type 0 = FILE_METADATA
        blk0 = struct.pack("<HHI", 0, 0, 0) + struct.pack("<I", 0)
        assert gl._find_thumbnail_insert_pos([blk0]) == 1

    def test_after_printer_metadata_block(self):
        # Block type 3 = PRINTER_METADATA
        blk3 = struct.pack("<HHI", 3, 0, 0) + struct.pack("<I", 0)
        assert gl._find_thumbnail_insert_pos([blk3]) == 1

    def test_before_other_block_types(self):
        # Block type 1 = GCODE, 2 = SLICER_METADATA
        blk1 = struct.pack("<HHI", 1, 0, 0) + struct.pack("<I", 0)
        blk2 = struct.pack("<HHI", 2, 0, 0) + struct.pack("<I", 0)
        assert gl._find_thumbnail_insert_pos([blk1, blk2]) == 0

    def test_mixed_blocks(self):
        # FILE_METADATA at index 0, GCODE at index 1
        blk0 = struct.pack("<HHI", 0, 0, 0) + struct.pack("<I", 0)
        blk1 = struct.pack("<HHI", 1, 0, 0) + struct.pack("<I", 0)
        assert gl._find_thumbnail_insert_pos([blk0, blk1]) == 1


class TestFindSlicerMetaIndex:
    def test_empty_list(self):
        assert gl._find_slicer_meta_index([]) is None

    def test_finds_slicer_metadata(self):
        # Block type 2 = SLICER_METADATA
        blk = struct.pack("<HHI", 2, 0, 0) + struct.pack("<I", 0)
        assert gl._find_slicer_meta_index([blk]) == 0

    def test_no_slicer_metadata(self):
        blk = struct.pack("<HHI", 1, 0, 0) + struct.pack("<I", 0)
        assert gl._find_slicer_meta_index([blk]) is None

    def test_multiple_blocks_returns_first(self):
        blk0 = struct.pack("<HHI", 0, 0, 0) + struct.pack("<I", 0)
        blk2 = struct.pack("<HHI", 2, 0, 0) + struct.pack("<I", 0)
        assert gl._find_slicer_meta_index([blk0, blk2]) == 1


class TestInjectThumbnails:
    def test_does_nothing_for_ascii_gcode(self):
        gf = gl.from_text(GCODE_BODY)
        assert gf.source_format == "text"
        # Should not raise, just return silently
        gl.inject_thumbnails(gf, "/fake/path.stl", "16x16/PNG")
        assert gf.thumbnails == []

    def test_does_nothing_if_thumbnails_already_present(self):
        # Create a text gcode with an existing thumbnail
        text = _thumb_block("thumbnail", 16, 16, PNG_DATA) + GCODE_BODY
        gf = gl.from_text(text)
        assert len(gf.thumbnails) == 1
        # Force source_format to bgcode to test the short-circuit
        gf.source_format = "bgcode"
        original_count = len(gf.thumbnails)
        gl.inject_thumbnails(gf, "/fake/path.stl", "16x16/PNG")
        assert len(gf.thumbnails) == original_count

    @patch("gcode_lib.render_stl_to_png")
    def test_injects_thumbnail_for_bgcode(self, mock_render):
        mock_render.return_value = PNG_DATA
        # Build a minimal bgcode GCodeFile
        gf = gl.GCodeFile(
            lines=[],
            thumbnails=[],
            source_format="bgcode",
            _bgcode_nongcode_blocks=[],
        )
        gl.inject_thumbnails(gf, "/fake/model.stl", "16x16/PNG")
        assert len(gf.thumbnails) == 1
        assert gf.thumbnails[0].width == 16
        assert gf.thumbnails[0].height == 16
        assert gf.thumbnails[0].data == PNG_DATA
        mock_render.assert_called_once_with("/fake/model.stl", 16, 16)


class TestPatchSlicerMetadata:
    def test_does_nothing_for_ascii_gcode(self):
        gf = gl.from_text(GCODE_BODY)
        # Should not raise
        gl.patch_slicer_metadata(gf, "COREONE", 0.4)

    def test_returns_silently_for_unknown_combo(self):
        gf = gl.GCodeFile(
            lines=[],
            thumbnails=[],
            source_format="bgcode",
            _bgcode_nongcode_blocks=[],
        )
        # "UNKNOWN" printer is not in _PRINTER_SETTINGS_IDS
        gl.patch_slicer_metadata(gf, "UNKNOWN", 0.4)

    def test_patches_printer_model(self):
        """patch_slicer_metadata sets both printer_settings_id and printer_model."""
        # Build a minimal SLICER_METADATA block (block type 2, uncompressed)
        payload = b"printer_settings_id=\nprinter_model=\n"
        hdr = struct.pack("<HHI", 2, 0, len(payload))
        params = b"\x00\x00"
        block = hdr + params + payload
        crc = struct.pack("<I", zlib.crc32(block) & 0xFFFFFFFF)
        block = block + crc

        gf = gl.GCodeFile(
            lines=[],
            thumbnails=[],
            source_format="bgcode",
            _bgcode_nongcode_blocks=[block],
        )
        gl.patch_slicer_metadata(gf, "COREONE", 0.4)

        # Decode the patched block
        patched = gf._bgcode_nongcode_blocks[0]
        _, _, usize = struct.unpack_from("<HHI", patched, 0)
        text = patched[10:10 + usize].decode("utf-8")
        assert "printer_settings_id=Prusa CORE One HF0.4 nozzle" in text
        assert "printer_model=COREONE" in text


class TestNeedsSubprocessRender:
    @patch("gcode_lib.platform")
    def test_darwin_returns_true(self, mock_platform):
        mock_platform.system.return_value = "Darwin"
        assert gl._needs_subprocess_render() is True

    @patch("gcode_lib.platform")
    def test_linux_returns_false(self, mock_platform):
        mock_platform.system.return_value = "Linux"
        assert gl._needs_subprocess_render() is False


class TestRebuildSlicerMetaBlock:
    def _build_slicer_meta_block(self, text: str, comp: int = 0) -> bytes:
        """Build a minimal SLICER_METADATA block for testing."""
        payload = text.encode("utf-8")
        params = struct.pack("<H", 0)  # 2-byte encoding param

        if comp == 0:
            # Uncompressed
            hdr = struct.pack("<HHI", 2, 0, len(payload))
            block_body = hdr + params + payload
        elif comp == 1:
            # Deflate compressed
            compressed = zlib.compress(payload)
            hdr = struct.pack("<HHI", 2, 1, len(payload))
            cs_bytes = struct.pack("<I", len(compressed))
            block_body = hdr + cs_bytes + params + compressed
        else:
            raise ValueError(f"Unsupported comp: {comp}")

        crc = struct.pack("<I", zlib.crc32(block_body) & 0xFFFFFFFF)
        return block_body + crc

    def test_uncompressed_update(self):
        raw = self._build_slicer_meta_block(
            "printer_settings_id=\nother_key=value\n",
            comp=0,
        )
        updated = gl._rebuild_slicer_meta_block(
            raw, {"printer_settings_id": "Prusa CORE One HF0.4 nozzle"},
        )
        # Decode the updated block to verify the key was changed
        btype, comp, usize = struct.unpack_from("<HHI", updated, 0)
        assert btype == 2
        assert comp == 0
        params = updated[8:10]
        payload = updated[10:10 + usize]
        text = payload.decode("utf-8")
        assert "printer_settings_id=Prusa CORE One HF0.4 nozzle" in text
        assert "other_key=value" in text

    def test_deflate_round_trip(self):
        raw = self._build_slicer_meta_block(
            "printer_settings_id=\nsome_key=foo\n",
            comp=1,
        )
        updated = gl._rebuild_slicer_meta_block(
            raw, {"printer_settings_id": "Prusa CORE One HF0.6 nozzle"},
        )
        # Verify block is deflate compressed
        btype, comp, usize = struct.unpack_from("<HHI", updated, 0)
        assert btype == 2
        assert comp == 1
        # Decompress and verify content
        cs = struct.unpack_from("<I", updated, 8)[0]
        params = updated[12:14]
        compressed = updated[14:14 + cs]
        payload = zlib.decompress(compressed)
        text = payload.decode("utf-8")
        assert "printer_settings_id=Prusa CORE One HF0.6 nozzle" in text
        assert "some_key=foo" in text
