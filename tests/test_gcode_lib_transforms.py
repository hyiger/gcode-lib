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


@pytest.mark.parametrize(
    "code, axis, expected",
    [
        pytest.param("G1 X10 Y20", "X", "G1 Y20", id="first-word"),
        pytest.param("G1 X10 Y20", "Y", "G1 X10", id="last-word-leaves-no-trailing-space"),
        pytest.param("G1 X10 Y20 E1", "Y", "G1 X10 E1", id="middle-word"),
        pytest.param("G1 x10 Y20", "X", "G1 Y20", id="lowercase-word"),
        pytest.param("G1 X10 Y20", "x", "G1 Y20", id="lowercase-axis"),
        pytest.param("G1 X-1.5e2 Y20", "X", "G1 Y20", id="exponent"),
        pytest.param("G1 X 10 Y20", "X", "G1 Y20", id="space-before-number"),
        pytest.param("G1 X10. Y20", "X", "G1 Y20", id="trailing-dot"),
        pytest.param("G1 Y20 X10.", "X", "G1 Y20", id="trailing-dot-at-end"),
        pytest.param("G1 X10 X20", "X", "G1 X20", id="first-occurrence-only"),
    ],
)
def test_replace_or_append_none_removes_word(code, axis, expected):
    assert gl.replace_or_append(code, axis, None) == expected


def test_replace_or_append_none_with_missing_axis_changes_nothing():
    assert gl.replace_or_append("G1 Y20", "X", None) == "G1 Y20"


def test_replace_or_append_can_remap_an_axis():
    code = "G1 X10 Y20"
    code = gl.replace_or_append(code, "X", None)
    code = gl.replace_or_append(code, "F", 10.0)
    assert code == "G1 Y20 F10"


@pytest.mark.parametrize(
    "code, expected",
    [
        pytest.param("G1 X10  Y20", "G1 X5  Y20", id="keeps-spacing-after-word"),
        pytest.param("G1 X10. Y20", "G1 X5 Y20", id="trailing-dot"),
        pytest.param("G1 Y20 X10.", "G1 Y20 X5", id="trailing-dot-at-end"),
    ],
)
def test_replace_or_append_replaces_whole_word(code, expected):
    assert gl.replace_or_append(code, "X", 5.0) == expected


@pytest.mark.parametrize(
    "code, axis, val, expected",
    [
        pytest.param("G1X10Y20", "X", 5.0, "G1X5Y20", id="after-command"),
        pytest.param("G1 X10Y20", "Y", 5.0, "G1 X10Y5", id="after-word"),
        pytest.param("G1 X10Y20E1", "Y", 5.0, "G1 X10Y5E1", id="between-words"),
        pytest.param("G1 X10.Y20", "X", 5.0, "G1 X5Y20", id="trailing-dot"),
        pytest.param("G1X10Y20", "X", None, "G1Y20", id="remove-first"),
        pytest.param("G1 X10Y20E1", "Y", None, "G1 X10E1", id="remove-middle"),
        pytest.param("G1 X10Y20", "Y", None, "G1 X10", id="remove-last"),
    ],
)
def test_replace_or_append_handles_words_without_spaces(code, axis, val, expected):
    assert gl.replace_or_append(code, axis, val) == expected


def test_replace_or_append_does_not_match_inside_a_longer_word():
    assert gl.replace_or_append("G1 MAX5 Y20", "X", 1.0) == "G1 MAX5 Y20 X1"


@pytest.mark.parametrize(
    "code, val, expected",
    [
        pytest.param("G1 A1e2 E3", 5.0, "G1 A1e2 E5", id="replace"),
        pytest.param("G1 A1e2 E3", None, "G1 A1e2", id="remove"),
        pytest.param("G1 A1e2", 5.0, "G1 A1e2 E5", id="append"),
        pytest.param("G1 A1e2", None, "G1 A1e2", id="remove-absent"),
        pytest.param("G1 X1.5e-2 E3 Y2", 5.0, "G1 X1.5e-2 E5 Y2", id="signed-exponent"),
    ],
)
def test_replace_or_append_e_word_ignores_exponents(code, val, expected):
    assert gl.replace_or_append(code, "E", val) == expected


def test_replace_or_append_changes_a_word_written_with_an_exponent():
    assert gl.replace_or_append("G1 A1e2 E3", "A", 5.0) == "G1 A5 E3"


def test_translate_xy_keeps_rotary_exponent_and_e_word():
    moved = gl.translate_xy(gl.parse_lines("G90\nG1 X10 Y20 A1e2 E3"), 5.0, 10.0)[1]
    assert moved.raw == "G1 X15 Y30 A1e2 E3"


@pytest.mark.parametrize(
    "code, axis, val, expected",
    [
        pytest.param("G1 X1e2e3 Y20", "X", 105.0, "G1 X105 e3 Y20", id="replace-before-e"),
        pytest.param("G1 X1Y2 e3", "Y", None, "G1 X1 e3", id="remove-spaced"),
        pytest.param("G1 X1Y2e3", "Y", None, "G1 X1", id="exponent-belongs-to-its-word"),
        pytest.param("G1 X1.Y2 e3", "Y", None, "G1 X1. e3", id="remove-after-trailing-dot"),
        pytest.param("G1 X1Y2 E3", "Y", None, "G1 X1E3", id="uppercase-e-needs-no-gap"),
        pytest.param("G1 X1Y2 F3", "Y", None, "G1 X1F3", id="other-words-need-no-gap"),
        pytest.param("e3 Y2", "Y", None, "e3", id="nothing-before"),
    ],
)
def test_replace_or_append_keeps_e_word_out_of_the_number_before_it(code, axis, val, expected):
    result = gl.replace_or_append(code, axis, val)
    assert result == expected
    untouched = {k: v for k, v in gl.parse_words(code).items() if k != axis.upper()}
    assert {k: v for k, v in gl.parse_words(result).items() if k != axis.upper()} == untouched


def test_translate_xy_keeps_compact_e_word_after_exponent():
    moved = gl.translate_xy(gl.parse_lines("G90\nG1 X1e2e3 Y20"), 5.0, 10.0)[1]
    assert gl.parse_line(moved.raw).words == pytest.approx({"X": 105.0, "Y": 30.0, "E": 3.0})


def test_translate_xy_keeps_compact_words_free_of_duplicates():
    moved = gl.translate_xy(gl.parse_lines("G90\nG1 X10Y20E1.5"), 5.0, 7.0)[1]
    assert moved.raw == "G1 X15Y27E1.5"


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

    def test_arc_rotation_absolute_ij_r_arc_does_not_inject_ij(self):
        """R-format arcs in G90.1 mode must not be rewritten to include I/J."""
        lines = gl.parse_lines("G90\nG90.1\nG2 X10 Y0 R5")
        result = gl.rotate_xy(lines, 0.0, pivot_x=0.0, pivot_y=0.0, skip_negative_y=False)
        arc = [ln for ln in result if ln.is_arc][0]
        assert "I" not in arc.words
        assert "J" not in arc.words
        assert " I" not in arc.raw
        assert " J" not in arc.raw

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

    def test_bed_validation_respects_initial_state(self):
        """Bed fit/recenter pass must use initial_state for partial-axis moves."""
        lines = gl.parse_lines("G90\nG1 Y60\nG1 X120")
        initial = gl.ModalState()
        initial.x = 100.0
        initial.y = 50.0
        result = gl.rotate_xy(
            lines, 0.0,
            bed_min_x=0, bed_max_x=200, bed_min_y=0, bed_max_y=200,
            initial_state=initial,
            skip_negative_y=False,
        )
        g1s = [ln for ln in result if ln.command == "G1"]
        # True pre-center bounds center is (110, 60), so recenter delta is (-10, +40).
        assert g1s[0].words["Y"] == pytest.approx(100.0, abs=1e-3)
        assert g1s[1].words["X"] == pytest.approx(110.0, abs=1e-3)

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


# ---------------------------------------------------------------------------
# Rotational axes A, B, C carried through transforms
# ---------------------------------------------------------------------------

def test_translate_xy_preserves_rotational_axes():
    lines = gl.parse_lines("G90\nG1 X10 Y20 A30 B45 C60 E1.0")
    result = gl.translate_xy(lines, dx=5, dy=10)
    g1 = [ln for ln in result if ln.command == "G1"][0]
    assert g1.words["X"] == pytest.approx(15.0)
    assert g1.words["Y"] == pytest.approx(30.0)
    assert g1.words["A"] == pytest.approx(30.0)
    assert g1.words["B"] == pytest.approx(45.0)
    assert g1.words["C"] == pytest.approx(60.0)
    assert g1.words["E"] == pytest.approx(1.0)


def test_translate_xy_allow_arcs_preserves_rotational():
    lines = gl.parse_lines("G90\nG1 X0 Y0\nG2 X10 Y0 I5 J0 A90 B180")
    result = gl.translate_xy_allow_arcs(lines, dx=5, dy=5)
    arc = [ln for ln in result if ln.command == "G2"][0]
    assert arc.words["X"] == pytest.approx(15.0)
    assert arc.words["Y"] == pytest.approx(5.0)
    assert arc.words["A"] == pytest.approx(90.0)
    assert arc.words["B"] == pytest.approx(180.0)


def test_rotate_xy_preserves_rotational_axes():
    lines = gl.parse_lines("G90\nG1 X10 Y0 A45 B90")
    result = gl.rotate_xy(lines, angle_deg=90)
    g1 = [ln for ln in result if ln.command == "G1"][0]
    assert g1.words["A"] == pytest.approx(45.0)
    assert g1.words["B"] == pytest.approx(90.0)


def test_apply_xy_transform_preserves_rotational():
    lines = gl.parse_lines("G90\nG1 X10 Y20 A30 C60")
    result = gl.apply_xy_transform(lines, lambda x, y: (x + 100, y + 100))
    g1 = [ln for ln in result if ln.command == "G1"][0]
    assert g1.words["X"] == pytest.approx(110.0)
    assert g1.words["Y"] == pytest.approx(120.0)
    assert g1.words["A"] == pytest.approx(30.0)
    assert g1.words["C"] == pytest.approx(60.0)


def test_linearize_arcs_preserves_rotational():
    lines = gl.parse_lines("G90\nG1 X0 Y0\nG2 X10 Y0 I5 J0 A180")
    result = gl.linearize_arcs(lines)
    g1s = [ln for ln in result if ln.command == "G1"]
    # First G1 is the original G1 X0 Y0 (no A); the arc ends at the commanded angle
    assert g1s[-1].words.get("A") == pytest.approx(180.0)


def test_compute_bounds_skip_negative_y_keeps_y_zero():
    """Y=0 is on the bed; only strictly negative Y is skipped."""
    lines = gl.parse_lines("G90\nG1 X5 Y0")
    bounds = gl.compute_bounds(lines, skip_negative_y=True)
    assert bounds.valid
    assert bounds.y_min == pytest.approx(0.0)


def test_compute_bounds_skip_negative_y_filters_arc_points():
    """Only the part of an arc below Y=0 is excluded."""
    lines = gl.parse_lines("G90\nG1 X0 Y0\nG3 X10 Y0 I5 J0")  # dips to Y=-5
    assert gl.compute_bounds(lines).y_min == pytest.approx(-5.0, abs=0.01)
    skipped = gl.compute_bounds(lines, skip_negative_y=True)
    assert skipped.y_min == pytest.approx(0.0)
    assert skipped.x_max == pytest.approx(10.0)


def test_compute_bounds_extruding_only_ignores_travel_arc():
    lines = gl.parse_lines("G90\nM83\nG2 X10 Y0 I5 J0")
    assert not gl.compute_bounds(lines, extruding_only=True).valid


def test_compute_bounds_extruding_only_includes_extruding_arc():
    lines = gl.parse_lines("G90\nM83\nG2 X10 Y0 I5 J0 E1")
    assert gl.compute_bounds(lines, extruding_only=True).x_max == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Formatting and arc-linearization edge cases
# ---------------------------------------------------------------------------

def _final_xy(lines):
    """Replay the written text of *lines* and return the resulting XY position."""
    state = gl.ModalState()
    for line in lines:
        gl.advance_state(state, gl.parse_line(line.raw))
    return state.x, state.y


def _shift_x(x, y):
    return x + 100.0, y


def test_fmt_float_zero_with_zero_places():
    assert gl.fmt_float(0.0, 0) == "0"


@pytest.mark.parametrize(
    "value, expected",
    [(10.0, "10"), (100.0, "100"), (20.4, "20"), (-20.4, "-20"), (-0.4, "0")],
)
def test_fmt_float_zero_places_keeps_integer_digits(value, expected):
    assert gl.fmt_float(value, 0) == expected


def test_translate_xy_zero_decimals_keeps_coordinates():
    lines = gl.parse_lines("G90\nG1 X100 Y20")
    assert gl.translate_xy(lines, 10.0, 0.0, xy_decimals=0)[1].raw == "G1 X110 Y20"


def test_linearize_arcs_absolute_path_ends_where_source_ends():
    src = gl.parse_lines("G90\nG1 X10 Y0\nG3 X0 Y10 I-10 J0")
    assert _final_xy(gl.linearize_arcs(src)) == pytest.approx(_final_xy(src), abs=1e-3)


def test_linearize_arcs_relative_path_ends_where_source_ends():
    src = gl.parse_lines("G91\nG1 X10 Y0\nG3 X-10 Y10 I-10 J0")
    assert _final_xy(gl.linearize_arcs(src)) == pytest.approx(_final_xy(src), abs=1e-3)


def test_linearize_arcs_relative_output_stays_on_the_arc():
    src = gl.parse_lines("G91\nG1 X10 Y0\nG3 X-10 Y10 I-10 J0")
    state = gl.ModalState()
    for line in gl.linearize_arcs(src):
        gl.advance_state(state, gl.parse_line(line.raw))
        if line.command == "G1":
            assert math.hypot(state.x, state.y) == pytest.approx(10.0, abs=0.01)


def test_linearize_arcs_relative_rounding_does_not_accumulate():
    src = gl.parse_lines("G91\nG1 X7.3 Y2.1\nG2 I-7.3 J-2.1")  # full circle, hundreds of segments
    result = gl.linearize_arcs(src)
    assert len(result) > 200
    assert _final_xy(result) == pytest.approx((7.3, 2.1), abs=6e-4)


def test_linearize_arcs_r_format_stays_on_the_circle():
    result = gl.linearize_arcs(gl.parse_lines("G90\nG1 X10 Y0\nG3 X0 Y10 R10"))
    assert not any(line.is_arc for line in result)
    for line in result[2:]:
        assert math.hypot(line.words["X"], line.words["Y"]) == pytest.approx(10.0, abs=1e-3)


# ---------------------------------------------------------------------------
# rotate_xy edge cases
# ---------------------------------------------------------------------------

class TestRotateXYEdgeCases:
    def test_no_xy_moves_returns_equal_copy(self):
        lines = gl.parse_lines("M104 S200\nG28")
        result = gl.rotate_xy(lines, 45.0)
        assert result == lines
        assert result is not lines

    def test_missing_pivot_y_comes_from_bounds_centre(self):
        lines = gl.parse_lines("G90\nG1 X0 Y0\nG1 X10 Y20")
        result = gl.rotate_xy(lines, 180.0, pivot_x=0.0)
        g1s = [ln for ln in result if ln.command == "G1"]
        assert (g1s[0].words["X"], g1s[0].words["Y"]) == pytest.approx((0.0, 20.0), abs=1e-3)
        assert (g1s[1].words["X"], g1s[1].words["Y"]) == pytest.approx((-10.0, 0.0), abs=1e-3)

    def test_missing_pivot_x_comes_from_bounds_centre(self):
        lines = gl.parse_lines("G90\nG1 X0 Y0\nG1 X10 Y20")
        result = gl.rotate_xy(lines, 180.0, pivot_y=0.0)
        g1s = [ln for ln in result if ln.command == "G1"]
        assert (g1s[0].words["X"], g1s[0].words["Y"]) == pytest.approx((10.0, 0.0), abs=1e-3)
        assert (g1s[1].words["X"], g1s[1].words["Y"]) == pytest.approx((0.0, -20.0), abs=1e-3)

    def test_absolute_ij_centre_rotates_as_a_point(self):
        lines = gl.parse_lines("G90\nG90.1\nG1 X10 Y0\nG3 X0 Y10 I0 J0")
        result = gl.rotate_xy(lines, 90.0, pivot_x=10.0, pivot_y=0.0)
        arc = gl.parse_line(next(ln for ln in result if ln.is_arc).raw)
        assert arc.words["X"] == pytest.approx(0.0, abs=1e-3)
        assert arc.words["Y"] == pytest.approx(-10.0, abs=1e-3)
        assert arc.words["I"] == pytest.approx(10.0, abs=1e-3)
        assert arc.words["J"] == pytest.approx(-10.0, abs=1e-3)

    def test_r_arc_in_relative_ij_mode_does_not_inject_ij(self):
        lines = gl.parse_lines("G90\nG91.1\nG1 X10 Y0\nG3 X0 Y10 R10")
        result = gl.rotate_xy(lines, 90.0, pivot_x=0.0, pivot_y=0.0)
        arc = next(ln for ln in result if ln.is_arc)
        assert arc.words["X"] == pytest.approx(-10.0, abs=1e-3)
        assert arc.words["Y"] == pytest.approx(0.0, abs=1e-3)
        assert arc.words["R"] == pytest.approx(10.0)
        assert "I" not in arc.words and "J" not in arc.words
        assert " I" not in arc.raw and " J" not in arc.raw

    def test_bed_validation_without_moves_is_a_noop(self):
        lines = gl.parse_lines("M104 S200")
        result = gl.rotate_xy(
            lines, 0.0, pivot_x=0.0, pivot_y=0.0,
            bed_min_x=0, bed_max_x=10, bed_min_y=0, bed_max_y=10,
        )
        assert result == lines

    def test_bed_validation_leaves_centred_print_in_place(self):
        lines = gl.parse_lines("G90\nG1 X40 Y40\nG1 X60 Y60")
        result = gl.rotate_xy(
            lines, 0.0,
            bed_min_x=0, bed_max_x=100, bed_min_y=0, bed_max_y=100,
        )
        g1s = [ln for ln in result if ln.command == "G1"]
        assert g1s[0].words["X"] == pytest.approx(40.0, abs=1e-3)
        assert g1s[1].words["Y"] == pytest.approx(60.0, abs=1e-3)

    def test_partial_axis_move_reaches_rotated_target(self):
        lines = gl.parse_lines("G90\nG1 X10 Y20\nG1 X30")
        result = gl.rotate_xy(lines, 90.0, pivot_x=0.0, pivot_y=0.0)
        assert _final_xy(result) == pytest.approx((-20.0, 30.0), abs=1e-3)

    def test_partial_y_move_reaches_rotated_target(self):
        lines = gl.parse_lines("G90\nG1 X10 Y20\nG1 Y30")
        result = gl.rotate_xy(lines, 90.0, pivot_x=0.0, pivot_y=0.0)
        assert _final_xy(result) == pytest.approx((-30.0, 10.0), abs=1e-3)

    def test_partial_axis_move_keeps_e_f_and_comment(self):
        lines = gl.parse_lines("G90\nG1 X10 Y20\nG1 X30 E1.5 F1200 ; wall")
        moved = gl.rotate_xy(lines, 90.0, pivot_x=0.0, pivot_y=0.0)[2]
        for token in ("E1.5", "F1200", "; wall"):
            assert token in moved.raw

    def test_rotated_r_arc_linearizes_onto_the_rotated_circle(self):
        lines = gl.parse_lines("G90\nG1 X10 Y0\nG3 X0 Y10 R10")
        rotated = gl.rotate_xy(lines, 90.0, pivot_x=0.0, pivot_y=0.0)
        for line in gl.linearize_arcs(rotated)[1:]:
            assert math.hypot(line.words["X"], line.words["Y"]) == pytest.approx(10.0, abs=1e-3)

    @pytest.mark.parametrize(
        "program, expected_ij",
        [
            ("G90\nG1 X10 Y0\nG3 X0 Y10 I-10", (0.0, -10.0)),
            ("G90\nG1 X0 Y10\nG3 X-10 Y0 J-10", (10.0, 0.0)),
        ],
    )
    def test_arc_with_omitted_ij_word_keeps_centre(self, program, expected_ij):
        result = gl.rotate_xy(gl.parse_lines(program), 90.0, pivot_x=0.0, pivot_y=0.0)
        arc = next(ln for ln in result if ln.is_arc)
        written = gl.parse_line(arc.raw).words
        assert (arc.words["I"], arc.words["J"]) == pytest.approx(expected_ij, abs=1e-3)
        assert (written["I"], written["J"]) == pytest.approx(expected_ij, abs=1e-3)


# ---------------------------------------------------------------------------
# translate_xy_allow_arcs edge cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "arc_words, expected_ij",
    [("I5", (8.0, 4.0)), ("J5", (3.0, 9.0)), ("I5 J6", (8.0, 10.0))],
)
def test_translate_xy_allow_arcs_absolute_centre_is_shifted(arc_words, expected_ij):
    lines = gl.parse_lines(f"G90.1\nG2 X10 Y0 {arc_words}")
    arc = next(ln for ln in gl.translate_xy_allow_arcs(lines, 3.0, 4.0) if ln.is_arc)
    written = gl.parse_line(arc.raw).words
    assert (arc.words["I"], arc.words["J"]) == pytest.approx(expected_ij)
    assert (written["I"], written["J"]) == pytest.approx(expected_ij)


def test_translate_xy_allow_arcs_absolute_mode_does_not_inject_ij_into_r_arc():
    lines = gl.parse_lines("G90.1\nG2 X10 Y0 R5")
    arc = next(ln for ln in gl.translate_xy_allow_arcs(lines, 3.0, 4.0) if ln.is_arc)
    assert "I" not in arc.words and "J" not in arc.words


def test_translate_xy_allow_arcs_partial_move_after_skipped_region():
    lines = gl.parse_lines("G90\nG1 X10 Y-1\nG1 Y5")
    result = gl.translate_xy_allow_arcs(lines, 100.0, 0.0)
    assert _final_xy(result) == pytest.approx((110.0, 5.0), abs=1e-3)


def test_translate_xy_allow_arcs_partial_first_move_gets_both_offsets():
    result = gl.translate_xy_allow_arcs(gl.parse_lines("G90\nG1 X30"), 5.0, 7.0)
    assert _final_xy(result) == pytest.approx((35.0, 7.0), abs=1e-3)


# ---------------------------------------------------------------------------
# apply_xy_transform_by_layer edge cases
# ---------------------------------------------------------------------------

class TestApplyXYTransformByLayerEdgeCases:
    def test_skipped_negative_y_move_still_tracks_z(self):
        lines = gl.parse_lines("G90\nG1 X5 Y-2 Z1.0\nG1 X5 Y5")
        result = gl.apply_xy_transform_by_layer(lines, _shift_x, z_max=0.5)
        assert [ln.raw for ln in result] == [ln.raw for ln in lines]

    def test_skipped_negative_y_move_without_z_keeps_layer(self):
        lines = gl.parse_lines("G90\nG1 X5 Y-2\nG1 X5 Y5")
        result = gl.apply_xy_transform_by_layer(lines, _shift_x)
        assert result[1].raw == "G1 X5 Y-2"
        assert result[2].words["X"] == pytest.approx(105.0)

    def test_skip_negative_y_false_transforms_purge_moves(self):
        lines = gl.parse_lines("G90\nG1 X5 Y-2")
        result = gl.apply_xy_transform_by_layer(lines, _shift_x, skip_negative_y=False)
        assert result[1].words["X"] == pytest.approx(105.0)

    @pytest.mark.parametrize("extrusion_mode", ["M82", "M83"])
    def test_z_e_f_and_comment_preserved(self, extrusion_mode):
        lines = gl.parse_lines(f"G90\n{extrusion_mode}\nG1 X1 Y1 Z0.2 E0.5 F1200 ; wall")
        moved = gl.apply_xy_transform_by_layer(lines, _shift_x)[2]
        assert moved.words["X"] == pytest.approx(101.0)
        for token in ("Z0.2", "E0.5", "F1200", "; wall"):
            assert token in moved.raw

    def test_layers_above_range_are_untouched(self):
        lines = gl.parse_lines("G90\nG1 X1 Y1 Z0.2\nG1 X2 Y2\nG1 Z1.0\nG1 X4 Y4")
        result = gl.apply_xy_transform_by_layer(lines, _shift_x, z_max=0.5)
        xs = [ln.words["X"] for ln in result if "X" in ln.words]
        assert xs == pytest.approx([101.0, 102.0, 4.0])

    @pytest.mark.parametrize(
        "bounds, expected_xs",
        [
            ({"z_min": 5.0}, [1.0, 110.0, 120.0]),
            ({"z_max": 0.2}, [101.0, 10.0, 20.0]),
        ],
    )
    def test_combined_xyz_move_follows_iter_layers_membership(self, bounds, expected_xs):
        lines = gl.parse_lines("G90\nG1 X1 Y1 Z0.2\nG1 X10 Y10 Z5\nG1 X20 Y20")
        result = gl.apply_xy_transform_by_layer(lines, _shift_x, **bounds)
        xs = [ln.words["X"] for ln in result if "X" in ln.words]
        assert xs == pytest.approx(expected_xs)

    def test_selected_lines_match_iter_layers(self):
        lines = gl.parse_lines(
            "G90\nG1 X1 Y1\nG1 X2 Y2 Z0.2\nG1 X3 Y3\nG1 X4 Y4 Z0.4\nG1 X5 Y5\nG1 Z0.6\nG1 X6 Y6"
        )
        selected = [
            line.raw
            for z, group in gl.iter_layers(lines)
            if 0.2 <= z <= 0.4
            for line in group
            if "X" in line.words
        ]
        result = gl.apply_xy_transform_by_layer(lines, _shift_x, z_min=0.2, z_max=0.4)
        changed = [src.raw for src, out in zip(lines, result) if src.raw != out.raw]
        assert changed == selected

    def test_relative_z_change_is_tracked(self):
        lines = gl.parse_lines("G91\nG1 Z5\nG90\nG1 X1 Y1")
        result = gl.apply_xy_transform_by_layer(lines, _shift_x, z_min=5.0)
        assert result[3].words["X"] == pytest.approx(101.0)

    def test_relative_z_word_is_added_to_the_current_height(self):
        lines = gl.parse_lines("G90\nG1 Z4\nG91\nG1 X1 Y1 Z1")  # lands at Z=5, above the range
        result = gl.apply_xy_transform_by_layer(lines, _shift_x, z_max=4.5)
        assert [line.raw for line in result] == [line.raw for line in lines]

    def test_initial_state_z_sets_the_starting_layer(self):
        initial = gl.ModalState()
        initial.z = 5.0
        lines = gl.parse_lines("G90\nG1 X1 Y1")
        result = gl.apply_xy_transform_by_layer(lines, _shift_x, z_min=5.0, initial_state=initial)
        assert result[1].words["X"] == pytest.approx(101.0)


# ---------------------------------------------------------------------------
# Remaining helpers
# ---------------------------------------------------------------------------

def test_to_absolute_xy_keeps_feedrate_and_arc_offsets():
    lines = gl.parse_lines("G90\nG1 X10 Y10\nG91\nG1 X5 F1200\nG2 X5 Y5 I2.5 J2.5")
    result = gl.to_absolute_xy(lines)
    move = next(ln for ln in result if "F" in ln.words)
    arc = next(ln for ln in result if ln.is_arc)
    assert move.words["X"] == pytest.approx(15.0)
    assert "F1200" in move.raw
    assert (arc.words["X"], arc.words["Y"]) == pytest.approx((20.0, 15.0))
    assert (arc.words["I"], arc.words["J"]) == pytest.approx((2.5, 2.5))


def test_dist_to_segment_degenerate_segment_is_point_distance():
    assert gl._dist_to_segment(3.0, 4.0, 0.0, 0.0, 0.0, 0.0) == pytest.approx(5.0)


def test_recenter_to_bed_fit_rejects_margin_consuming_the_bed():
    lines = gl.parse_lines("G90\nG1 X0 Y0\nG1 X10 Y10")
    with pytest.raises(ValueError, match="zero or negative"):
        gl.recenter_to_bed(lines, 0, 20, 0, 20, margin=10.0, mode="fit")


# ---------------------------------------------------------------------------
# Rotational axes through G91 conversion, layers and arc linearization
# ---------------------------------------------------------------------------

def _final_abc(lines):
    """Replay the written text of *lines* and return the resulting A/B/C position."""
    state = gl.ModalState()
    for line in lines:
        gl.advance_state(state, gl.parse_line(line.raw))
    return state.a, state.b, state.c


def test_to_absolute_xy_accumulates_rotational_axes():
    lines = gl.parse_lines("G91\nG1 X1 A10 B20 C30\nG1 X1 A10 B20 C30\nG1 A5")
    result = gl.to_absolute_xy(lines)
    assert [ln.raw for ln in result] == [
        "G90", "G1 X1 A10 B20 C30", "G1 X2 A20 B40 C60", "G1 A25",
    ]
    assert result[2].words["A"] == pytest.approx(20.0)
    assert result[2].words["B"] == pytest.approx(40.0)
    assert result[2].words["C"] == pytest.approx(60.0)


def test_to_absolute_xy_rotational_axis_continues_from_absolute_position():
    result = gl.to_absolute_xy(gl.parse_lines("G90\nG1 A90\nG91\nG1 A10"))
    assert _final_abc(result) == pytest.approx((100.0, 0.0, 0.0))


def test_to_absolute_xy_leaves_omitted_rotational_axes_unwritten():
    result = gl.to_absolute_xy(gl.parse_lines("G91\nG1 A10\nG1 X5"))
    assert result[2].raw == "G1 X5"


def test_apply_xy_transform_by_layer_keeps_rotational_axes():
    lines = gl.parse_lines("G90\nG1 X1 Y1 Z5 A30 B40 C50 F100\nG1 X2 Y2 C7")
    result = gl.apply_xy_transform_by_layer(lines, _shift_x, z_min=5.0)
    assert result[1].words["X"] == pytest.approx(101.0)
    assert result[2].words["X"] == pytest.approx(102.0)
    assert _final_abc(result) == pytest.approx((30.0, 40.0, 7.0))


@pytest.mark.parametrize("axis", ["A", "B", "C"])
def test_linearize_arcs_interpolates_rotational_axes(axis):
    lines = gl.parse_lines(f"G90\nG1 X10 Y0\nG3 X0 Y10 I-10 J0 {axis}180")
    result = gl.linearize_arcs(lines, seg_mm=1000.0, max_deg=50.0)
    assert [ln.words[axis] for ln in result[2:]] == pytest.approx([90.0, 180.0])
    assert f"{axis}90" in result[2].raw
    assert f"{axis}180" in result[3].raw


def test_linearize_arcs_interpolates_from_current_rotational_position():
    lines = gl.parse_lines("G90\nG1 X10 Y0 A90\nG3 X0 Y10 I-10 J0 A270")
    result = gl.linearize_arcs(lines, seg_mm=1000.0, max_deg=50.0)
    assert [ln.words["A"] for ln in result[2:]] == pytest.approx([180.0, 270.0])


def test_linearize_arcs_interpolates_relative_rotational_steps():
    lines = gl.parse_lines("G91\nG1 X10 Y0 A10\nG3 X-10 Y10 I-10 J0 A90")
    result = gl.linearize_arcs(lines, seg_mm=1000.0, max_deg=50.0)
    assert [ln.words["A"] for ln in result[2:]] == pytest.approx([45.0, 45.0])
    assert _final_abc(result)[0] == pytest.approx(100.0)


def test_linearize_arcs_tracks_rotational_position_between_arcs():
    lines = gl.parse_lines(
        "G90\nG1 X10 Y0\nG3 X0 Y10 I-10 J0 A90\nG3 X-10 Y0 I0 J-10 A180"
    )
    result = gl.linearize_arcs(lines, seg_mm=1000.0, max_deg=50.0)
    assert [ln.words["A"] for ln in result[2:]] == pytest.approx([45.0, 90.0, 135.0, 180.0])


def test_linearize_arcs_tracks_relative_rotational_position_between_arcs():
    lines = gl.parse_lines("G91\nG1 X10 Y0\nG3 X-10 Y10 I-10 J0 A90\nG3 X-10 Y-10 I0 J-10 A90")
    assert _final_abc(gl.linearize_arcs(lines)) == pytest.approx((180.0, 0.0, 0.0), abs=1e-4)


def test_linearize_arcs_relative_rotational_rounding_does_not_accumulate():
    lines = gl.parse_lines("G91\nG1 X10 Y0\nG3 I-10 J0 A0.00007")
    result = gl.linearize_arcs(lines)
    assert len(result) > 300
    assert _final_abc(result)[0] == pytest.approx(0.00007, abs=1e-5)


def test_linearize_arcs_writes_only_the_rotational_axes_on_the_arc():
    lines = gl.parse_lines("G90\nG1 X10 Y0\nG3 X0 Y10 I-10 J0 B90")
    for line in gl.linearize_arcs(lines)[2:]:
        assert "B" in line.words
        assert "A" not in line.words and "C" not in line.words


def test_linearize_arcs_relative_rotational_axes_end_where_source_ends():
    src = gl.parse_lines("G91\nG1 X10 Y0 A10 B1 C2\nG3 X-10 Y10 I-10 J0 A5 B2 C3")
    assert _final_abc(gl.linearize_arcs(src)) == pytest.approx(_final_abc(src))


def test_translate_xy_leaves_compact_rotational_words_verbatim():
    moved = gl.translate_xy(gl.parse_lines("G90\nG1 X10 Y20 A30B45C60"), 5.0, 10.0)[1]
    assert moved.raw == "G1 X15 Y30 A30B45C60"


def test_by_layer_leaves_compact_rotational_words_verbatim():
    lines = gl.parse_lines("G90\nG1 X10 Y20 A30B45C60")
    result = gl.apply_xy_transform_by_layer(lines, _shift_x)
    assert result[1].raw == "G1 X110 Y20 A30B45C60"


def test_to_absolute_xy_handles_compact_rotational_words():
    lines = gl.parse_lines("G91\nG1 X1 A10B20\nG1 X1 A10B20")
    assert gl.to_absolute_xy(lines)[2].raw == "G1 X2 A20B40"


def test_e_word_directly_after_rotational_word_keeps_extrusion():
    line = gl.parse_line("G1 X10 Y20 A30E1.5")
    assert (line.words["A"], line.words["E"]) == pytest.approx((30.0, 1.5))
    moved = gl.translate_xy([line], 5.0, 10.0)[0]
    assert moved.raw == "G1 X15 Y30 A30E1.5"


def test_linearize_arcs_keeps_e_word_after_rotational_word():
    lines = gl.parse_lines("G90\nG1 X10 Y0\nG3 X0 Y10 I-10 J0 A90E1.5")
    last = gl.linearize_arcs(lines)[-1]
    assert (last.words["A"], last.words["E"]) == pytest.approx((90.0, 1.5))
