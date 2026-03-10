"""
Tests for the Engineering Master Document extensions (§4–§9).

Covers:
  §4.1  to_absolute_xy
  §4.2  translate_xy_allow_arcs
  §4.3  OOBHit / find_oob_moves / max_oob_distance
  §4.4  recenter_to_bed
  §4.5  analyze_xy_transform
  §4.6  iter_layers / apply_xy_transform_by_layer
  §5    PRINTER_PRESETS / FILAMENT_PRESETS
  §6    render_template
  §7    encode_thumbnail_comment_block
  §8    read_bgcode / write_bgcode
  §9    PrusaSlicerCapabilities / RunResult / SliceRequest / find_prusaslicer_executable
"""
from __future__ import annotations

import math
import struct
import subprocess

import pytest

import gcode_lib as gl


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lines(text: str):
    return gl.parse_lines(text)


def _xy_of(line: gl.GCodeLine):
    return line.words.get("X"), line.words.get("Y")


def _rect_bed(w: float = 250.0, h: float = 220.0):
    """Rectangular bed polygon from (0,0) to (w,h)."""
    return [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]


# ===========================================================================
# §4.1 — to_absolute_xy
# ===========================================================================

class TestToAbsoluteXY:
    def test_pure_g90_passthrough(self):
        """G90-only file is returned unchanged (no G90 prepended)."""
        src = "G90\nG1 X10 Y20\nG1 X30 Y40\n"
        out = gl.to_absolute_xy(_lines(src))
        moves = [l for l in out if l.is_move]
        assert moves[0].words["X"] == pytest.approx(10.0)
        assert moves[1].words["X"] == pytest.approx(30.0)
        # No extra G90 inserted when nothing was converted.
        g90_count = sum(1 for l in out if l.command == "G90")
        assert g90_count == 1  # the original G90 passthrough

    def test_g91_moves_converted(self):
        """Relative moves become absolute; G91 lines are dropped."""
        src = "G90\nG1 X10 Y0\nG91\nG1 X5 Y3\nG1 X-2 Y1\n"
        out = gl.to_absolute_xy(_lines(src))
        # No G91 command should remain.
        assert not any(l.command == "G91" for l in out)
        moves = [l for l in out if l.is_move]
        assert moves[0].words["X"] == pytest.approx(10.0)
        assert moves[1].words["X"] == pytest.approx(15.0)
        assert moves[1].words["Y"] == pytest.approx(3.0)
        assert moves[2].words["X"] == pytest.approx(13.0)
        assert moves[2].words["Y"] == pytest.approx(4.0)

    def test_z_converted_too(self):
        """Z words are also converted to absolute in G91 sections."""
        src = "G91\nG1 Z0.2\nG1 Z0.2\n"
        out = gl.to_absolute_xy(_lines(src))
        moves = [l for l in out if l.is_move]
        assert moves[0].words["Z"] == pytest.approx(0.2)
        assert moves[1].words["Z"] == pytest.approx(0.4)

    def test_g90_prepended_when_g91_found(self):
        """G90 is prepended when any G91 line is dropped."""
        src = "G91\nG1 X5\n"
        out = gl.to_absolute_xy(_lines(src))
        assert out[0].command == "G90"

    def test_e_and_comments_preserved(self):
        """E words and comments are preserved verbatim."""
        src = "G90\nG1 X0\nG91\nG1 X5 E0.5 ; test\n"
        out = gl.to_absolute_xy(_lines(src))
        extruding = [l for l in out if l.is_move and "E" in l.words]
        assert extruding[0].words["E"] == pytest.approx(0.5)
        assert "; test" in extruding[0].comment

    def test_result_safe_for_apply_xy_transform(self):
        """Output can be passed directly to apply_xy_transform without error."""
        src = "G91\nG1 X5 Y5\nG1 X-2 Y3\n"
        out = gl.to_absolute_xy(_lines(src))
        # Must not raise ValueError about G91.
        shifted = gl.apply_xy_transform(out, lambda x, y: (x + 1, y + 1))
        assert len(shifted) > 0

    def test_mixed_sections(self):
        """Multiple G90/G91 mode switches are handled correctly."""
        src = "G90\nG1 X10\nG91\nG1 X2\nG90\nG1 X20\n"
        out = gl.to_absolute_xy(_lines(src))
        moves = [l for l in out if l.is_move]
        assert moves[0].words["X"] == pytest.approx(10.0)
        assert moves[1].words["X"] == pytest.approx(12.0)
        assert moves[2].words["X"] == pytest.approx(20.0)


# ===========================================================================
# §4.2 — translate_xy_allow_arcs
# ===========================================================================

class TestTranslateXYAllowArcs:
    def test_g1_translated(self):
        src = "G90\nG1 X10 Y20\n"
        out = gl.translate_xy_allow_arcs(_lines(src), dx=5.0, dy=-3.0)
        move = next(l for l in out if l.is_move)
        assert move.words["X"] == pytest.approx(15.0)
        assert move.words["Y"] == pytest.approx(17.0)

    def test_arc_endpoint_translated(self):
        src = "G90\nG1 X0 Y0\nG2 X10 Y0 I5 J0\n"
        out = gl.translate_xy_allow_arcs(_lines(src), dx=10.0, dy=5.0)
        arc = next(l for l in out if l.is_arc)
        assert arc.words["X"] == pytest.approx(20.0)
        assert arc.words["Y"] == pytest.approx(5.0)

    def test_arc_relative_ij_unchanged(self):
        """I/J (relative arc centre) are NOT modified for pure translation."""
        src = "G90\nG91.1\nG1 X0 Y0\nG2 X10 Y0 I5 J0\n"
        out = gl.translate_xy_allow_arcs(_lines(src), dx=10.0, dy=5.0)
        arc = next(l for l in out if l.is_arc)
        assert arc.words["I"] == pytest.approx(5.0)
        assert arc.words["J"] == pytest.approx(0.0)

    def test_arc_absolute_ij_shifted(self):
        """I/J in G90.1 (absolute arc centre) ARE shifted by (dx,dy)."""
        src = "G90\nG90.1\nG1 X0 Y0\nG2 X10 Y0 I5 J0\n"
        out = gl.translate_xy_allow_arcs(_lines(src), dx=3.0, dy=2.0)
        arc = next(l for l in out if l.is_arc)
        assert arc.words["I"] == pytest.approx(8.0)
        assert arc.words["J"] == pytest.approx(2.0)

    def test_g91_raises(self):
        src = "G91\nG1 X5 Y5\n"
        with pytest.raises(ValueError, match="G91"):
            gl.translate_xy_allow_arcs(_lines(src), dx=1.0, dy=1.0)

    def test_non_move_passthrough(self):
        src = "G90\nM82\nG28\nG1 X10 Y5\n"
        out = gl.translate_xy_allow_arcs(_lines(src), dx=0.0, dy=0.0)
        assert out[1].command == "M82"
        assert out[2].command == "G28"

    def test_zero_translation_identity(self):
        """dx=0, dy=0 must produce byte-identical X/Y values."""
        src = "G90\nG1 X12.345 Y-6.789\n"
        out = gl.translate_xy_allow_arcs(_lines(src), dx=0.0, dy=0.0)
        move = next(l for l in out if l.is_move)
        assert move.words["X"] == pytest.approx(12.345)
        assert move.words["Y"] == pytest.approx(-6.789)


# ===========================================================================
# §4.3 — OOBHit / find_oob_moves / max_oob_distance
# ===========================================================================

class TestOOBDetection:
    BED = _rect_bed(100.0, 100.0)

    def test_all_inside_no_hits(self):
        src = "G90\nG1 X10 Y10\nG1 X90 Y90\n"
        hits = gl.find_oob_moves(_lines(src), self.BED)
        assert hits == []

    def test_outside_point_detected(self):
        src = "G90\nG1 X110 Y50\n"
        hits = gl.find_oob_moves(_lines(src), self.BED)
        assert len(hits) == 1
        assert hits[0].x == pytest.approx(110.0)
        assert hits[0].y == pytest.approx(50.0)

    def test_distance_outside_correct(self):
        """Point 10 mm past the right edge should have distance ≈ 10."""
        src = "G90\nG1 X110 Y50\n"
        hits = gl.find_oob_moves(_lines(src), self.BED)
        assert hits[0].distance_outside == pytest.approx(10.0, abs=1e-3)

    def test_line_number_reported(self):
        src = "G90\nG1 X10 Y10\nG1 X-5 Y10\n"
        hits = gl.find_oob_moves(_lines(src), self.BED)
        assert len(hits) == 1
        assert hits[0].line_number == 2   # 0-indexed; G90 is 0, G1 X10 is 1

    def test_multiple_oob_hits(self):
        src = "G90\nG1 X-10 Y50\nG1 X50 Y110\n"
        hits = gl.find_oob_moves(_lines(src), self.BED)
        assert len(hits) == 2

    def test_max_oob_distance_inside(self):
        src = "G90\nG1 X50 Y50\n"
        assert gl.max_oob_distance(_lines(src), self.BED) == pytest.approx(0.0)

    def test_max_oob_distance_outside(self):
        src = "G90\nG1 X120 Y50\n"
        d = gl.max_oob_distance(_lines(src), self.BED)
        assert d == pytest.approx(20.0, abs=1e-3)

    def test_empty_lines_no_hits(self):
        hits = gl.find_oob_moves([], self.BED)
        assert hits == []

    def test_invalid_polygon_raises(self):
        src = "G90\nG1 X10 Y10\n"
        with pytest.raises(ValueError, match="at least 3 points"):
            gl.find_oob_moves(_lines(src), [])

    def test_max_oob_distance_invalid_polygon_raises(self):
        src = "G90\nG1 X10 Y10\n"
        with pytest.raises(ValueError, match="at least 3 points"):
            gl.max_oob_distance(_lines(src), [])


# ===========================================================================
# §4.4 — recenter_to_bed
# ===========================================================================

class TestRecenterToBed:
    def test_center_mode_moves_to_bed_center(self):
        # Print spans (0,0) to (20,10), centre at (10,5).
        # Bed 0–100 in X, 0–80 in Y, centre at (50,40).
        # Expected shift: dx=40, dy=35.
        src = "G90\nG1 X0 Y0\nG1 X20 Y10\n"
        out = gl.recenter_to_bed(
            _lines(src), 0.0, 100.0, 0.0, 80.0, mode="center"
        )
        bounds = gl.compute_bounds(out)
        assert bounds.center_x == pytest.approx(50.0, abs=0.01)
        assert bounds.center_y == pytest.approx(40.0, abs=0.01)

    def test_fit_mode_scales_to_bed(self):
        # Print 200×200, bed 100×100 → scale 0.5.
        src = (
            "G90\nG1 X0 Y0\nG1 X200 Y0\n"
            "G1 X200 Y200\nG1 X0 Y200\nG1 X0 Y0\n"
        )
        out = gl.recenter_to_bed(
            _lines(src), 0.0, 100.0, 0.0, 100.0, mode="fit"
        )
        bounds = gl.compute_bounds(out)
        assert bounds.width == pytest.approx(100.0, abs=0.01)
        assert bounds.height == pytest.approx(100.0, abs=0.01)

    def test_fit_mode_with_margin(self):
        src = "G90\nG1 X0 Y0\nG1 X100 Y100\n"
        out = gl.recenter_to_bed(
            _lines(src), 0.0, 200.0, 0.0, 200.0, margin=10.0, mode="fit"
        )
        bounds = gl.compute_bounds(out)
        # Available space is 200 - 2*10 = 180 mm; scaled print must fit.
        assert bounds.width <= 180.1
        assert bounds.height <= 180.1

    def test_center_mode_with_arcs_no_error(self):
        """Center mode uses translate_xy_allow_arcs; arcs are fine."""
        src = "G90\nG1 X0 Y0\nG2 X10 Y0 I5 J0\n"
        out = gl.recenter_to_bed(
            _lines(src), 0.0, 100.0, 0.0, 100.0, mode="center"
        )
        assert any(l.is_arc for l in out)

    def test_invalid_mode_raises(self):
        src = "G90\nG1 X0 Y0\n"
        with pytest.raises(ValueError, match="mode"):
            gl.recenter_to_bed(_lines(src), 0.0, 100.0, 0.0, 100.0, mode="zoom")

    def test_empty_lines_returns_empty(self):
        out = gl.recenter_to_bed([], 0.0, 100.0, 0.0, 100.0)
        assert out == []

    def test_fit_mode_zero_dimension_raises(self):
        """Print with zero width can't be fit-scaled."""
        src = "G90\nG1 X5 Y5\n"  # single point
        with pytest.raises(ValueError):
            gl.recenter_to_bed(_lines(src), 0.0, 100.0, 0.0, 100.0, mode="fit")


# ===========================================================================
# §4.5 — analyze_xy_transform
# ===========================================================================

class TestAnalyzeXYTransform:
    def test_identity_transform(self):
        src = "G90\nG1 X10 Y20\nG1 X30 Y40\n"
        result = gl.analyze_xy_transform(_lines(src), lambda x, y: (x, y))
        assert result["max_dx"] == pytest.approx(0.0)
        assert result["max_dy"] == pytest.approx(0.0)
        assert result["max_displacement"] == pytest.approx(0.0)
        assert result["move_count"] == 2

    def test_translation_analysis(self):
        src = "G90\nG1 X0 Y0\nG1 X10 Y5\n"
        result = gl.analyze_xy_transform(
            _lines(src), lambda x, y: (x + 3.0, y + 4.0)
        )
        assert result["max_dx"] == pytest.approx(3.0)
        assert result["max_dy"] == pytest.approx(4.0)
        assert result["max_displacement"] == pytest.approx(5.0)  # 3-4-5 triangle

    def test_no_moves_returns_minus_one(self):
        src = "G90\nM82\n; just a comment\n"
        result = gl.analyze_xy_transform(_lines(src), lambda x, y: (x, y))
        assert result["line_number"] == -1
        assert result["move_count"] == 0

    def test_worst_line_reported(self):
        """line_number should point to the move with the largest displacement."""
        src = "G90\nG1 X1 Y0\nG1 X100 Y0\n"
        # Skew grows with X.
        result = gl.analyze_xy_transform(
            _lines(src), lambda x, y: (x + x * 0.01, y)
        )
        # Second move (X=100) has larger displacement than first (X=1).
        assert result["line_number"] == 2  # 0-indexed; G90=0, G1 X1=1, G1 X100=2


# ===========================================================================
# §4.6 — iter_layers / apply_xy_transform_by_layer
# ===========================================================================

class TestIterLayers:
    def test_single_layer(self):
        src = "G90\nG1 Z0.2\nG1 X10 Y10\nG1 X20 Y20\n"
        layers = list(gl.iter_layers(_lines(src)))
        assert len(layers) == 2  # z=0 group + z=0.2 group

    def test_layer_z_values(self):
        src = "G90\nG1 Z0.2\nG1 X10\nG1 Z0.4\nG1 X20\n"
        layers = list(gl.iter_layers(_lines(src)))
        z_vals = [z for z, _ in layers]
        assert z_vals[0] == pytest.approx(0.0)
        assert 0.2 in [pytest.approx(z) for z in z_vals]
        assert 0.4 in [pytest.approx(z) for z in z_vals]

    def test_z_change_line_in_new_layer(self):
        """The G1 Z<new> line belongs to the NEW layer group."""
        src = "G90\nG1 X5\nG1 Z0.2\nG1 X10\n"
        layers = list(gl.iter_layers(_lines(src)))
        # Layer at z=0 should contain G1 X5, not G1 Z0.2.
        z0_layer = layers[0][1]
        z0_cmds = [l.raw for l in z0_layer if l.is_move]
        assert not any("Z0.2" in c or "Z.2" in c for c in z0_cmds)

    def test_all_lines_accounted_for(self):
        src = "G90\nG1 Z0.2\nG1 X10\nG1 Z0.4\nG1 X20\n; end\n"
        layers = list(gl.iter_layers(_lines(src)))
        total = sum(len(lns) for _, lns in layers)
        assert total == len(gl.parse_lines(src))

    def test_no_z_change_one_layer(self):
        src = "G90\nG1 X10 Y10\nG1 X20 Y20\n"
        layers = list(gl.iter_layers(_lines(src)))
        assert len(layers) == 1
        assert layers[0][0] == pytest.approx(0.0)


class TestApplyXYTransformByLayer:
    def test_all_layers_transformed_when_no_filter(self):
        src = "G90\nG1 Z0.2\nG1 X10 Y5\nG1 Z0.4\nG1 X10 Y5\n"
        out = gl.apply_xy_transform_by_layer(
            _lines(src), lambda x, y: (x + 1.0, y + 1.0)
        )
        moves = [l for l in out if l.is_move and "X" in l.words and "Z" not in l.words]
        for m in moves:
            assert m.words["X"] == pytest.approx(11.0)
            assert m.words["Y"] == pytest.approx(6.0)

    def test_z_range_filter(self):
        """Only moves in z_min..z_max are transformed."""
        src = "G90\nG1 Z0.2\nG1 X10 Y5\nG1 Z0.6\nG1 X10 Y5\n"
        out = gl.apply_xy_transform_by_layer(
            _lines(src),
            lambda x, y: (x + 99.0, y + 99.0),
            z_min=0.5,
            z_max=1.0,
        )
        moves = [l for l in out if l.is_move and "X" in l.words and "Z" not in l.words]
        # First layer (z=0.2) should be unchanged, second (z=0.6) transformed.
        assert moves[0].words["X"] == pytest.approx(10.0)
        assert moves[1].words["X"] == pytest.approx(109.0)

    def test_g91_raises(self):
        src = "G91\nG1 X5\n"
        with pytest.raises(ValueError, match="G91"):
            gl.apply_xy_transform_by_layer(
                _lines(src), lambda x, y: (x, y)
            )

    def test_non_move_lines_pass_through(self):
        src = "G90\n; setup\nM82\nG1 X10 Y5\n"
        out = gl.apply_xy_transform_by_layer(
            _lines(src), lambda x, y: (x, y)
        )
        assert out[1].comment == "; setup"
        assert out[2].command == "M82"


# ===========================================================================
# §5 — Presets
# ===========================================================================

class TestPresets:
    def test_printer_presets_exist(self):
        assert isinstance(gl.PRINTER_PRESETS, dict)
        assert len(gl.PRINTER_PRESETS) >= 1

    def test_coreone_preset(self):
        p = gl.PRINTER_PRESETS["COREONE"]
        assert p["bed_x"] == 250.0
        assert p["bed_y"] == 220.0
        assert p["max_z"] == 250.0

    def test_coreonel_preset(self):
        p = gl.PRINTER_PRESETS["COREONEL"]
        assert p["bed_x"] == 300.0
        assert p["bed_y"] == 300.0
        assert p["max_z"] == 330.0

    def test_all_printer_presets_have_required_keys(self):
        for name, preset in gl.PRINTER_PRESETS.items():
            assert "bed_x" in preset, f"{name} missing bed_x"
            assert "bed_y" in preset, f"{name} missing bed_y"
            assert "max_z" in preset, f"{name} missing max_z"

    def test_filament_presets_exist(self):
        assert isinstance(gl.FILAMENT_PRESETS, dict)
        assert len(gl.FILAMENT_PRESETS) >= 2

    def test_pla_preset(self):
        p = gl.FILAMENT_PRESETS["PLA"]
        assert p["hotend"] == 215
        assert p["bed"] == 60

    def test_all_filament_presets_have_required_keys(self):
        for name, preset in gl.FILAMENT_PRESETS.items():
            assert "hotend" in preset, f"{name} missing hotend"
            assert "bed"    in preset, f"{name} missing bed"
            assert "fan"    in preset, f"{name} missing fan"
            assert "retract" in preset, f"{name} missing retract"
            assert "temp_min" in preset, f"{name} missing temp_min"
            assert "temp_max" in preset, f"{name} missing temp_max"
            assert "speed" in preset, f"{name} missing speed"
            assert "enclosure" in preset, f"{name} missing enclosure"
            assert preset["temp_min"] < preset["temp_max"], (
                f"{name}: temp_min must be less than temp_max"
            )
            assert preset["temp_min"] <= preset["hotend"] <= preset["temp_max"], (
                f"{name}: hotend must be within temp_min..temp_max"
            )


# ===========================================================================
# §5.1 — detect_printer_preset
# ===========================================================================

class TestDetectPrinterPreset:
    def test_detect_coreone(self):
        lines = gl.parse_lines('G90\nM862.3 P "COREONE"\nG1 X10 Y10\n')
        assert gl.detect_printer_preset(lines) == "COREONE"

    def test_detect_coreonel(self):
        lines = gl.parse_lines('G90\nM862.3 P "COREONEL"\nG1 X10 Y10\n')
        assert gl.detect_printer_preset(lines) == "COREONEL"

    def test_detect_mk4(self):
        lines = gl.parse_lines('M862.3 P "MK4"\n')
        assert gl.detect_printer_preset(lines) == "MK4"

    def test_detect_mk4s_alias_maps_to_mk4_preset(self):
        lines = gl.parse_lines('M862.3 P "MK4S"\n')
        assert gl.detect_printer_preset(lines) == "MK4"

    def test_detect_without_quotes(self):
        lines = gl.parse_lines('M862.3 P COREONE\n')
        assert gl.detect_printer_preset(lines) == "COREONE"

    def test_detect_case_insensitive(self):
        lines = gl.parse_lines('M862.3 P "coreone"\n')
        assert gl.detect_printer_preset(lines) == "COREONE"

    def test_no_m862_returns_none(self):
        lines = gl.parse_lines("G90\nG1 X10 Y10\n")
        assert gl.detect_printer_preset(lines) is None

    def test_unknown_printer_returns_none(self):
        lines = gl.parse_lines('M862.3 P "UNKNOWNPRINTER"\n')
        assert gl.detect_printer_preset(lines) is None

    def test_empty_lines_returns_none(self):
        assert gl.detect_printer_preset([]) is None

    def test_other_m862_subcommands_ignored(self):
        """M862.1 (nozzle) and M862.5 (firmware) should not match."""
        lines = gl.parse_lines('M862.1 P0.6 A0 F0\nM862.5 P2\n')
        assert gl.detect_printer_preset(lines) is None

    def test_detect_in_realistic_gcode(self):
        """Detect preset from a realistic start-gcode snippet."""
        src = (
            "M17\n"
            'M862.1 P0.6 A0 F0\n'
            'M862.3 P "COREONE"\n'
            'M862.5 P2\n'
            'M862.6 P"Input shaper"\n'
            "M115 U6.3.4+10511\n"
        )
        lines = gl.parse_lines(src)
        assert gl.detect_printer_preset(lines) == "COREONE"


class TestDetectPrintVolume:
    def test_returns_volume_for_coreone(self):
        lines = gl.parse_lines('M862.3 P "COREONE"\n')
        vol = gl.detect_print_volume(lines)
        assert vol == {"bed_x": 250.0, "bed_y": 220.0, "max_z": 250.0, "max_nozzle_temp": 290.0, "max_bed_temp": 120.0}

    def test_returns_volume_for_coreonel(self):
        lines = gl.parse_lines('M862.3 P "COREONEL"\n')
        vol = gl.detect_print_volume(lines)
        assert vol == {"bed_x": 300.0, "bed_y": 300.0, "max_z": 330.0, "max_nozzle_temp": 290.0, "max_bed_temp": 120.0}

    def test_returns_none_when_no_printer(self):
        lines = gl.parse_lines("G90\nG1 X10 Y10\n")
        assert gl.detect_print_volume(lines) is None

    def test_returns_none_for_unknown_printer(self):
        lines = gl.parse_lines('M862.3 P "MYSTERY"\n')
        assert gl.detect_print_volume(lines) is None

    def test_returned_dict_is_a_copy(self):
        """Mutating the result must not change PRINTER_PRESETS."""
        lines = gl.parse_lines('M862.3 P "MK4"\n')
        vol = gl.detect_print_volume(lines)
        vol["bed_x"] = 9999.0
        assert gl.PRINTER_PRESETS["MK4"]["bed_x"] == 250.0

    def test_mk4s_alias_uses_mk4_dimensions(self):
        lines = gl.parse_lines('M862.3 P "MK4S"\n')
        vol = gl.detect_print_volume(lines)
        assert vol == {"bed_x": 250.0, "bed_y": 210.0, "max_z": 220.0, "max_nozzle_temp": 290.0, "max_bed_temp": 120.0}


# ===========================================================================
# §6 — render_template
# ===========================================================================

class TestRenderTemplate:
    def test_simple_substitution(self):
        assert gl.render_template("M104 S{temp}", {"temp": 215}) == "M104 S215"

    def test_multiple_placeholders(self):
        result = gl.render_template("{cmd} X{x} Y{y}", {"cmd": "G1", "x": 10, "y": 20})
        assert result == "G1 X10 Y20"

    def test_missing_key_left_unchanged(self):
        assert gl.render_template("{foo} bar", {}) == "{foo} bar"

    def test_uppercase_key_not_substituted(self):
        """Uppercase identifiers must be left alone (slicer conditionals)."""
        result = gl.render_template("{IF layer}", {"IF": "if"})
        assert "{IF layer}" in result or "IF" in result

    def test_slicer_conditional_preserved(self):
        tmpl = "{if layer_num == 0}G28{endif}"
        assert gl.render_template(tmpl, {"layer_num": 0}) == tmpl

    def test_value_converted_to_str(self):
        assert gl.render_template("{v}", {"v": 3.14}) == "3.14"

    def test_empty_variables(self):
        assert gl.render_template("hello {world}", {}) == "hello {world}"

    def test_stem_placeholder_for_slice_batch(self):
        result = gl.render_template("{stem}.gcode", {"stem": "model"})
        assert result == "model.gcode"

    def test_digits_in_key_name(self):
        assert gl.render_template("{layer2}", {"layer2": "x"}) == "x"


# ===========================================================================
# §7 — encode_thumbnail_comment_block
# ===========================================================================

class TestEncodeThumbnailCommentBlock:
    # Minimal 1×1 PNG (26 bytes).
    MINI_PNG = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
        b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    def test_output_contains_begin_end(self):
        block = gl.encode_thumbnail_comment_block(1, 1, self.MINI_PNG)
        assert "; thumbnail begin 1x1" in block
        assert "; thumbnail end" in block

    def test_size_field_is_b64_char_count(self):
        import base64
        b64 = base64.b64encode(self.MINI_PNG).decode("ascii")
        block = gl.encode_thumbnail_comment_block(16, 16, self.MINI_PNG)
        assert f"; thumbnail begin 16x16 {len(b64)}" in block

    def test_round_trip_data_preserved(self):
        """Parse the generated block back and verify the image data."""
        block = gl.encode_thumbnail_comment_block(8, 8, self.MINI_PNG)
        gf = gl.from_text(block)
        assert len(gf.thumbnails) == 1
        assert gf.thumbnails[0].data == self.MINI_PNG
        assert gf.thumbnails[0].width == 8
        assert gf.thumbnails[0].height == 8

    def test_format_code_is_png(self):
        block = gl.encode_thumbnail_comment_block(4, 4, self.MINI_PNG)
        gf = gl.from_text(block)
        assert gf.thumbnails[0].format_code == 0  # _IMG_PNG = 0

    def test_uses_thumbnail_keyword(self):
        """PNG should use the base 'thumbnail' keyword, not 'thumbnail_PNG'."""
        block = gl.encode_thumbnail_comment_block(4, 4, self.MINI_PNG)
        assert "; thumbnail begin" in block
        assert "thumbnail_PNG" not in block


# ===========================================================================
# §8 — read_bgcode / write_bgcode
# ===========================================================================

class TestReadWriteBgcode:
    """Tests that do not require the real Prusa binary format for decode.

    write_bgcode creates a valid bgcode from scratch; read_bgcode should
    be able to load it back (since it uses DEFLATE-none compression).
    """

    SIMPLE_GCODE = "G90\nG1 X10 Y20 Z0.2\nG1 X20 Y30 E1.0\n"

    def test_write_bgcode_returns_bytes(self):
        data = gl.write_bgcode(self.SIMPLE_GCODE)
        assert isinstance(data, bytes)

    def test_write_bgcode_starts_with_magic(self):
        data = gl.write_bgcode(self.SIMPLE_GCODE)
        assert data[:4] == b"GCDE"

    def test_read_bgcode_round_trip(self):
        data = gl.write_bgcode(self.SIMPLE_GCODE)
        gf = gl.read_bgcode(data)
        assert gf.source_format == "bgcode"
        text = gl.to_text(gf)
        # All original commands should survive.
        assert "G90" in text
        assert "X10" in text
        assert "X20" in text

    def test_write_bgcode_with_thumbnail(self):
        import base64
        # 1-byte payload thumbnail
        params = struct.pack("<HHH", 0, 16, 16)  # PNG
        thumb = gl.Thumbnail(params=params, data=b"\x89PNG fake", _raw_block=b"")
        data = gl.write_bgcode(self.SIMPLE_GCODE, thumbnails=[thumb])
        assert data[:4] == b"GCDE"

    def test_read_bgcode_with_thumbnail_round_trip(self):
        params = struct.pack("<HHH", 0, 8, 8)
        thumb = gl.Thumbnail(params=params, data=b"fakepng_data_here", _raw_block=b"")
        data = gl.write_bgcode(self.SIMPLE_GCODE, thumbnails=[thumb])
        gf = gl.read_bgcode(data)
        assert len(gf.thumbnails) == 1
        assert gf.thumbnails[0].width == 8
        assert gf.thumbnails[0].height == 8
        assert gf.thumbnails[0].data == b"fakepng_data_here"

    def test_read_bgcode_invalid_magic_raises(self):
        with pytest.raises(ValueError):
            gl.read_bgcode(b"NOTBGCODE\x00" * 10)

    def test_read_bgcode_too_short_raises(self):
        with pytest.raises(ValueError):
            gl.read_bgcode(b"GCD")  # too short


# ===========================================================================
# §9 — PrusaSlicer CLI data structures (no live executable needed)
# ===========================================================================

class TestPrusaSlicerDataStructures:
    def test_run_result_ok_property(self):
        r = gl.RunResult(cmd=["a"], returncode=0, stdout="", stderr="")
        assert r.ok is True

    def test_run_result_not_ok(self):
        r = gl.RunResult(cmd=["a"], returncode=1, stdout="", stderr="err")
        assert r.ok is False

    def test_slice_request_defaults(self):
        req = gl.SliceRequest(
            input_path="model.stl",
            output_path="out.gcode",
            config_ini=None,
        )
        assert req.printer_technology == "FFF"
        assert req.extra_args == []

    def test_prusaslicer_capabilities_fields(self):
        cap = gl.PrusaSlicerCapabilities(
            version_text="PrusaSlicer-2.8.0",
            has_export_gcode=True,
            has_load_config=True,
            has_help_fff=True,
            supports_binary_gcode=False,
            raw_help="...",
            raw_help_fff=None,
        )
        assert cap.version_text == "PrusaSlicer-2.8.0"
        assert cap.has_export_gcode is True
        assert cap.raw_help_fff is None


class TestSliceModelCommand:
    def test_includes_printer_technology_flag(self):
        from unittest.mock import patch

        req = gl.SliceRequest(
            input_path="model.stl",
            output_path="out.gcode",
            config_ini=None,
            printer_technology="SLA",
        )
        fake = gl.RunResult(cmd=[], returncode=0, stdout="", stderr="")
        with patch("gcode_lib._prusaslicer.run_prusaslicer", return_value=fake) as m:
            gl.slice_model("/fake/slicer", req)

        args = m.call_args[0][1]
        assert "--printer-technology" in args
        idx = args.index("--printer-technology")
        assert args[idx + 1] == "SLA"


class TestFindPrusaSlicerExecutable:
    def test_explicit_path_not_found_raises(self):
        with pytest.raises(FileNotFoundError, match="Explicit"):
            gl.find_prusaslicer_executable(explicit_path="/no/such/executable")

    def test_not_found_raises_file_not_found(self):
        """When PrusaSlicer is not installed, a FileNotFoundError is raised."""
        from unittest.mock import patch
        # Patch both shutil.which and os.path.isfile inside gcode_lib so that
        # no filesystem path appears to exist and which() finds nothing either.
        with patch("gcode_lib.shutil.which", return_value=None), \
             patch("gcode_lib.os.path.isfile", return_value=False):
            with pytest.raises(FileNotFoundError):
                gl.find_prusaslicer_executable()


# ===========================================================================
# Edge-case / audit gap tests
# ===========================================================================

# ---------------------------------------------------------------------------
# OOB detection — edge cases
# ---------------------------------------------------------------------------

RECT_BED = [(0, 0), (250, 0), (250, 220), (0, 220)]


class TestOOBEdgeCases:
    def test_empty_lines_returns_empty(self):
        assert gl.find_oob_moves([], RECT_BED) == []

    def test_no_moves_returns_empty(self):
        lines = gl.parse_lines("G28\nM104 S215\n; just a comment\n")
        assert gl.find_oob_moves(lines, RECT_BED) == []

    def test_all_in_bounds_returns_empty(self):
        lines = gl.parse_lines("G90\nG1 X10 Y10\nG1 X100 Y100\n")
        assert gl.find_oob_moves(lines, RECT_BED) == []

    def test_max_oob_all_in_bounds_returns_zero(self):
        lines = gl.parse_lines("G90\nG1 X10 Y10\nG1 X100 Y100\n")
        assert gl.max_oob_distance(lines, RECT_BED) == pytest.approx(0.0)

    def test_g91_mode_handled_correctly(self):
        """find_oob_moves must work in G91 relative mode, not just G90."""
        # Start at (240, 0), then move +20 in X → lands at (260, 0) → OOB
        lines = gl.parse_lines("G90\nG1 X240 Y0\nG91\nG1 X20 Y0\n")
        hits = gl.find_oob_moves(lines, RECT_BED)
        assert len(hits) == 1
        assert hits[0].x == pytest.approx(260.0)
        assert hits[0].distance_outside > 0.0

    def test_concave_polygon(self):
        """L-shaped (concave) polygon: point inside concavity is correctly OOB."""
        # L-shape: missing top-right quadrant
        l_shape = [
            (0, 0), (200, 0), (200, 100), (100, 100), (100, 200), (0, 200)
        ]
        # (150, 150) is inside the bounding box but in the missing quadrant
        lines = gl.parse_lines("G90\nG1 X150 Y150\n")
        hits = gl.find_oob_moves(lines, l_shape)
        assert len(hits) == 1

    def test_single_point_exactly_on_edge(self):
        """A point on the polygon edge should be treated as in-bounds (no OOB hit)."""
        # (0, 110) is on the left edge of the rectangle
        lines = gl.parse_lines("G90\nG1 X0 Y110\n")
        hits = gl.find_oob_moves(lines, RECT_BED)
        assert hits == []

    def test_points_on_right_and_top_edges_are_in_bounds(self):
        lines = gl.parse_lines("G90\nG1 X250 Y110\nG1 X120 Y220\n")
        assert gl.find_oob_moves(lines, RECT_BED) == []


# ---------------------------------------------------------------------------
# iter_layers — edge cases
# ---------------------------------------------------------------------------

class TestIterLayersEdgeCases:
    def test_no_z_moves_single_group(self):
        """File with no Z changes yields a single layer at Z=0."""
        lines = gl.parse_lines("G90\nG1 X10 Y10\nG1 X20 Y20\n")
        layers = list(gl.iter_layers(lines))
        assert len(layers) == 1
        z, group = layers[0]
        assert z == pytest.approx(0.0)
        assert len(group) == len(lines)

    def test_empty_input_yields_nothing(self):
        assert list(gl.iter_layers([])) == []

    def test_arc_with_z_triggers_layer_change(self):
        """A G2 arc with a Z word must trigger a new layer (advance_state fix)."""
        lines = gl.parse_lines("G90\nG1 X0 Y0 Z0.2\nG2 X10 Y0 Z0.4 I5 J0\nG1 X20 Y0\n")
        layers = list(gl.iter_layers(lines))
        z_heights = [z for z, _ in layers]
        assert 0.4 in [pytest.approx(z) for z in z_heights] or \
               any(abs(z - 0.4) < 1e-6 for z in z_heights)

    def test_duplicate_z_no_extra_group(self):
        """Two consecutive moves at the same Z must stay in the same layer."""
        lines = gl.parse_lines("G90\nG1 Z0.2\nG1 X10 Y10\nG1 Z0.2\nG1 X20 Y20\n")
        layers = list(gl.iter_layers(lines))
        # Second G1 Z0.2 is the same height → should not start a new layer
        assert len(layers) == 2  # layer 0 (Z=0) and layer 1 (Z=0.2)

    def test_initial_state_respected(self):
        """When initial_state has Z=1.0, the first group has z_height=1.0."""
        initial = gl.ModalState()
        initial.z = 1.0
        lines = gl.parse_lines("G90\nG1 X10 Y10\n")
        layers = list(gl.iter_layers(lines, initial_state=initial))
        assert layers[0][0] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# render_template — edge cases
# ---------------------------------------------------------------------------

class TestRenderTemplateEdgeCases:
    def test_numeric_suffix_in_key(self):
        """{var0} should be substituted — key starts with letter, contains digit."""
        result = gl.render_template("M104 S{temp0}", {"temp0": 215})
        assert result == "M104 S215"

    def test_underscore_in_key(self):
        result = gl.render_template("{hotend_temp}", {"hotend_temp": 240})
        assert result == "240"

    def test_missing_key_preserved(self):
        """Unknown {key} placeholders are left unchanged (no KeyError)."""
        result = gl.render_template("G1 X{x_pos} Y{y_pos}", {"x_pos": 10})
        assert result == "G1 X10 Y{y_pos}"

    def test_uppercase_key_not_substituted(self):
        """{TEMP} must not be substituted (uppercase, not matched by regex)."""
        result = gl.render_template("M104 S{TEMP}", {"TEMP": 215})
        assert result == "M104 S{TEMP}"

    def test_key_starting_with_digit_not_substituted(self):
        """{0var} must not be substituted (starts with digit)."""
        result = gl.render_template("X{0var}", {"0var": 99})
        assert result == "X{0var}"

    def test_empty_template(self):
        assert gl.render_template("", {}) == ""

    def test_no_placeholders_unchanged(self):
        gcode = "G28\nG90\nG1 X100 Y100\n"
        assert gl.render_template(gcode, {"x": 5}) == gcode

    def test_slicer_conditional_preserved(self):
        t = "{if layer_num == 0}M106 S0{endif}"
        assert gl.render_template(t, {}) == t

    def test_value_converted_to_str(self):
        """Numeric values are converted to str during substitution."""
        result = gl.render_template("{x}", {"x": 3.14})
        assert result == "3.14"


# ---------------------------------------------------------------------------
# analyze_xy_transform — edge cases
# ---------------------------------------------------------------------------

class TestAnalyzeXYTransformEdgeCases:
    def test_no_moves_returns_zeros(self):
        """File with no XY moves should return move_count=0 and zero displacement."""
        lines = gl.parse_lines("G28\nM104 S215\n; comment\n")
        info = gl.analyze_xy_transform(lines, lambda x, y: (x + 10, y + 10))
        assert info["move_count"] == 0
        assert info["max_displacement"] == pytest.approx(0.0)
        assert info["line_number"] == -1

    def test_empty_input(self):
        info = gl.analyze_xy_transform([], lambda x, y: (x, y))
        assert info["move_count"] == 0

    def test_identity_transform_zero_displacement(self):
        lines = gl.parse_lines("G90\nG1 X50 Y100\nG1 X150 Y50\n")
        info = gl.analyze_xy_transform(lines, lambda x, y: (x, y))
        assert info["max_displacement"] == pytest.approx(0.0)
        assert info["move_count"] == 2


# ---------------------------------------------------------------------------
# recenter_to_bed — edge cases
# ---------------------------------------------------------------------------

class TestRecenterToBedEdgeCases:
    def test_print_larger_than_bed_fit_mode_shrinks(self):
        """fit mode must scale the print down when it exceeds the bed."""
        # 300 mm wide print on 250 mm bed with 0 margin
        lines = gl.parse_lines(
            "G90\nG1 X0 Y0\nG1 X300 Y0\nG1 X300 Y100\nG1 X0 Y100\nG1 X0 Y0\n"
        )
        result = gl.recenter_to_bed(
            lines, 0, 250, 0, 220, margin=0.0, mode="fit"
        )
        bounds = gl.compute_bounds(result)
        assert bounds.width <= 250.01
        assert bounds.height <= 220.01

    def test_zero_margin_uses_full_bed(self):
        lines = gl.parse_lines("G90\nG1 X50 Y50\nG1 X100 Y100\n")
        result = gl.recenter_to_bed(lines, 0, 200, 0, 200, margin=0.0, mode="center")
        bounds = gl.compute_bounds(result)
        assert bounds.center_x == pytest.approx(100.0, abs=0.5)
        assert bounds.center_y == pytest.approx(100.0, abs=0.5)

    def test_already_centred_noop(self):
        """A print already at the bed centre should move negligibly."""
        lines = gl.parse_lines("G90\nG1 X75 Y85\nG1 X125 Y135\n")
        result = gl.recenter_to_bed(lines, 0, 200, 0, 220, margin=0.0, mode="center")
        b_before = gl.compute_bounds(lines)
        b_after  = gl.compute_bounds(result)
        assert b_after.center_x == pytest.approx(100.0, abs=0.5)
        assert b_after.center_y == pytest.approx(110.0, abs=0.5)
        assert b_after.width == pytest.approx(b_before.width, abs=0.01)

    def test_fit_mode_linearizes_arcs(self):
        """fit mode should output G1-only geometry (arcs consumed during scaling)."""
        lines = gl.parse_lines("G90\nG1 X0 Y0\nG3 X10 Y0 I5 J0")
        result = gl.recenter_to_bed(lines, 0, 40, 0, 40, mode="fit", skip_negative_y=False)
        assert all(not ln.is_arc for ln in result)


# ---------------------------------------------------------------------------
# slice_batch — edge cases
# ---------------------------------------------------------------------------

class TestRunPrusaSlicerErrors:
    def test_timeout_raises_runtime_error(self):
        from unittest.mock import patch
        with patch("gcode_lib.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["fake"], timeout=10)):
            with pytest.raises(RuntimeError, match="timed out"):
                gl.run_prusaslicer("/fake/slicer", ["--help"], timeout_s=10)

    def test_os_error_raises_runtime_error(self):
        from unittest.mock import patch
        with patch("gcode_lib.subprocess.run", side_effect=OSError("No such file")):
            with pytest.raises(RuntimeError, match="Cannot run"):
                gl.run_prusaslicer("/fake/slicer", ["--help"])

    def test_stdin_devnull(self):
        """stdin must be DEVNULL to prevent interactive prompts from blocking."""
        from unittest.mock import patch, MagicMock
        fake_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("gcode_lib.subprocess.run", return_value=fake_result) as mock_run:
            gl.run_prusaslicer("/fake/slicer", ["--help"])
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["stdin"] is subprocess.DEVNULL


class TestProbePrusaSlicerCapabilitiesErrors:
    def test_timeout_raises_runtime_error(self):
        from unittest.mock import patch
        with patch("gcode_lib.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["fake"], timeout=30)):
            with pytest.raises(RuntimeError, match="timed out"):
                gl.probe_prusaslicer_capabilities("/fake/slicer")

    def test_os_error_raises_runtime_error(self):
        from unittest.mock import patch
        with patch("gcode_lib.subprocess.run", side_effect=OSError("Permission denied")):
            with pytest.raises(RuntimeError, match="Cannot run"):
                gl.probe_prusaslicer_capabilities("/fake/slicer")


class TestSliceBatchEdgeCases:
    def test_empty_inputs_returns_empty_list(self):
        from unittest.mock import patch
        with patch("gcode_lib.shutil.which", return_value=None), \
             patch("gcode_lib.os.path.isfile", return_value=False):
            # exe doesn't matter — empty input list is checked before any slicing
            results = gl.slice_batch(
                exe="/fake/slicer",
                inputs=[],
                output_dir="/tmp",
                config_ini=None,
            )
        assert results == []
