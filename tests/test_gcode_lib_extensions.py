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
        params = struct.pack("<HHH", 16, 16, 0)  # PNG
        thumb = gl.Thumbnail(params=params, data=b"\x89PNG fake", _raw_block=b"")
        data = gl.write_bgcode(self.SIMPLE_GCODE, thumbnails=[thumb])
        assert data[:4] == b"GCDE"

    def test_read_bgcode_with_thumbnail_round_trip(self):
        params = struct.pack("<HHH", 8, 8, 0)
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
