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


# ---------------------------------------------------------------------------
# Real .gcode — new §4–§9 features exercised against a live Benchy file
# ---------------------------------------------------------------------------

COREONE_BED = [(0, 0), (250, 0), (250, 220), (0, 220)]


class TestRealGcodeTransforms:
    """Smoke tests for the new transform/analysis functions on a real slicer file."""

    @needs_gcode
    def test_real_file_has_arcs(self):
        """PrusaSlicer emits G2/G3 arcs for perimeters — confirm they exist."""
        gf = gl.load(GCODE_PATH)
        arc_count = sum(1 for l in gf.lines if l.is_arc)
        assert arc_count > 1000, f"Expected many arcs, got {arc_count}"

    @needs_gcode
    def test_real_file_is_pure_g90(self):
        """Slicer output should contain no G91 relative-mode lines."""
        gf = gl.load(GCODE_PATH)
        g91_count = sum(1 for l in gf.lines if l.command.upper() == "G91")
        assert g91_count == 0

    @needs_gcode
    def test_iter_layers_one_more_than_stats(self):
        """iter_layers yields stats.layer_count + 1: one initial setup group at Z=0
        before the first layer move, plus one group per actual print layer."""
        gf = gl.load(GCODE_PATH)
        stats  = gl.compute_stats(gf.lines)
        layers = list(gl.iter_layers(gf.lines))
        assert len(layers) == stats.layer_count + 1

    @needs_gcode
    def test_iter_layers_first_group_at_z_zero(self):
        """The first group emitted by iter_layers is always at Z=0 (initial state)."""
        gf = gl.load(GCODE_PATH)
        layers = list(gl.iter_layers(gf.lines))
        z0, _ = layers[0]
        assert z0 == pytest.approx(0.0)

    @needs_gcode
    def test_real_file_has_oob_purge_moves(self):
        """The Benchy file has purge/wipe moves that go below Y=0 (outside the bed).
        find_oob_moves must detect them."""
        gf = gl.load(GCODE_PATH)
        hits = gl.find_oob_moves(gf.lines, COREONE_BED)
        assert len(hits) > 0
        # All OOB moves should have a positive distance_outside
        assert all(h.distance_outside > 0.0 for h in hits)

    @needs_gcode
    def test_translate_xy_allow_arcs_shifts_bounds(self):
        """translate_xy_allow_arcs must shift the XY bounding box by exactly (dx, dy)
        without destroying arc commands."""
        gf  = gl.load(GCODE_PATH)
        dx, dy = 5.0, 3.0
        before = gl.compute_bounds(gf.lines)
        lines  = gl.translate_xy_allow_arcs(gf.lines, dx=dx, dy=dy)
        after  = gl.compute_bounds(lines)

        assert after.x_min == pytest.approx(before.x_min + dx, abs=0.01)
        assert after.y_min == pytest.approx(before.y_min + dy, abs=0.01)
        assert after.x_max == pytest.approx(before.x_max + dx, abs=0.01)
        assert after.y_max == pytest.approx(before.y_max + dy, abs=0.01)
        # Arc commands must be preserved
        arcs_after = sum(1 for l in lines if l.is_arc)
        assert arcs_after == sum(1 for l in gf.lines if l.is_arc)

    @needs_gcode
    def test_translate_preserves_print_dimensions(self):
        """A translate-then-inverse-translate must restore the original bounding box
        width and height to within floating-point tolerance."""
        gf     = gl.load(GCODE_PATH)
        before = gl.compute_bounds(gf.lines)
        lines  = gl.translate_xy_allow_arcs(gf.lines, dx=10.0, dy=7.0)
        lines  = gl.translate_xy_allow_arcs(lines,    dx=-10.0, dy=-7.0)
        after  = gl.compute_bounds(lines)
        assert after.width  == pytest.approx(before.width,  abs=0.01)
        assert after.height == pytest.approx(before.height, abs=0.01)

    @needs_gcode
    def test_linearize_arcs_eliminates_all_arcs(self):
        """linearize_arcs must replace every G2/G3 with G1 segments."""
        gf    = gl.load(GCODE_PATH)
        lines = gl.linearize_arcs(gf.lines)
        assert sum(1 for l in lines if l.is_arc) == 0

    @needs_gcode
    def test_linearize_arcs_increases_line_count(self):
        """Replacing arcs with multiple G1 segments must increase total line count."""
        gf    = gl.load(GCODE_PATH)
        lines = gl.linearize_arcs(gf.lines)
        assert len(lines) > len(gf.lines)

    @needs_gcode
    def test_to_absolute_xy_idempotent_on_g90_file(self):
        """to_absolute_xy on a pure G90 file must leave XY bounds identical."""
        gf     = gl.load(GCODE_PATH)
        before = gl.compute_bounds(gf.lines)
        lines  = gl.to_absolute_xy(gf.lines)
        after  = gl.compute_bounds(lines)
        assert after.x_min == pytest.approx(before.x_min, abs=0.01)
        assert after.x_max == pytest.approx(before.x_max, abs=0.01)
        assert after.y_min == pytest.approx(before.y_min, abs=0.01)
        assert after.y_max == pytest.approx(before.y_max, abs=0.01)

    @needs_gcode
    def test_analyze_xy_transform_reports_correct_shift(self):
        """analyze_xy_transform with a 10 mm X shift must report max_dx ≈ 10."""
        gf   = gl.load(GCODE_PATH)
        info = gl.analyze_xy_transform(gf.lines, lambda x, y: (x + 10.0, y))
        assert info["max_dx"]           == pytest.approx(10.0, abs=0.01)
        assert info["max_dy"]           == pytest.approx(0.0,  abs=0.01)
        assert info["max_displacement"] == pytest.approx(10.0, abs=0.01)
        assert info["move_count"]       > 0

    @needs_gcode
    def test_recenter_to_bed_centers_bounding_box(self):
        """After recentering with margin=5 on the COREONE bed, the print bounding
        box centre should be at the bed's usable centre (125, 110)."""
        gf = gl.load(GCODE_PATH)
        p  = gl.PRINTER_PRESETS["COREONE"]
        lines  = gl.recenter_to_bed(
            gf.lines,
            bed_min_x=0.0, bed_max_x=p["bed_x"],
            bed_min_y=0.0, bed_max_y=p["bed_y"],
            margin=5.0,
            mode="center",
        )
        bounds = gl.compute_bounds(lines)
        usable_cx = (5.0 + (p["bed_x"] - 5.0)) / 2   # 125.0
        usable_cy = (5.0 + (p["bed_y"] - 5.0)) / 2   # 110.0
        assert bounds.center_x == pytest.approx(usable_cx, abs=0.5)
        assert bounds.center_y == pytest.approx(usable_cy, abs=0.5)

    @needs_gcode
    def test_recenter_reduces_max_oob_distance(self):
        """Recentering a print that straddles the bed edge must reduce the maximum
        out-of-bounds distance for the purge moves."""
        gf = gl.load(GCODE_PATH)
        p  = gl.PRINTER_PRESETS["COREONE"]
        oob_before = gl.max_oob_distance(gf.lines, COREONE_BED)

        lines     = gl.recenter_to_bed(
            gf.lines, 0, p["bed_x"], 0, p["bed_y"], margin=5.0, mode="center"
        )
        oob_after = gl.max_oob_distance(lines, COREONE_BED)
        assert oob_after < oob_before

    @needs_gcode
    def test_write_bgcode_read_bgcode_round_trip(self):
        """Encoding the Benchy G-code as BGCode and decoding it must preserve
        key print semantics (move count, layer count, extrusion)."""
        gf = gl.load(GCODE_PATH)
        # to_text re-embeds thumbnail comment lines; write those directly into
        # the BGCode G-code block (pass thumbnails separately so they are also
        # stored in BGCode thumbnail blocks).
        bgcode_bytes = gl.write_bgcode(gl.to_text(gf), thumbnails=gf.thumbnails)
        gf2 = gl.read_bgcode(bgcode_bytes)

        # Thumbnail blocks round-trip correctly
        assert len(gf2.thumbnails) == len(gf.thumbnails)

        # Print semantics are preserved (compare stats on the decoded file)
        s1 = gl.compute_stats(gf.lines)
        s2 = gl.compute_stats(gf2.lines)
        assert s2.move_count    == s1.move_count
        assert s2.layer_count   == s1.layer_count
        assert s2.total_extrusion == pytest.approx(s1.total_extrusion, rel=1e-4)

    @needs_gcode
    def test_encode_thumbnail_comment_block_round_trip(self):
        """encode_thumbnail_comment_block → parse_lines → load must recover the
        original thumbnail data byte-for-byte."""
        gf = gl.load(GCODE_PATH)
        # Find the PNG thumbnail (encode_thumbnail_comment_block is PNG-only)
        png_thumb = next(
            t for t in gf.thumbnails if t.format_code == gl._IMG_PNG
        )
        block = gl.encode_thumbnail_comment_block(
            png_thumb.width, png_thumb.height, png_thumb.data
        )
        recovered = gl.from_text(block)
        assert len(recovered.thumbnails) == 1
        rt = recovered.thumbnails[0]
        assert rt.width  == png_thumb.width
        assert rt.height == png_thumb.height
        assert rt.data   == png_thumb.data
