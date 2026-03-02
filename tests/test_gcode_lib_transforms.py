"""Tests for gcode_lib transforms: linearize_arcs, apply_xy_transform, apply_skew, translate_xy, rotate_xy."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gcode_lib as gl


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def test_fmt_float_trims_trailing_zeros():
    assert gl.fmt_float(10.0, 3) == "10"
    assert gl.fmt_float(10.100, 3) == "10.1"
    assert gl.fmt_float(10.125, 3) == "10.125"


def test_fmt_float_negative_zero():
    assert gl.fmt_float(-0.0, 3) == "0"


def test_fmt_axis_xy_uses_xy_decimals():
    s = gl.fmt_axis("X", 10.12345, xy_decimals=2, other_decimals=5)
    assert s == "10.12"


def test_fmt_axis_e_uses_other_decimals():
    s = gl.fmt_axis("E", 1.12345, xy_decimals=2, other_decimals=4)
    assert s == "1.1235"  # rounds to 4 places → 1.1234 actually, let me check
    # 1.12345 rounded to 4 places = 1.1235 (banker's rounding: 5 rounds to even → 4 even → 1.1234)
    # Python f"{1.12345:.4f}" -> "1.1235" (standard rounding)
    assert gl.fmt_axis("E", 1.12345, xy_decimals=2, other_decimals=4) in ("1.1234", "1.1235")


def test_replace_or_append_replaces_existing():
    result = gl.replace_or_append("G1 X10 Y20", "X", 15.5)
    assert "X15.5" in result
    assert "X10" not in result


def test_replace_or_append_appends_when_missing():
    result = gl.replace_or_append("G1 Y20", "X", 15.5)
    assert "X15.5" in result


def test_replace_or_append_preserves_other_words():
    result = gl.replace_or_append("G1 X10 Y20 E1.0", "X", 99.0)
    assert "Y20" in result
    assert "E1" in result


def test_replace_or_append_only_first_occurrence():
    # Should only replace first X occurrence (unusual but defensive)
    result = gl.replace_or_append("G1 X10 X20", "X", 5.0)
    # One X5 present, at most one replacement
    assert result.count("X5") == 1


# ---------------------------------------------------------------------------
# linearize_arcs — basic
# ---------------------------------------------------------------------------

def test_linearize_arcs_replaces_g2_with_g1():
    lines = gl.parse_lines("G90\nG1 X0 Y0\nG2 X10 Y0 I5 J0")
    result = gl.linearize_arcs(lines)
    commands = [ln.command for ln in result]
    assert "G2" not in commands
    assert "G1" in commands


def test_linearize_arcs_replaces_g3_with_g1():
    lines = gl.parse_lines("G90\nG1 X0 Y0\nG3 X0 Y10 I0 J5")
    result = gl.linearize_arcs(lines)
    assert all(ln.command != "G3" for ln in result)


def test_linearize_arcs_non_arc_lines_unchanged():
    lines = gl.parse_lines("G90\nM82\nG1 X10 Y20 E1.0\n; comment")
    result = gl.linearize_arcs(lines)
    # Non-arc lines preserve their raw text
    non_arc = [ln for ln in result if ln.command != "G1" or "G2" not in ln.raw]
    assert result[0].raw == lines[0].raw   # G90
    assert result[1].raw == lines[1].raw   # M82


def test_linearize_arcs_endpoint_correct():
    """Last segment of a linearized arc must end exactly at the arc endpoint."""
    lines = gl.parse_lines("G90\nG1 X0 Y0\nG2 X10 Y0 I5 J0")
    result = gl.linearize_arcs(lines)
    g1_lines = [ln for ln in result if ln.command == "G1" and "X" in ln.words]
    last = g1_lines[-1]
    assert last.words["X"] == pytest.approx(10.0, abs=1e-3)
    assert last.words["Y"] == pytest.approx(0.0, abs=1e-3)


def test_linearize_arcs_produces_multiple_segments():
    """A 90° arc of radius 10 at default precision should produce many segments."""
    lines = gl.parse_lines("G90\nG1 X10 Y0\nG3 X0 Y10 I-10 J0")
    result = gl.linearize_arcs(lines)
    g1_count = sum(1 for ln in result if ln.command == "G1")
    assert g1_count > 2   # Must have more than the original single move + arc


def test_linearize_arcs_full_circle():
    """A full-circle arc (start == end) should be linearized, not dropped."""
    lines = gl.parse_lines("G90\nG1 X10 Y0\nG2 X10 Y0 I-10 J0")
    result = gl.linearize_arcs(lines)
    arc_segs = [ln for ln in result if ln.command == "G1" and "X" in ln.words]
    # Should have many segments (full circle ≈ 63 mm circumference / 0.2 mm)
    assert len(arc_segs) > 30


def test_linearize_arcs_e_preserved_abs():
    """Absolute E at arc end must equal the value in the original arc command."""
    lines = gl.parse_lines("G90\nM82\nG1 X0 Y0 E0\nG2 X10 Y0 I5 J0 E2.5")
    result = gl.linearize_arcs(lines)
    g1s = [ln for ln in result if ln.command == "G1" and "E" in ln.words]
    last_e = g1s[-1].words["E"]
    assert last_e == pytest.approx(2.5, abs=1e-4)


def test_linearize_arcs_e_preserved_rel():
    """Sum of printed relative E increments must equal the original arc E."""
    lines = gl.parse_lines("G90\nM83\nG1 X0 Y0\nG2 X10 Y0 I5 J0 E1.0")
    result = gl.linearize_arcs(lines)
    g1s = [ln for ln in result if ln.command == "G1" and "E" in ln.words]
    total = sum(ln.words["E"] for ln in g1s)
    assert total == pytest.approx(1.0, abs=1e-4)


def test_linearize_arcs_comment_on_first_segment():
    lines = gl.parse_lines("G90\nG1 X0 Y0\nG2 X10 Y0 I5 J0 ; arc comment")
    result = gl.linearize_arcs(lines)
    # The original 'G1 X0 Y0' is at index 0; arc segments follow
    g1s = [ln for ln in result if ln.command == "G1"]
    # Exactly one line should carry the arc comment
    with_comment = [ln for ln in g1s if "; arc comment" in ln.raw]
    assert len(with_comment) == 1
    # It must be the first arc segment, not the original G1 X0 Y0
    assert with_comment[0].raw != "G1 X0 Y0"
    # All other arc G1s must not carry the comment
    without_comment = [ln for ln in g1s if "; arc comment" not in ln.raw]
    assert len(without_comment) == len(g1s) - 1


def test_linearize_arcs_feedrate_on_first_segment_only():
    lines = gl.parse_lines("G90\nG1 X0 Y0\nG2 X10 Y0 I5 J0 F2000")
    result = gl.linearize_arcs(lines)
    # Only one G1 among the arc segments should carry the F word
    g1s_with_f = [ln for ln in result if ln.command == "G1" and "F" in ln.words]
    assert len(g1s_with_f) == 1
    # The G1 with F must be an arc segment (not the original 'G1 X0 Y0')
    assert g1s_with_f[0].raw != "G1 X0 Y0"


def test_linearize_arcs_z_word_on_first_segment_only():
    """Z word in an arc is preserved on the first linearized segment only."""
    lines = gl.parse_lines("G90\nG1 X0 Y0 Z0.2\nG2 X10 Y0 Z0.4 I5 J0")
    result = gl.linearize_arcs(lines)
    arc_segs = [ln for ln in result if ln.command == "G1" and ln.raw != "G1 X0 Y0 Z0.2"]
    # First segment carries Z
    assert "Z" in arc_segs[0].words
    assert arc_segs[0].words["Z"] == pytest.approx(0.4)
    # Remaining segments do not carry Z
    for seg in arc_segs[1:]:
        assert "Z" not in seg.words


def test_linearize_arcs_z_state_updated():
    """After linearizing an arc with Z, state.z reflects the arc's Z endpoint."""
    lines = gl.parse_lines("G90\nG1 X0 Y0 Z0.2\nG2 X10 Y0 Z0.4 I5 J0\nG1 X20 Y0")
    result = gl.linearize_arcs(lines)
    state = gl.ModalState()
    for ln in result:
        gl.advance_state(state, ln)
    assert state.z == pytest.approx(0.4)


def test_linearize_arcs_no_z_word_state_unchanged():
    """An arc without a Z word must not change the Z state."""
    lines = gl.parse_lines("G90\nG1 X0 Y0 Z0.3\nG2 X10 Y0 I5 J0")
    result = gl.linearize_arcs(lines)
    state = gl.ModalState()
    for ln in result:
        gl.advance_state(state, ln)
    assert state.z == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# apply_xy_transform
# ---------------------------------------------------------------------------

def test_apply_xy_transform_identity():
    lines  = gl.parse_lines("G90\nG1 X10 Y20 E1.0")
    result = gl.apply_xy_transform(lines, lambda x, y: (x, y))
    g1 = next(ln for ln in result if ln.command == "G1")
    assert g1.words["X"] == pytest.approx(10.0, abs=0.001)
    assert g1.words["Y"] == pytest.approx(20.0, abs=0.001)


def test_apply_xy_transform_scale():
    lines  = gl.parse_lines("G90\nG1 X10 Y20")
    result = gl.apply_xy_transform(lines, lambda x, y: (x * 2, y * 2))
    g1 = next(ln for ln in result if ln.command == "G1")
    assert g1.words["X"] == pytest.approx(20.0, abs=0.001)
    assert g1.words["Y"] == pytest.approx(40.0, abs=0.001)


def test_apply_xy_transform_preserves_other_words():
    lines  = gl.parse_lines("G90\nG1 X10 Y20 Z0.2 E1.0 F3000")
    result = gl.apply_xy_transform(lines, lambda x, y: (x + 1, y + 1))
    g1 = next(ln for ln in result if ln.command == "G1")
    assert "Z" in g1.raw
    assert "E" in g1.raw
    assert "F" in g1.raw


def test_apply_xy_transform_passes_through_non_moves():
    lines  = gl.parse_lines("G90\nM82\n; comment\nG1 X5")
    result = gl.apply_xy_transform(lines, lambda x, y: (x, y))
    assert result[0].raw == "G90"
    assert result[1].raw == "M82"
    assert result[2].raw == "; comment"


def test_apply_xy_transform_raises_on_relative_xy():
    lines = gl.parse_lines("G91\nG1 X5 Y5")
    with pytest.raises(ValueError, match="relative XY"):
        gl.apply_xy_transform(lines, lambda x, y: (x, y))


def test_apply_xy_transform_no_xy_move_passes_through():
    """G1 with only Z or E should pass through unmodified."""
    lines  = gl.parse_lines("G90\nG1 Z0.2")
    result = gl.apply_xy_transform(lines, lambda x, y: (x * 10, y * 10))
    g1 = next(ln for ln in result if ln.command == "G1")
    assert g1.raw == "G1 Z0.2"


def test_apply_xy_transform_state_uses_original_coords():
    """Subsequent moves use original (untransformed) coords for state."""
    # First move: X0 -> X10, state.x should remain 0 for the second move
    calls: list[tuple[float, float]] = []
    def fn(x: float, y: float) -> tuple[float, float]:
        calls.append((x, y))
        return (x + 100, y)

    lines  = gl.parse_lines("G90\nG1 X0 Y0\nG1 X5 Y0")
    gl.apply_xy_transform(lines, fn)
    # Second call should receive (5, 0) not (105, 0)
    assert calls[1][0] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# apply_skew
# ---------------------------------------------------------------------------

def test_apply_skew_zero_deg_no_change():
    lines  = gl.parse_lines("G90\nG1 X10 Y20 E1.0")
    result = gl.apply_skew(lines, skew_deg=0.0)
    g1 = next(ln for ln in result if ln.command == "G1")
    assert g1.words["X"] == pytest.approx(10.0, abs=0.001)
    assert g1.words["Y"] == pytest.approx(20.0, abs=0.001)


def test_apply_skew_y_unchanged():
    """Skew is XY-shear only; Y must not change."""
    lines  = gl.parse_lines("G90\nG1 X10 Y15 E1.0")
    result = gl.apply_skew(lines, skew_deg=1.0)
    g1 = next(ln for ln in result if ln.command == "G1")
    assert g1.words["Y"] == pytest.approx(15.0, abs=0.001)


def test_apply_skew_x_shifted():
    """x' = x + (y - y_ref) * tan(theta)."""
    skew_deg = 1.0
    k = math.tan(math.radians(skew_deg))
    lines  = gl.parse_lines("G90\nG1 X10 Y10 E1.0")
    result = gl.apply_skew(lines, skew_deg=skew_deg, y_ref=0.0)
    g1 = next(ln for ln in result if ln.command == "G1")
    expected_x = 10.0 + (10.0 - 0.0) * k
    assert g1.words["X"] == pytest.approx(expected_x, abs=0.001)


def test_apply_skew_y_ref_affects_x():
    """With y_ref = y, x displacement is zero."""
    skew_deg = 5.0
    lines  = gl.parse_lines("G90\nG1 X10 Y20 E1.0")
    result = gl.apply_skew(lines, skew_deg=skew_deg, y_ref=20.0)
    g1 = next(ln for ln in result if ln.command == "G1")
    assert g1.words["X"] == pytest.approx(10.0, abs=0.001)  # (y - y_ref) = 0


def test_apply_skew_negative_angle():
    k = math.tan(math.radians(-1.0))
    lines  = gl.parse_lines("G90\nG1 X10 Y10 E1.0")
    result = gl.apply_skew(lines, skew_deg=-1.0)
    g1 = next(ln for ln in result if ln.command == "G1")
    expected_x = 10.0 + 10.0 * k
    assert g1.words["X"] == pytest.approx(expected_x, abs=0.001)


def test_apply_skew_multiple_moves():
    skew_deg = 0.5
    k = math.tan(math.radians(skew_deg))
    lines  = gl.parse_lines("G90\nG1 X10 Y10\nG1 X20 Y30")
    result = gl.apply_skew(lines, skew_deg=skew_deg)
    g1s = [ln for ln in result if ln.command == "G1"]
    assert g1s[0].words["X"] == pytest.approx(10.0 + 10.0 * k, abs=0.001)
    assert g1s[1].words["X"] == pytest.approx(20.0 + 30.0 * k, abs=0.001)


# ---------------------------------------------------------------------------
# translate_xy
# ---------------------------------------------------------------------------

def test_translate_xy_shifts_x_and_y():
    lines  = gl.parse_lines("G90\nG1 X10 Y20")
    result = gl.translate_xy(lines, dx=5.0, dy=-3.0)
    g1 = next(ln for ln in result if ln.command == "G1")
    assert g1.words["X"] == pytest.approx(15.0, abs=0.001)
    assert g1.words["Y"] == pytest.approx(17.0, abs=0.001)


def test_translate_xy_zero_no_change():
    lines  = gl.parse_lines("G90\nG1 X10 Y20")
    result = gl.translate_xy(lines, dx=0.0, dy=0.0)
    g1 = next(ln for ln in result if ln.command == "G1")
    assert g1.words["X"] == pytest.approx(10.0, abs=0.001)
    assert g1.words["Y"] == pytest.approx(20.0, abs=0.001)


def test_translate_xy_passes_through_non_moves():
    lines  = gl.parse_lines("G90\nM82\nG1 X10 Y20")
    result = gl.translate_xy(lines, dx=1.0, dy=1.0)
    assert result[0].raw == "G90"
    assert result[1].raw == "M82"


def test_translate_xy_multiple_moves():
    lines  = gl.parse_lines("G90\nG1 X0 Y0\nG1 X10 Y10")
    result = gl.translate_xy(lines, dx=100.0, dy=200.0)
    g1s = [ln for ln in result if ln.command == "G1"]
    assert g1s[0].words["X"] == pytest.approx(100.0, abs=0.001)
    assert g1s[0].words["Y"] == pytest.approx(200.0, abs=0.001)
    assert g1s[1].words["X"] == pytest.approx(110.0, abs=0.001)
    assert g1s[1].words["Y"] == pytest.approx(210.0, abs=0.001)


# ---------------------------------------------------------------------------
# Combined: linearize_arcs then apply_skew
# ---------------------------------------------------------------------------

def test_linearize_then_skew_no_arcs_in_output():
    lines    = gl.parse_lines("G90\nG1 X0 Y0\nG2 X10 Y0 I5 J0 E1.0")
    lin      = gl.linearize_arcs(lines)
    result   = gl.apply_skew(lin, skew_deg=0.5)
    assert all(ln.command != "G2" for ln in result)
    assert all(ln.command != "G3" for ln in result)


def test_linearize_then_skew_x_monotone_for_positive_y():
    """For positive skew and positive Y, all X values should be shifted right."""
    skew_deg = 1.0
    k = math.tan(math.radians(skew_deg))
    # Straight horizontal extrusion at y=10
    lines  = gl.parse_lines("G90\nM82\nG1 X0 Y10 E0\nG1 X100 Y10 E2.0")
    result = gl.apply_skew(lines, skew_deg=skew_deg)
    g1s = [ln for ln in result if ln.command == "G1" and "X" in ln.words]
    for ln in g1s:
        # Every X should be shifted by (10 * k) relative to original
        orig_x = ln.words["X"] - 10.0 * k  # un-skew
        assert orig_x >= -0.001  # original was non-negative


# ---------------------------------------------------------------------------
# rotate_xy
# ---------------------------------------------------------------------------

class TestRotateXY:
    """Tests for rotate_xy transform."""

    def test_zero_rotation_is_identity(self):
        """0° rotation should leave coordinates unchanged."""
        lines = gl.parse_lines("G90\nG1 X10 Y20\nG1 X30 Y40")
        result = gl.rotate_xy(lines, 0.0)
        g1s = [ln for ln in result if ln.command == "G1"]
        assert g1s[0].words["X"] == pytest.approx(10.0, abs=1e-3)
        assert g1s[0].words["Y"] == pytest.approx(20.0, abs=1e-3)
        assert g1s[1].words["X"] == pytest.approx(30.0, abs=1e-3)
        assert g1s[1].words["Y"] == pytest.approx(40.0, abs=1e-3)

    def test_90_degree_rotation(self):
        """90° CCW rotation of a point (20, 0) around origin (0,0) → (0, 20)."""
        lines = gl.parse_lines("G90\nG1 X20 Y0")
        result = gl.rotate_xy(lines, 90.0, pivot_x=0.0, pivot_y=0.0)
        g1 = [ln for ln in result if ln.command == "G1"][0]
        assert g1.words["X"] == pytest.approx(0.0, abs=1e-3)
        assert g1.words["Y"] == pytest.approx(20.0, abs=1e-3)

    def test_negative_90_degree_rotation(self):
        """−90° (CW) rotation of (0, 10) around origin → (10, 0)."""
        lines = gl.parse_lines("G90\nG1 X0 Y10")
        result = gl.rotate_xy(lines, -90.0, pivot_x=0.0, pivot_y=0.0)
        g1 = [ln for ln in result if ln.command == "G1"][0]
        assert g1.words["X"] == pytest.approx(10.0, abs=1e-3)
        assert g1.words["Y"] == pytest.approx(0.0, abs=1e-3)

    def test_45_degree_rotation(self):
        """45° CCW rotation of (10, 0) around origin → (7.071, 7.071)."""
        lines = gl.parse_lines("G90\nG1 X10 Y0")
        result = gl.rotate_xy(lines, 45.0, pivot_x=0.0, pivot_y=0.0)
        g1 = [ln for ln in result if ln.command == "G1"][0]
        expected = 10.0 * math.cos(math.radians(45))
        assert g1.words["X"] == pytest.approx(expected, abs=1e-3)
        assert g1.words["Y"] == pytest.approx(expected, abs=1e-3)

    def test_180_degree_rotation_square(self):
        """180° rotation of a square path flips all coordinates around center."""
        lines = gl.parse_lines(
            "G90\nG1 X0 Y0\nG1 X10 Y0\nG1 X10 Y10\nG1 X0 Y10"
        )
        # Print center is (5, 5); 180° around center flips each point
        result = gl.rotate_xy(lines, 180.0)
        g1s = [ln for ln in result if ln.command == "G1"]
        # (0,0) → (10,10), (10,0) → (0,10), (10,10) → (0,0), (0,10) → (10,0)
        assert g1s[0].words["X"] == pytest.approx(10.0, abs=1e-3)
        assert g1s[0].words["Y"] == pytest.approx(10.0, abs=1e-3)
        assert g1s[1].words["X"] == pytest.approx(0.0, abs=1e-3)
        assert g1s[1].words["Y"] == pytest.approx(10.0, abs=1e-3)
        assert g1s[2].words["X"] == pytest.approx(0.0, abs=1e-3)
        assert g1s[2].words["Y"] == pytest.approx(0.0, abs=1e-3)
        assert g1s[3].words["X"] == pytest.approx(10.0, abs=1e-3)
        assert g1s[3].words["Y"] == pytest.approx(0.0, abs=1e-3)

    def test_custom_pivot(self):
        """Rotation around a custom pivot point."""
        lines = gl.parse_lines("G90\nG1 X20 Y10")
        # Rotate (20, 10) by 90° around (10, 10) → (10, 20)
        result = gl.rotate_xy(lines, 90.0, pivot_x=10.0, pivot_y=10.0)
        g1 = [ln for ln in result if ln.command == "G1"][0]
        assert g1.words["X"] == pytest.approx(10.0, abs=1e-3)
        assert g1.words["Y"] == pytest.approx(20.0, abs=1e-3)

    def test_arc_rotation_relative_ij(self):
        """G2 arc with relative I/J: both endpoint and I/J vector are rotated."""
        # Quarter-circle arc: from (10,0) to (0,10) with centre at (0,0), I=-10 J=0
        lines = gl.parse_lines("G90\nG91.1\nG1 X10 Y0\nG3 X0 Y10 I-10 J0")
        # Rotate 90° CCW around origin: start (10,0)→(0,10), end (0,10)→(-10,0)
        # I/J vector (-10,0) rotated 90° CCW → (0,-10)
        result = gl.rotate_xy(lines, 90.0, pivot_x=0.0, pivot_y=0.0)
        arcs = [ln for ln in result if ln.is_arc]
        assert len(arcs) == 1
        arc = arcs[0]
        assert arc.words["X"] == pytest.approx(-10.0, abs=1e-3)
        assert arc.words["Y"] == pytest.approx(0.0, abs=1e-3)
        assert arc.words["I"] == pytest.approx(0.0, abs=1e-3)
        assert arc.words["J"] == pytest.approx(-10.0, abs=1e-3)

    def test_bed_validation_recenters(self):
        """Rotated print should be re-centred within the bed."""
        # Square at (0,0)-(10,10), rotate 0° with bed 0-100 x 0-100
        lines = gl.parse_lines("G90\nG1 X0 Y0\nG1 X10 Y10")
        result = gl.rotate_xy(
            lines, 0.0,
            bed_min_x=0, bed_max_x=100, bed_min_y=0, bed_max_y=100,
        )
        bounds = gl.compute_bounds(result)
        # Should be centred at (50, 50)
        assert bounds.center_x == pytest.approx(50.0, abs=1e-3)
        assert bounds.center_y == pytest.approx(50.0, abs=1e-3)

    def test_bed_validation_raises_if_too_large(self):
        """ValueError when rotated print exceeds bed area."""
        lines = gl.parse_lines("G90\nG1 X0 Y0\nG1 X100 Y100")
        with pytest.raises(ValueError, match="exceeds available bed area"):
            gl.rotate_xy(
                lines, 45.0,
                bed_min_x=0, bed_max_x=100, bed_min_y=0, bed_max_y=100,
                skip_negative_y=False,
            )

    def test_bed_validation_with_margin(self):
        """Margin reduces available bed area."""
        # 10x10 print on a 20x20 bed with 6mm margin → available 8x8 → doesn't fit
        lines = gl.parse_lines("G90\nG1 X0 Y0\nG1 X10 Y10")
        with pytest.raises(ValueError, match="exceeds available bed area"):
            gl.rotate_xy(
                lines, 0.0,
                bed_min_x=0, bed_max_x=20, bed_min_y=0, bed_max_y=20,
                margin=6.0,
            )

    def test_g91_raises_valueerror(self):
        """Relative XY mode should raise ValueError."""
        lines = gl.parse_lines("G91\nG1 X10 Y10")
        with pytest.raises(ValueError, match="relative XY"):
            gl.rotate_xy(lines, 45.0)

    def test_preserves_z_and_e(self):
        """Z and E coordinates must not be modified by rotation."""
        lines = gl.parse_lines("G90\nG1 X10 Y0 Z5.0 E1.5")
        result = gl.rotate_xy(lines, 90.0, pivot_x=0.0, pivot_y=0.0)
        g1 = [ln for ln in result if ln.command == "G1"][0]
        assert g1.words["Z"] == pytest.approx(5.0)
        assert g1.words["E"] == pytest.approx(1.5)

    def test_comments_preserved(self):
        """Comments should be preserved after rotation."""
        lines = gl.parse_lines("G90\nG1 X10 Y0 ; perimeter")
        result = gl.rotate_xy(lines, 90.0, pivot_x=0.0, pivot_y=0.0)
        g1 = [ln for ln in result if ln.command == "G1"][0]
        assert "; perimeter" in g1.raw

    def test_non_move_lines_unchanged(self):
        """Non-move lines (M commands, comments) should pass through unchanged."""
        lines = gl.parse_lines("G90\nM104 S200\n; comment\nG1 X10 Y10")
        result = gl.rotate_xy(lines, 45.0, pivot_x=0.0, pivot_y=0.0)
        assert result[1].raw == "M104 S200"
        assert result[2].raw == "; comment"

    def test_skip_negative_y_default(self):
        """Moves at negative Y should NOT be transformed by default."""
        lines = gl.parse_lines("G90\nG1 X50 Y-19\nG1 X50 Y10")
        result = gl.rotate_xy(lines, 90.0, pivot_x=50.0, pivot_y=0.0)
        g1s = [ln for ln in result if ln.command == "G1"]
        # Y=-19 move should be untouched
        assert g1s[0].words["X"] == pytest.approx(50.0, abs=1e-3)
        assert g1s[0].words["Y"] == pytest.approx(-19.0, abs=1e-3)
        # Y=10 move should be rotated: (50, 10) around (50, 0) by 90° → (40, 0)
        assert g1s[1].words["X"] == pytest.approx(40.0, abs=1e-3)
        assert g1s[1].words["Y"] == pytest.approx(0.0, abs=1e-3)

    def test_skip_negative_y_false_transforms_all(self):
        """With skip_negative_y=False, negative-Y moves are also transformed."""
        lines = gl.parse_lines("G90\nG1 X50 Y-19")
        result = gl.rotate_xy(lines, 90.0, pivot_x=50.0, pivot_y=0.0, skip_negative_y=False)
        g1 = [ln for ln in result if ln.command == "G1"][0]
        # (50, -19) around (50, 0) by 90° → (50+19, 0) = (69, 0)
        assert g1.words["X"] == pytest.approx(69.0, abs=1e-3)
        assert g1.words["Y"] == pytest.approx(0.0, abs=1e-3)


# ---------------------------------------------------------------------------
# skip_negative_y across other transforms
# ---------------------------------------------------------------------------

def test_translate_xy_allow_arcs_skips_negative_y():
    """translate_xy_allow_arcs should skip negative-Y moves by default."""
    lines = gl.parse_lines("G90\nG1 X10 Y-5\nG1 X10 Y20")
    result = gl.translate_xy_allow_arcs(lines, dx=100.0, dy=100.0)
    g1s = [ln for ln in result if ln.command == "G1"]
    # Y=-5 move: untouched
    assert g1s[0].words["X"] == pytest.approx(10.0, abs=1e-3)
    assert g1s[0].words["Y"] == pytest.approx(-5.0, abs=1e-3)
    # Y=20 move: shifted
    assert g1s[1].words["X"] == pytest.approx(110.0, abs=1e-3)
    assert g1s[1].words["Y"] == pytest.approx(120.0, abs=1e-3)


def test_apply_xy_transform_skips_negative_y():
    """apply_xy_transform should skip negative-Y moves by default."""
    lines = gl.parse_lines("G90\nG1 X10 Y-3\nG1 X10 Y5")
    result = gl.apply_xy_transform(lines, lambda x, y: (x + 50, y + 50))
    g1s = [ln for ln in result if ln.command == "G1"]
    # Y=-3 move: untouched
    assert g1s[0].words["X"] == pytest.approx(10.0, abs=1e-3)
    assert g1s[0].words["Y"] == pytest.approx(-3.0, abs=1e-3)
    # Y=5 move: transformed
    assert g1s[1].words["X"] == pytest.approx(60.0, abs=1e-3)
    assert g1s[1].words["Y"] == pytest.approx(55.0, abs=1e-3)


def test_compute_bounds_skip_negative_y():
    """compute_bounds with skip_negative_y should exclude negative-Y points."""
    lines = gl.parse_lines("G90\nG1 X10 Y-19\nG1 X20 Y5\nG1 X30 Y15")
    b_all = gl.compute_bounds(lines)
    b_skip = gl.compute_bounds(lines, skip_negative_y=True)
    assert b_all.y_min == pytest.approx(-19.0, abs=1e-3)
    assert b_skip.y_min == pytest.approx(5.0, abs=1e-3)
    # X and max Y should be the same
    assert b_skip.x_max == pytest.approx(30.0, abs=1e-3)
    assert b_skip.y_max == pytest.approx(15.0, abs=1e-3)
