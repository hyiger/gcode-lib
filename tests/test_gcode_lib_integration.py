"""Integration tests against real sliced files.

Requires the two Benchy files to be present at the paths below.  Tests are
automatically skipped when the files are absent so the CI suite still passes
without them.
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gcode_lib as gl

# ---------------------------------------------------------------------------
# Paths to real files (skip all tests gracefully if absent)
# ---------------------------------------------------------------------------

GCODE_PATH  = "tests/3DBenchy_0.6n_0.32mm_FLEX_COREONE_32m.gcode"
BGCODE_PATH = "tests/3DBenchy_0.6n_0.32mm_FLEX_COREONE_32m.bgcode"

needs_gcode  = pytest.mark.skipif(not os.path.exists(GCODE_PATH),  reason="real .gcode file not present")
needs_bgcode = pytest.mark.skipif(not os.path.exists(BGCODE_PATH), reason="real .bgcode file not present")


# ---------------------------------------------------------------------------
# Plain-text .gcode — thumbnail extraction
# ---------------------------------------------------------------------------

class TestRealGcode:
    @needs_gcode
    def test_load_succeeds(self):
        gf = gl.load(GCODE_PATH)
        assert gf.source_format == "text"
        assert len(gf.lines) > 0

    @needs_gcode
    def test_four_thumbnails_extracted(self):
        gf = gl.load(GCODE_PATH)
        assert len(gf.thumbnails) == 4

    @needs_gcode
    def test_thumbnail_dimensions(self):
        gf = gl.load(GCODE_PATH)
        dims = {(t.width, t.height) for t in gf.thumbnails}
        assert (16, 16)   in dims
        assert (313, 173) in dims
        assert (480, 240) in dims
        assert (380, 285) in dims

    @needs_gcode
    def test_thumbnail_formats(self):
        gf = gl.load(GCODE_PATH)
        fmt_counts = {}
        for t in gf.thumbnails:
            fmt_counts[t.format_code] = fmt_counts.get(t.format_code, 0) + 1
        # File has 3 QOI and 1 PNG thumbnail
        assert fmt_counts.get(gl._IMG_QOI, 0) == 3
        assert fmt_counts.get(gl._IMG_PNG, 0) == 1

    @needs_gcode
    def test_thumbnail_data_non_empty(self):
        gf = gl.load(GCODE_PATH)
        for t in gf.thumbnails:
            assert len(t.data) > 0

    @needs_gcode
    def test_thumbnail_data_has_correct_magic(self):
        gf = gl.load(GCODE_PATH)
        for t in gf.thumbnails:
            if t.format_code == gl._IMG_QOI:
                assert t.data[:4] == b"qoif", f"QOI thumbnail missing qoif magic"
            elif t.format_code == gl._IMG_PNG:
                assert t.data[:4] == b"\x89PNG", f"PNG thumbnail missing PNG magic"

    @needs_gcode
    def test_thumbnail_block_lines_absent_from_gf_lines(self):
        # begin/end markers must be stripped; slicer metadata comments like
        # "; thumbnails = 16x16/QOI, ..." are normal lines and may remain.
        gf = gl.load(GCODE_PATH)
        import re
        begin_re = re.compile(r"thumbnail(?:_\w+)?\s+begin", re.IGNORECASE)
        end_re   = re.compile(r"thumbnail(?:_\w+)?\s+end",   re.IGNORECASE)
        for line in gf.lines:
            assert not begin_re.search(line.raw), f"thumbnail begin still in lines: {line.raw!r}"
            assert not end_re.search(line.raw),   f"thumbnail end still in lines: {line.raw!r}"

    @needs_gcode
    def test_header_size_is_b64_char_count(self):
        """Re-emitted thumbnail headers must use base64 char count, not raw byte count."""
        gf = gl.load(GCODE_PATH)
        out = gl.to_text(gf)
        for t in gf.thumbnails:
            keyword = gl._THUMB_FMT_KEYWORD.get(t.format_code, "thumbnail")
            b64_len = len(base64.b64encode(t.data))
            expected = f"; {keyword} begin {t.width}x{t.height} {b64_len}"
            assert expected in out, f"Missing header for {t.width}x{t.height}: {expected!r}"

    @needs_gcode
    def test_round_trip_preserves_thumbnail_data(self, tmp_path):
        gf = gl.load(GCODE_PATH)
        orig_thumbs = [(t.width, t.height, t.format_code, t.data) for t in gf.thumbnails]

        dst = tmp_path / "benchy_rt.gcode"
        gl.save(gf, str(dst))

        gf2 = gl.load(str(dst))
        assert len(gf2.thumbnails) == len(orig_thumbs)
        for t, (w, h, fmt, data) in zip(gf2.thumbnails, orig_thumbs):
            assert t.width  == w
            assert t.height == h
            assert t.format_code == fmt
            assert t.data   == data

    @needs_gcode
    def test_round_trip_line_count_delta_is_thumbnail_separators(self, tmp_path):
        # _render_text_thumbnails appends one blank separator line per thumbnail.
        # The original file may have had a different blank-line count around
        # thumbnail blocks, so the delta equals the number of thumbnails.
        gf = gl.load(GCODE_PATH)
        orig_count = len(gf.lines)
        n_thumbs = len(gf.thumbnails)

        dst = tmp_path / "benchy_rt.gcode"
        gl.save(gf, str(dst))

        gf2 = gl.load(str(dst))
        delta = len(gf2.lines) - orig_count
        assert abs(delta) <= n_thumbs, (
            f"Line count changed by {delta} (expected at most ±{n_thumbs})"
        )

    @needs_gcode
    def test_stats_smoke(self):
        gf = gl.load(GCODE_PATH)
        stats = gl.compute_stats(gf.lines)
        assert stats.move_count > 0
        assert stats.layer_count > 0
        assert stats.total_extrusion > 0
        assert stats.bounds.valid

    @needs_gcode
    def test_bounds_reasonable_for_benchy(self):
        gf = gl.load(GCODE_PATH)
        bounds = gl.compute_bounds(gf.lines, extruding_only=True)
        # Benchy is ~60 x 31 mm footprint, ~48 mm tall.
        # Bed coordinates vary by printer, so only sanity-check Z height.
        assert bounds.valid
        assert 40 < bounds.z_max < 60, f"unexpected Z max {bounds.z_max}"
        assert bounds.width  > 30, f"print width too small: {bounds.width}"
        assert bounds.height > 15, f"print height too small: {bounds.height}"


# ---------------------------------------------------------------------------
# Binary .bgcode — current limitation: Heatshrink GCode blocks
# ---------------------------------------------------------------------------

class TestRealBgcode:
    @needs_bgcode
    def test_recognised_as_bgcode(self):
        # File should be detected as bgcode, not rejected as unknown binary
        assert gl._is_bgcode_file(BGCODE_PATH)

    @needs_bgcode
    def test_load_raises_for_heatshrink(self):
        """Real PrusaSlicer .bgcode uses Heatshrink (type 3) GCode compression.

        This is a known limitation: the library only supports DEFLATE and
        uncompressed GCode blocks.  The error message should clearly identify
        the problem.
        """
        with pytest.raises(ValueError, match="Heatshrink"):
            gl.load(BGCODE_PATH)
