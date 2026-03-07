"""Tests for slicer helper utilities: extrusion detection, dimensions, presets, filenames."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gcode_lib as gl


# ===========================================================================
# is_extrusion_move
# ===========================================================================


def test_is_extrusion_move_g1_with_e_and_xy():
    line = gl.parse_line("G1 X10 Y20 E1.5")
    assert gl.is_extrusion_move(line) is True


def test_is_extrusion_move_g1_with_e_and_x_only():
    line = gl.parse_line("G1 X10 E1.5")
    assert gl.is_extrusion_move(line) is True


def test_is_extrusion_move_g1_with_e_and_y_only():
    line = gl.parse_line("G1 Y20 E1.5")
    assert gl.is_extrusion_move(line) is True


def test_is_extrusion_move_false_for_g0():
    line = gl.parse_line("G0 X10 Y20 E1.5")
    assert gl.is_extrusion_move(line) is False


def test_is_extrusion_move_false_for_retract_only():
    """G1 with only E (no X or Y) is a retraction, not an extrusion move."""
    line = gl.parse_line("G1 E-0.8")
    assert gl.is_extrusion_move(line) is False


def test_is_extrusion_move_false_without_e():
    line = gl.parse_line("G1 X10 Y20")
    assert gl.is_extrusion_move(line) is False


def test_is_extrusion_move_false_for_z_only():
    line = gl.parse_line("G1 Z0.3 E0.5")
    assert gl.is_extrusion_move(line) is False


# ===========================================================================
# derive_slicer_dimensions
# ===========================================================================


def test_derive_slicer_dimensions_04():
    lh, ew = gl.derive_slicer_dimensions(0.4)
    assert lh == pytest.approx(0.2)
    assert ew == pytest.approx(0.45)


def test_derive_slicer_dimensions_06():
    lh, ew = gl.derive_slicer_dimensions(0.6)
    assert lh == pytest.approx(0.3)
    assert ew == pytest.approx(0.67)


def test_derive_slicer_dimensions_08():
    lh, ew = gl.derive_slicer_dimensions(0.8)
    assert lh == pytest.approx(0.4)
    assert ew == pytest.approx(0.9)


# ===========================================================================
# flow_to_feedrate
# ===========================================================================


def test_flow_to_feedrate_math():
    # 10 / (0.2 * 0.45) * 60 = 6666.666...
    result = gl.flow_to_feedrate(10.0, 0.2, 0.45)
    assert result == pytest.approx(6666.67, rel=1e-4)


def test_flow_to_feedrate_different_values():
    # 5 / (0.3 * 0.68) * 60 = 1470.588...
    result = gl.flow_to_feedrate(5.0, 0.3, 0.68)
    assert result == pytest.approx(5.0 / (0.3 * 0.68) * 60.0)


# ===========================================================================
# resolve_filament_preset
# ===========================================================================


def test_resolve_preset_pla():
    result = gl.resolve_filament_preset("PLA")
    assert result["nozzle_temp"] == 215
    assert result["bed_temp"] == 60
    assert result["fan_speed"] == 100


def test_resolve_preset_explicit_overrides():
    result = gl.resolve_filament_preset(
        "PLA", nozzle_temp=200, bed_temp=50, fan_speed=80
    )
    assert result["nozzle_temp"] == 200
    assert result["bed_temp"] == 50
    assert result["fan_speed"] == 80


def test_resolve_preset_partial_override():
    result = gl.resolve_filament_preset("PLA", nozzle_temp=200)
    assert result["nozzle_temp"] == 200
    assert result["bed_temp"] == 60  # from preset
    assert result["fan_speed"] == 100  # from preset


def test_resolve_preset_unknown_type_defaults():
    result = gl.resolve_filament_preset("UNKNOWN_MATERIAL")
    assert result["nozzle_temp"] == 210
    assert result["bed_temp"] == 60
    assert result["fan_speed"] == 100


def test_resolve_preset_case_insensitive():
    result = gl.resolve_filament_preset("pla")
    assert result["nozzle_temp"] == 215


# ===========================================================================
# gcode_ext
# ===========================================================================


def test_gcode_ext_binary():
    assert gl.gcode_ext(binary=True) == ".bgcode"


def test_gcode_ext_ascii():
    assert gl.gcode_ext(binary=False) == ".gcode"


def test_gcode_ext_default_is_binary():
    assert gl.gcode_ext() == ".bgcode"


# ===========================================================================
# unique_suffix
# ===========================================================================


def test_unique_suffix_length():
    suffix = gl.unique_suffix()
    assert len(suffix) == 5


def test_unique_suffix_is_hex():
    suffix = gl.unique_suffix()
    assert re.fullmatch(r"[0-9a-f]{5}", suffix)


def test_unique_suffix_varies():
    """Two calls should produce different values (statistically)."""
    a = gl.unique_suffix()
    b = gl.unique_suffix()
    assert a != b


# ===========================================================================
# safe_filename_part
# ===========================================================================


def test_safe_filename_normal_passthrough():
    assert gl.safe_filename_part("PLA") == "PLA"


def test_safe_filename_strips_slash():
    assert "/" not in gl.safe_filename_part("path/part")


def test_safe_filename_strips_backslash():
    assert "\\" not in gl.safe_filename_part("path\\part")


def test_safe_filename_strips_dotdot():
    assert ".." not in gl.safe_filename_part("../etc/passwd")


def test_safe_filename_strips_null():
    assert "\x00" not in gl.safe_filename_part("bad\x00name")


def test_safe_filename_empty_returns_unknown():
    assert gl.safe_filename_part("") == "unknown"
