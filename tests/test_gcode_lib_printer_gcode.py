"""Tests for §14 Printer G-code Templates.

Covers:
  KNOWN_PRINTERS constant
  MBL_TEMP constant
  PrinterGCode dataclass
  resolve_printer
  compute_bed_center
  compute_bed_shape
  compute_m555
  render_start_gcode
  render_end_gcode
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gcode_lib as gl


# ---------------------------------------------------------------------------
# KNOWN_PRINTERS
# ---------------------------------------------------------------------------

class TestKnownPrinters:
    def test_is_tuple(self):
        assert isinstance(gl.KNOWN_PRINTERS, tuple)

    def test_contains_expected_printers(self):
        assert gl.KNOWN_PRINTERS == ("COREONE", "COREONEL", "MK4S", "MINI", "XL")


# ---------------------------------------------------------------------------
# MBL_TEMP
# ---------------------------------------------------------------------------

class TestMblTemp:
    def test_value(self):
        assert gl.MBL_TEMP == 170


# ---------------------------------------------------------------------------
# PrinterGCode dataclass
# ---------------------------------------------------------------------------

class TestPrinterGCode:
    def test_has_start_and_end_fields(self):
        pgc = gl.PrinterGCode(start="start-gcode", end="end-gcode")
        assert pgc.start == "start-gcode"
        assert pgc.end == "end-gcode"


# ---------------------------------------------------------------------------
# resolve_printer
# ---------------------------------------------------------------------------

class TestResolvePrinter:
    def test_passthrough_coreone(self):
        assert gl.resolve_printer("COREONE") == "COREONE"

    def test_case_insensitive(self):
        assert gl.resolve_printer("coreone") == "COREONE"

    def test_alias_mk4_lower(self):
        assert gl.resolve_printer("mk4") == "MK4S"

    def test_alias_mk4_upper(self):
        assert gl.resolve_printer("MK4") == "MK4S"

    def test_unknown_raises_valueerror(self):
        with pytest.raises(ValueError, match="unknown printer"):
            gl.resolve_printer("UNKNOWN")

    def test_mini_passthrough(self):
        assert gl.resolve_printer("MINI") == "MINI"


# ---------------------------------------------------------------------------
# compute_bed_center
# ---------------------------------------------------------------------------

class TestComputeBedCenter:
    def test_coreone(self):
        # 250/2=125, 220/2=110
        assert gl.compute_bed_center("COREONE") == "125,110"

    def test_mini(self):
        # 180/2=90, 180/2=90
        assert gl.compute_bed_center("MINI") == "90,90"

    def test_unknown_fallback(self):
        assert gl.compute_bed_center("UNKNOWN_PRINTER") == "125,110"


# ---------------------------------------------------------------------------
# compute_bed_shape
# ---------------------------------------------------------------------------

class TestComputeBedShape:
    def test_coreone(self):
        assert gl.compute_bed_shape("COREONE") == "0x0,250x0,250x220,0x220"

    def test_mini(self):
        assert gl.compute_bed_shape("MINI") == "0x0,180x0,180x180,0x180"

    def test_unknown_fallback(self):
        assert gl.compute_bed_shape("UNKNOWN_PRINTER") == "0x0,250x0,250x220,0x220"


# ---------------------------------------------------------------------------
# compute_m555
# ---------------------------------------------------------------------------

class TestComputeM555:
    def test_centered_model(self):
        result = gl.compute_m555("125,110", 40, 40)
        assert result == {
            "m555_x": 105,
            "m555_y": 90,
            "m555_w": 40,
            "m555_h": 40,
        }


# ---------------------------------------------------------------------------
# render_start_gcode
# ---------------------------------------------------------------------------

class TestRenderStartGCode:
    def _render(self, *, cool_fan: bool = True) -> str:
        return gl.render_start_gcode(
            "COREONE",
            nozzle_dia=0.4,
            bed_temp=60,
            hotend_temp=215,
            bed_center="125,110",
            model_width=40,
            model_depth=40,
            cool_fan=cool_fan,
        )

    def test_contains_printer_model_check(self):
        out = self._render()
        assert 'M862.3 P "COREONE"' in out

    def test_contains_bed_temp(self):
        out = self._render()
        assert "M140 S60" in out

    def test_cool_fan_true_emits_m106(self):
        out = self._render(cool_fan=True)
        assert "M106 S255" in out

    def test_cool_fan_false_no_m106(self):
        out = self._render(cool_fan=False)
        assert "M106 S255" not in out

    def test_mbl_temp_clamped(self):
        # hotend_temp=215 > MBL_TEMP=170 → mbl_temp=170
        out = self._render()
        assert "M109 R170" in out

    def test_mbl_temp_not_clamped_when_lower(self):
        # hotend_temp=150 < MBL_TEMP=170 → mbl_temp=150
        out = gl.render_start_gcode(
            "COREONE",
            nozzle_dia=0.4,
            bed_temp=60,
            hotend_temp=150,
            bed_center="125,110",
            model_width=40,
            model_depth=40,
        )
        assert "M109 R150" in out

    def test_contains_m555(self):
        out = self._render()
        assert "M555 X105 Y90 W40 H40" in out

    def test_contains_hotend_temp(self):
        out = self._render()
        assert "M109 S215" in out

    def test_alias_mk4_matches_mk4s_output(self):
        out_alias = gl.render_start_gcode(
            "MK4",
            nozzle_dia=0.4,
            bed_temp=60,
            hotend_temp=215,
            bed_center="125,110",
            model_width=40,
            model_depth=40,
        )
        out_canonical = gl.render_start_gcode(
            "MK4S",
            nozzle_dia=0.4,
            bed_temp=60,
            hotend_temp=215,
            bed_center="125,110",
            model_width=40,
            model_depth=40,
        )
        assert out_alias == out_canonical


# ---------------------------------------------------------------------------
# render_end_gcode
# ---------------------------------------------------------------------------

class TestRenderEndGCode:
    def test_park_z_offset(self):
        out = gl.render_end_gcode("COREONE", max_layer_z=50.0)
        # park_z = 50 + 10 = 60.0
        assert "Z60.0" in out

    def test_max_layer_z_comment(self):
        out = gl.render_end_gcode("COREONE", max_layer_z=50.0)
        assert "max_layer_z = 50.00" in out

    def test_park_z_capped_at_max_z(self):
        # COREONE max_z=250.  With max_layer_z=245, park_z=255 → capped to 250
        out = gl.render_end_gcode("COREONE", max_layer_z=245.0)
        assert "Z250.0" in out

    def test_park_z_not_capped_below_max(self):
        # max_layer_z=100, park_z=110, well below max_z=250
        out = gl.render_end_gcode("COREONE", max_layer_z=100.0)
        assert "Z110.0" in out

    def test_alias_mk4_matches_mk4s_output(self):
        out_alias = gl.render_end_gcode("MK4", max_layer_z=50.0)
        out_canonical = gl.render_end_gcode("MK4S", max_layer_z=50.0)
        assert out_alias == out_canonical
