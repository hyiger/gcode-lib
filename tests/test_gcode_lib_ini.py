"""Tests for PrusaSlicer INI parsing and editing utilities."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gcode_lib as gl


# ===========================================================================
# _ini_first_value
# ===========================================================================


def test_ini_first_value_single():
    assert gl._ini_first_value("0.4") == "0.4"


def test_ini_first_value_semicolon_delimited():
    assert gl._ini_first_value("0.4;0.4") == "0.4"


def test_ini_first_value_strips_whitespace():
    assert gl._ini_first_value("  0.6 ; 0.6 ") == "0.6"


def test_ini_first_value_empty():
    assert gl._ini_first_value("") == ""


# ===========================================================================
# _ini_parse_float
# ===========================================================================


def test_ini_parse_float_basic():
    assert gl._ini_parse_float("0.4") == pytest.approx(0.4)


def test_ini_parse_float_semicolon_delimited():
    assert gl._ini_parse_float("0.4;0.4") == pytest.approx(0.4)


def test_ini_parse_float_failure():
    assert gl._ini_parse_float("abc") is None


def test_ini_parse_float_empty():
    assert gl._ini_parse_float("") is None


# ===========================================================================
# _ini_parse_int
# ===========================================================================


def test_ini_parse_int_whole():
    assert gl._ini_parse_int("215") == 215


def test_ini_parse_int_truncates_decimal():
    assert gl._ini_parse_int("215.7") == 215


def test_ini_parse_int_failure():
    assert gl._ini_parse_int("abc") is None


def test_ini_parse_int_empty():
    assert gl._ini_parse_int("") is None


# ===========================================================================
# _ini_parse_extrusion_width
# ===========================================================================


def test_extrusion_width_zero_is_auto():
    assert gl._ini_parse_extrusion_width("0") is None


def test_extrusion_width_empty_is_auto():
    assert gl._ini_parse_extrusion_width("") is None


def test_extrusion_width_percentage_ignored():
    assert gl._ini_parse_extrusion_width("105%") is None


def test_extrusion_width_negative_ignored():
    assert gl._ini_parse_extrusion_width("-0.5") is None


def test_extrusion_width_positive_float():
    assert gl._ini_parse_extrusion_width("0.45") == pytest.approx(0.45)


# ===========================================================================
# _ini_parse_bed_shape
# ===========================================================================


def test_bed_shape_standard_rectangle():
    assert gl._ini_parse_bed_shape("0x0,250x0,250x220,0x220") == "125,110"


def test_bed_shape_malformed_returns_none():
    assert gl._ini_parse_bed_shape("garbage") is None


def test_bed_shape_empty_returns_none():
    assert gl._ini_parse_bed_shape("") is None


# ===========================================================================
# parse_prusaslicer_ini — full parser
# ===========================================================================


def test_parse_ini_basic_flat_file(tmp_path):
    ini = tmp_path / "test.ini"
    ini.write_text(
        "nozzle_diameter = 0.4\n"
        "temperature = 215\n"
        "bed_temperature = 60\n"
        "max_fan_speed = 100\n"
        "layer_height = 0.2\n"
    )
    result = gl.parse_prusaslicer_ini(str(ini))
    assert result["nozzle_diameter"] == pytest.approx(0.4)
    assert result["nozzle_temp"] == 215
    assert result["bed_temp"] == 60
    assert result["fan_speed"] == 100
    assert result["layer_height"] == pytest.approx(0.2)


def test_parse_ini_with_section_headers(tmp_path):
    ini = tmp_path / "test.ini"
    ini.write_text(
        "[print]\n"
        "layer_height = 0.3\n"
        "[filament]\n"
        "temperature = 240\n"
    )
    result = gl.parse_prusaslicer_ini(str(ini))
    assert result["layer_height"] == pytest.approx(0.3)
    assert result["nozzle_temp"] == 240


def test_parse_ini_semicolon_delimited_values(tmp_path):
    ini = tmp_path / "test.ini"
    ini.write_text("nozzle_diameter = 0.4;0.4\n")
    result = gl.parse_prusaslicer_ini(str(ini))
    assert result["nozzle_diameter"] == pytest.approx(0.4)


def test_parse_ini_temp_fallback_first_layer(tmp_path):
    """Uses first_layer_temperature when temperature is missing."""
    ini = tmp_path / "test.ini"
    ini.write_text("first_layer_temperature = 220\n")
    result = gl.parse_prusaslicer_ini(str(ini))
    assert result["nozzle_temp"] == 220


def test_parse_ini_bed_temp_fallback_first_layer(tmp_path):
    """Uses first_layer_bed_temperature when bed_temperature is missing."""
    ini = tmp_path / "test.ini"
    ini.write_text("first_layer_bed_temperature = 70\n")
    result = gl.parse_prusaslicer_ini(str(ini))
    assert result["bed_temp"] == 70


def test_parse_ini_extrusion_width_auto_omitted(tmp_path):
    """Extrusion width '0' (auto) is not included in result."""
    ini = tmp_path / "test.ini"
    ini.write_text("extrusion_width = 0\n")
    result = gl.parse_prusaslicer_ini(str(ini))
    assert "extrusion_width" not in result


def test_parse_ini_extrusion_width_explicit(tmp_path):
    ini = tmp_path / "test.ini"
    ini.write_text("extrusion_width = 0.45\n")
    result = gl.parse_prusaslicer_ini(str(ini))
    assert result["extrusion_width"] == pytest.approx(0.45)


def test_parse_ini_extrusion_width_percentage_omitted(tmp_path):
    ini = tmp_path / "test.ini"
    ini.write_text("extrusion_width = 105%\n")
    result = gl.parse_prusaslicer_ini(str(ini))
    assert "extrusion_width" not in result


def test_parse_ini_bed_shape_to_bed_center(tmp_path):
    ini = tmp_path / "test.ini"
    ini.write_text("bed_shape = 0x0,250x0,250x220,0x220\n")
    result = gl.parse_prusaslicer_ini(str(ini))
    assert result["bed_center"] == "125,110"


def test_parse_ini_printer_model(tmp_path):
    ini = tmp_path / "test.ini"
    ini.write_text("printer_model = MK4S\n")
    result = gl.parse_prusaslicer_ini(str(ini))
    assert result["printer_model"] == "MK4S"


def test_parse_ini_filament_type(tmp_path):
    ini = tmp_path / "test.ini"
    ini.write_text("filament_type = PETG\n")
    result = gl.parse_prusaslicer_ini(str(ini))
    assert result["filament_type"] == "PETG"


def test_parse_ini_missing_file_returns_empty_dict(tmp_path):
    missing = tmp_path / "missing.ini"
    assert gl.parse_prusaslicer_ini(str(missing)) == {}


def test_parse_ini_missing_keys_empty_dict(tmp_path):
    ini = tmp_path / "test.ini"
    ini.write_text("# nothing relevant here\n")
    result = gl.parse_prusaslicer_ini(str(ini))
    assert result == {}


def test_parse_ini_invalid_temp_omitted(tmp_path):
    """Non-numeric temperature value should be omitted."""
    ini = tmp_path / "test.ini"
    ini.write_text("temperature = hot\n")
    result = gl.parse_prusaslicer_ini(str(ini))
    assert "nozzle_temp" not in result


def test_parse_ini_section_overrides_default(tmp_path):
    """Named section values must override [DEFAULT] values."""
    ini = tmp_path / "test.ini"
    ini.write_text(
        "[DEFAULT]\n"
        "temperature = 200\n"
        "[filament]\n"
        "temperature = 220\n"
    )
    result = gl.parse_prusaslicer_ini(str(ini))
    assert result["nozzle_temp"] == 220


def test_parse_ini_section_override_survives_later_section(tmp_path):
    """A section override must not be reset by a later section that inherits DEFAULT."""
    ini = tmp_path / "test.ini"
    ini.write_text(
        "[DEFAULT]\n"
        "temperature = 200\n"
        "[filament]\n"
        "temperature = 220\n"
        "[print]\n"
        "layer_height = 0.3\n"
    )
    result = gl.parse_prusaslicer_ini(str(ini))
    assert result["nozzle_temp"] == 220
    assert result["layer_height"] == pytest.approx(0.3)


def test_parse_ini_later_section_explicit_default_value(tmp_path):
    """A later section explicitly setting a key to DEFAULT value must override earlier sections."""
    ini = tmp_path / "test.ini"
    ini.write_text(
        "[DEFAULT]\n"
        "temperature = 200\n"
        "[filament]\n"
        "temperature = 220\n"
        "[print]\n"
        "temperature = 200\n"
    )
    result = gl.parse_prusaslicer_ini(str(ini))
    assert result["nozzle_temp"] == 200


# ===========================================================================
# replace_ini_value
# ===========================================================================


def test_replace_ini_value_existing_key():
    lines = ["nozzle_diameter = 0.4", "layer_height = 0.2"]
    result, found = gl.replace_ini_value(lines, "layer_height", "0.3")
    assert found is True
    assert result == ["nozzle_diameter = 0.4", "layer_height = 0.3"]


def test_replace_ini_value_preserves_whitespace():
    lines = ["layer_height  =  0.2"]
    result, found = gl.replace_ini_value(lines, "layer_height", "0.3")
    assert found is True
    assert result[0] == "layer_height  =  0.3"


def test_replace_ini_value_not_found():
    lines = ["nozzle_diameter = 0.4"]
    result, found = gl.replace_ini_value(lines, "missing_key", "42")
    assert found is False
    assert result == lines


def test_replace_ini_value_only_first_occurrence():
    lines = [
        "temperature = 200",
        "temperature = 210",
    ]
    result, found = gl.replace_ini_value(lines, "temperature", "220")
    assert found is True
    assert result[0] == "temperature = 220"
    assert result[1] == "temperature = 210"


def test_replace_ini_value_preserves_line_ending():
    lines = ["bed_temperature = 60\n"]
    result, found = gl.replace_ini_value(lines, "bed_temperature", "80")
    assert found is True
    assert result == ["bed_temperature = 80\n"]


# ===========================================================================
# pa_command
# ===========================================================================


def test_pa_command_default_coreone():
    assert gl.pa_command(0.04) == "M572 S0.0400"


def test_pa_command_mini():
    assert gl.pa_command(0.04, "MINI") == "M900 K0.0400"


def test_pa_command_case_insensitive():
    assert gl.pa_command(0.04, "mini") == "M900 K0.0400"


def test_pa_command_non_mini_uses_m572():
    assert gl.pa_command(0.05, "MK4S") == "M572 S0.0500"


# ===========================================================================
# inject_pa_into_start_gcode
# ===========================================================================


def test_inject_pa_replaces_existing_m572():
    lines = [
        "some_setting = value",
        "start_filament_gcode = M572 S0.0100\\nG92 E0",
        "other = 1",
    ]
    result = gl.inject_pa_into_start_gcode(lines, 0.04)
    assert "M572 S0.0400" in result[1]
    assert "M572 S0.0100" not in result[1]


def test_inject_pa_replaces_existing_m900():
    lines = [
        "start_filament_gcode = M900 K0.0100\\nG92 E0",
    ]
    result = gl.inject_pa_into_start_gcode(lines, 0.05, "MINI")
    assert "M900 K0.0500" in result[0]
    assert "M900 K0.0100" not in result[0]


def test_inject_pa_prepends_when_no_pa_command():
    lines = [
        "start_filament_gcode = G92 E0",
    ]
    result = gl.inject_pa_into_start_gcode(lines, 0.04)
    assert result[0].startswith("start_filament_gcode = M572 S0.0400\\nG92 E0")


def test_inject_pa_handles_quoted_values():
    lines = [
        'start_filament_gcode = "M572 S0.01\\nG92 E0"',
    ]
    result = gl.inject_pa_into_start_gcode(lines, 0.04)
    assert "M572 S0.0400" in result[0]
    assert result[0].strip().endswith('"')


def test_inject_pa_appends_when_key_missing():
    lines = [
        "some_other_setting = value",
    ]
    result = gl.inject_pa_into_start_gcode(lines, 0.04)
    assert len(result) == 2
    assert result[1] == "start_filament_gcode = M572 S0.0400"


# ---------------------------------------------------------------------------
# parse_prusaslicer_ini — nozzle flags
# ---------------------------------------------------------------------------


def test_parse_ini_nozzle_high_flow_true(tmp_path):
    ini = tmp_path / "test.ini"
    ini.write_text("nozzle_high_flow = 1\n")
    result = gl.parse_prusaslicer_ini(str(ini))
    assert result["nozzle_high_flow"] is True


def test_parse_ini_nozzle_high_flow_false(tmp_path):
    ini = tmp_path / "test.ini"
    ini.write_text("nozzle_high_flow = 0\n")
    result = gl.parse_prusaslicer_ini(str(ini))
    assert result["nozzle_high_flow"] is False


def test_parse_ini_nozzle_hardened_true(tmp_path):
    ini = tmp_path / "test.ini"
    ini.write_text("filament_abrasive = 1\n")
    result = gl.parse_prusaslicer_ini(str(ini))
    assert result["nozzle_hardened"] is True


def test_parse_ini_nozzle_hardened_false(tmp_path):
    ini = tmp_path / "test.ini"
    ini.write_text("filament_abrasive = 0\n")
    result = gl.parse_prusaslicer_ini(str(ini))
    assert result["nozzle_hardened"] is False


def test_parse_ini_nozzle_flags_missing(tmp_path):
    ini = tmp_path / "test.ini"
    ini.write_text("temperature = 210\n")
    result = gl.parse_prusaslicer_ini(str(ini))
    assert "nozzle_high_flow" not in result
    assert "nozzle_hardened" not in result
