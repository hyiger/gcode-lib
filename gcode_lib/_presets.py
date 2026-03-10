"""Printer/filament presets, G-code templates, STL thumbnails, slicer helpers, filename utils."""

from __future__ import annotations

import math
import multiprocessing as mp
import platform
import re
import secrets
import struct
import sys
import warnings
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from gcode_lib._constants import (
    _BLK_FILE_METADATA,
    _BLK_PRINTER_METADATA,
    _BLK_SLICER_METADATA,
    _BLK_THUMBNAIL,
    _COMP_DEFLATE,
    _COMP_NONE,
    _IMG_PNG,
)
from gcode_lib._types import GCodeFile, GCodeLine, Thumbnail


# ---------------------------------------------------------------------------
# §5 — Printer and filament presets
# ---------------------------------------------------------------------------

PRINTER_PRESETS: Dict[str, Dict[str, float]] = {
    "COREONE": {
        "bed_x": 250.0,
        "bed_y": 220.0,
        "max_z": 250.0,
        "max_nozzle_temp": 290.0,
        "max_bed_temp": 120.0,
    },
    "COREONEL": {
        "bed_x": 300.0,
        "bed_y": 300.0,
        "max_z": 330.0,
        "max_nozzle_temp": 290.0,
        "max_bed_temp": 120.0,
    },
    "MK4": {
        "bed_x": 250.0,
        "bed_y": 210.0,
        "max_z": 220.0,
        "max_nozzle_temp": 290.0,
        "max_bed_temp": 120.0,
    },
    "MK3S": {
        "bed_x": 250.0,
        "bed_y": 210.0,
        "max_z": 210.0,
        "max_nozzle_temp": 290.0,
        "max_bed_temp": 120.0,
    },
    "MINI": {
        "bed_x": 180.0,
        "bed_y": 180.0,
        "max_z": 180.0,
        "max_nozzle_temp": 280.0,
        "max_bed_temp": 100.0,
    },
    "XL": {
        "bed_x": 360.0,
        "bed_y": 360.0,
        "max_z": 360.0,
        "max_nozzle_temp": 290.0,
        "max_bed_temp": 120.0,
    },
}

FILAMENT_PRESETS: Dict[str, Dict[str, object]] = {
    "PLA": {
        "hotend": 215,
        "bed": 60,
        "fan": 100,
        "retract": 0.8,
        "temp_min": 190,
        "temp_max": 230,
        "speed": 60,
        "enclosure": False,
    },
    "PETG": {
        "hotend": 240,
        "bed": 80,
        "fan": 40,
        "retract": 0.8,
        "temp_min": 220,
        "temp_max": 260,
        "speed": 50,
        "enclosure": False,
    },
    "ASA": {
        "hotend": 260,
        "bed": 100,
        "fan": 20,
        "retract": 0.8,
        "temp_min": 240,
        "temp_max": 280,
        "speed": 45,
        "enclosure": True,
    },
    "TPU": {
        "hotend": 230,
        "bed": 50,
        "fan": 50,
        "retract": 1.5,
        "temp_min": 210,
        "temp_max": 250,
        "speed": 25,
        "enclosure": False,
    },
    "ABS": {
        "hotend": 255,
        "bed": 100,
        "fan": 20,
        "retract": 0.8,
        "temp_min": 230,
        "temp_max": 270,
        "speed": 45,
        "enclosure": True,
    },
    "PA": {
        "hotend": 260,
        "bed": 80,
        "fan": 30,
        "retract": 1.0,
        "temp_min": 240,
        "temp_max": 280,
        "speed": 40,
        "enclosure": True,
    },
    "PC": {
        "hotend": 275,
        "bed": 110,
        "fan": 20,
        "retract": 0.8,
        "temp_min": 260,
        "temp_max": 300,
        "speed": 40,
        "enclosure": True,
    },
    "PCTG": {
        "hotend": 250,
        "bed": 80,
        "fan": 50,
        "retract": 0.8,
        "temp_min": 230,
        "temp_max": 270,
        "speed": 50,
        "enclosure": False,
    },
    "PP": {
        "hotend": 240,
        "bed": 85,
        "fan": 30,
        "retract": 1.2,
        "temp_min": 220,
        "temp_max": 260,
        "speed": 35,
        "enclosure": True,
    },
    "PPA": {
        "hotend": 280,
        "bed": 100,
        "fan": 20,
        "retract": 0.8,
        "temp_min": 260,
        "temp_max": 310,
        "speed": 40,
        "enclosure": True,
    },
    "HIPS": {
        "hotend": 230,
        "bed": 100,
        "fan": 20,
        "retract": 0.8,
        "temp_min": 220,
        "temp_max": 250,
        "speed": 45,
        "enclosure": True,
    },
    "PLA-CF": {
        "hotend": 220,
        "bed": 60,
        "fan": 100,
        "retract": 0.8,
        "temp_min": 200,
        "temp_max": 240,
        "speed": 50,
        "enclosure": False,
    },
    "PETG-CF": {
        "hotend": 250,
        "bed": 80,
        "fan": 30,
        "retract": 0.8,
        "temp_min": 230,
        "temp_max": 270,
        "speed": 45,
        "enclosure": False,
    },
    "PA-CF": {
        "hotend": 270,
        "bed": 80,
        "fan": 20,
        "retract": 1.0,
        "temp_min": 250,
        "temp_max": 290,
        "speed": 40,
        "enclosure": True,
    },
}

_M862_3_RE = re.compile(
    r'^M862\.3\s+P\s*"?([A-Za-z0-9_]+)"?',
)


def detect_printer_preset(lines: List[GCodeLine]) -> Optional[str]:
    """Detect the printer preset from an ``M862.3 P`` line in *lines*."""
    for line in lines:
        if not line.command.startswith("M862"):
            continue
        m = _M862_3_RE.match(line.raw.strip())
        if m:
            name = m.group(1).upper()
            if name in PRINTER_PRESETS:
                return name
            alias = _PRESET_ALIASES.get(name)
            if alias in PRINTER_PRESETS:
                return alias
    return None


def detect_print_volume(lines: List[GCodeLine]) -> Optional[Dict[str, float]]:
    """Detect the print volume from an ``M862.3 P`` line in *lines*."""
    name = detect_printer_preset(lines)
    if name is not None:
        return dict(PRINTER_PRESETS[name])
    return None


# ===========================================================================
# §13 — STL thumbnail rendering & injection
# ===========================================================================

try:
    import vtk as _vtk  # type: ignore[import-untyped]
    _HAS_VTK = True
except ImportError:
    _vtk = None  # type: ignore[assignment]
    _HAS_VTK = False

_MODEL_COLOR = (0.93, 0.42, 0.13)
_SUPERSAMPLE_THRESHOLD: int = 32
_SUPERSAMPLE_FACTOR: int = 4

_PRINTER_SETTINGS_IDS: Dict[Tuple[str, str], str] = {
    ("COREONE", "0.25"): "Prusa CORE One 0.25 nozzle",
    ("COREONE", "0.3"):  "Prusa CORE One 0.3 nozzle",
    ("COREONE", "0.4"):  "Prusa CORE One HF0.4 nozzle",
    ("COREONE", "0.5"):  "Prusa CORE One HF0.5 nozzle",
    ("COREONE", "0.6"):  "Prusa CORE One HF0.6 nozzle",
    ("COREONE", "0.8"):  "Prusa CORE One HF0.8 nozzle",
}


def _fallback_png(width: int, height: int) -> bytes:
    """Return a minimal solid-color RGB PNG as a safe rendering fallback."""
    w = max(1, int(width))
    h = max(1, int(height))

    r = max(0, min(255, int(round(_MODEL_COLOR[0] * 255))))
    g = max(0, min(255, int(round(_MODEL_COLOR[1] * 255))))
    b = max(0, min(255, int(round(_MODEL_COLOR[2] * 255))))

    row = bytes([0]) + bytes([r, g, b]) * w
    raw = row * h

    def _chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        crc = zlib.crc32(body) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + body + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    idat = zlib.compress(raw)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", idat)
        + _chunk(b"IEND", b"")
    )


@dataclass
class ThumbnailSpec:
    """Desired thumbnail size and format."""
    width: int
    height: int


def parse_thumbnail_specs(spec: str) -> List[ThumbnailSpec]:
    """Parse a PrusaSlicer-style thumbnail spec string."""
    if not spec or not spec.strip():
        return []
    specs: List[ThumbnailSpec] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        size_part = part.split("/")[0]
        dims = size_part.lower().split("x")
        if len(dims) != 2:
            warnings.warn(f"Skipping invalid thumbnail spec: {part!r}")
            continue
        try:
            w, h = int(dims[0]), int(dims[1])
        except ValueError:
            warnings.warn(f"Skipping invalid thumbnail spec: {part!r}")
            continue
        specs.append(ThumbnailSpec(width=w, height=h))
    return specs


def render_stl_to_png(stl_path: str, width: int, height: int) -> bytes:
    """Render a binary STL file to PNG bytes at the requested size."""
    if not _HAS_VTK:
        raise RuntimeError("VTK is not installed; cannot render thumbnails")

    if not Path(stl_path).exists():
        raise FileNotFoundError(stl_path)

    if width <= _SUPERSAMPLE_THRESHOLD or height <= _SUPERSAMPLE_THRESHOLD:
        render_w = width * _SUPERSAMPLE_FACTOR
        render_h = height * _SUPERSAMPLE_FACTOR
        needs_downscale = True
    else:
        render_w = width
        render_h = height
        needs_downscale = False

    if _needs_subprocess_render():
        try:
            return _render_in_subprocess(
                stl_path, render_w, render_h, width, height, needs_downscale,
            )
        except RuntimeError as exc:
            warnings.warn(
                f"VTK subprocess render failed ({exc}); using fallback thumbnail"
            )
            return _fallback_png(width, height)
    return _render_vtk(stl_path, render_w, render_h, width, height, needs_downscale)


def build_thumbnail_block(png_data: bytes, width: int, height: int) -> bytes:
    """Construct a raw bgcode thumbnail block from PNG image data."""
    hdr = struct.pack("<HHI", _BLK_THUMBNAIL, _COMP_NONE, len(png_data))
    params = struct.pack("<HHH", _IMG_PNG, width, height)
    cksum = zlib.crc32(hdr) & 0xFFFFFFFF
    cksum = zlib.crc32(params, cksum) & 0xFFFFFFFF
    cksum = zlib.crc32(png_data, cksum) & 0xFFFFFFFF
    return hdr + params + png_data + struct.pack("<I", cksum)


def inject_thumbnails(
    gf: GCodeFile,
    stl_path: str,
    spec_string: str,
    *,
    verbose: bool = False,
) -> None:
    """Inject rendered thumbnails into a binary G-code file."""
    if gf.source_format != "bgcode":
        return

    if gf.thumbnails:
        if verbose:
            print("[DEBUG] Thumbnails already present — skipping injection")
        return

    specs = parse_thumbnail_specs(spec_string)
    if not specs:
        return

    try:
        new_blocks: List[bytes] = []
        new_thumbs: List[Thumbnail] = []

        for spec in specs:
            if verbose:
                print(
                    f"[DEBUG] Rendering {spec.width}×{spec.height} "
                    f"thumbnail from {stl_path}"
                )
            # Look up via parent package so mock.patch("gcode_lib.render_stl_to_png") works.
            _render = sys.modules[__name__.rpartition(".")[0]].render_stl_to_png
            png_data = _render(stl_path, spec.width, spec.height)
            block = build_thumbnail_block(png_data, spec.width, spec.height)
            gl_params = struct.pack("<HHH", _IMG_PNG, spec.width, spec.height)
            new_blocks.append(block)
            new_thumbs.append(
                Thumbnail(params=gl_params, data=png_data, _raw_block=block)
            )

        if gf._bgcode_nongcode_blocks is None:
            gf._bgcode_nongcode_blocks = []  # pragma: no cover
        insert_pos = _find_thumbnail_insert_pos(gf._bgcode_nongcode_blocks)
        for i, blk in enumerate(new_blocks):
            gf._bgcode_nongcode_blocks.insert(insert_pos + i, blk)
        gf.thumbnails.extend(new_thumbs)

        if verbose:
            print(f"[DEBUG] Injected {len(new_thumbs)} thumbnail(s)")

    except Exception as exc:
        warnings.warn(f"Thumbnail injection failed: {exc}")


def patch_slicer_metadata(
    gf: GCodeFile,
    printer_model: str,
    nozzle_diameter: float,
    *,
    verbose: bool = False,
) -> None:
    """Patch the SLICER_METADATA block to set ``printer_settings_id`` and ``printer_model``."""
    if gf.source_format != "bgcode":
        return

    nozzle_str = f"{nozzle_diameter:g}"
    settings_id = _PRINTER_SETTINGS_IDS.get((printer_model, nozzle_str))
    if settings_id is None:
        if verbose:
            print(
                f"[DEBUG] No printer_settings_id mapping for "
                f"({printer_model}, {nozzle_str})"
            )
        return

    blocks = gf._bgcode_nongcode_blocks
    if not blocks:
        return

    try:
        idx = _find_slicer_meta_index(blocks)
        if idx is None:
            return

        old_block = blocks[idx]
        new_block = _rebuild_slicer_meta_block(
            old_block,
            {
                "printer_settings_id": settings_id,
                "printer_model": printer_model,
            },
        )
        blocks[idx] = new_block

        if verbose:
            print(
                f"[DEBUG] Patched printer_settings_id={settings_id}, "
                f"printer_model={printer_model}"
            )

    except Exception as exc:
        warnings.warn(f"Slicer metadata patch failed: {exc}")


def _find_slicer_meta_index(blocks: List[bytes]) -> Optional[int]:
    """Return the index of the SLICER_METADATA block, or ``None``."""
    for i, blk in enumerate(blocks):
        btype = struct.unpack_from("<H", blk, 0)[0]
        if btype == _BLK_SLICER_METADATA:
            return i
    return None


def _rebuild_slicer_meta_block(
    raw_block: bytes,
    updates: Dict[str, str],
) -> bytes:
    """Rebuild a SLICER_METADATA block with updated key=value pairs."""
    btype, comp, usize = struct.unpack_from("<HHI", raw_block, 0)
    assert btype == _BLK_SLICER_METADATA

    if comp == _COMP_NONE:
        params = raw_block[8:10]
        payload = raw_block[10 : 10 + usize]
    elif comp == _COMP_DEFLATE:
        cs = struct.unpack_from("<I", raw_block, 8)[0]
        params = raw_block[12:14]
        compressed = raw_block[14 : 14 + cs]
        payload = zlib.decompress(compressed)
    else:
        return raw_block

    text = payload.decode("utf-8")
    for key, value in updates.items():
        pattern = rf"^{re.escape(key)}=.*$"
        if re.search(pattern, text, flags=re.MULTILINE):
            text = re.sub(pattern, f"{key}={value}", text, flags=re.MULTILINE)
        else:
            text = text.rstrip("\n") + f"\n{key}={value}\n"

    new_payload = text.encode("utf-8")

    new_hdr = struct.pack("<HHI", btype, comp, len(new_payload))
    if comp == _COMP_DEFLATE:
        new_compressed = zlib.compress(new_payload)
        cs_bytes = struct.pack("<I", len(new_compressed))
        block_body = new_hdr + cs_bytes + params + new_compressed
    else:
        block_body = new_hdr + params + new_payload

    crc = struct.pack("<I", zlib.crc32(block_body) & 0xFFFFFFFF)
    return block_body + crc


def _find_thumbnail_insert_pos(blocks: List[bytes]) -> int:
    """Return the index at which thumbnail blocks should be inserted."""
    pos = 0
    for i, blk in enumerate(blocks):
        btype = struct.unpack_from("<H", blk, 0)[0]
        if btype in (_BLK_FILE_METADATA, _BLK_PRINTER_METADATA):
            pos = i + 1
    return pos


def _needs_subprocess_render() -> bool:
    """Return ``True`` if VTK rendering must be offloaded to a subprocess."""
    # Look up platform via parent package so mock.patch("gcode_lib.platform") works.
    _platform = sys.modules[__name__.rpartition(".")[0]].platform
    return _platform.system() == "Darwin"


def _subprocess_render_worker(
    result_queue: object,
    stl_path: str,
    render_w: int,
    render_h: int,
    final_w: int,
    final_h: int,
    needs_downscale: bool,
) -> None:
    """Multiprocessing worker that runs ``_render_vtk`` on the main thread."""
    try:
        png = _render_vtk(stl_path, render_w, render_h, final_w, final_h, needs_downscale)
        result_queue.put(("ok", png))
    except Exception as exc:
        result_queue.put(("error", str(exc)))


def _render_in_subprocess(
    stl_path: str,
    render_w: int,
    render_h: int,
    final_w: int,
    final_h: int,
    needs_downscale: bool,
) -> bytes:
    """Spawn a subprocess to perform VTK rendering on its main thread."""
    ctx = mp.get_context("spawn")
    result_queue: mp.Queue[Tuple[str, Union[bytes, str]]] = ctx.Queue()

    proc = ctx.Process(
        target=_subprocess_render_worker,
        args=(result_queue, stl_path, render_w, render_h, final_w, final_h, needs_downscale),
    )
    proc.start()
    proc.join(timeout=120)

    if proc.exitcode is None:
        proc.kill()
        raise RuntimeError("VTK render subprocess timed out")

    if proc.exitcode != 0:
        raise RuntimeError(
            f"VTK render subprocess failed (exit code {proc.exitcode})"
        )

    status, data = result_queue.get_nowait()
    if status == "error":
        raise RuntimeError(f"VTK render failed in subprocess: {data}")
    return data  # type: ignore[return-value]


def _render_vtk(
    stl_path: str,
    render_w: int,
    render_h: int,
    final_w: int,
    final_h: int,
    needs_downscale: bool,
) -> bytes:
    """Render an STL file to PNG bytes using VTK off-screen rendering."""
    reader = _vtk.vtkSTLReader()
    reader.SetFileName(stl_path)
    reader.Update()

    mapper = _vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(reader.GetOutputPort())

    actor = _vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(*_MODEL_COLOR)
    actor.GetProperty().SetAmbient(0.3)
    actor.GetProperty().SetDiffuse(0.7)

    renderer = _vtk.vtkRenderer()
    renderer.AddActor(actor)
    renderer.SetBackground(0.22, 0.22, 0.22)

    window = _vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(render_w, render_h)
    window.AddRenderer(renderer)

    renderer.ResetCamera()
    camera = renderer.GetActiveCamera()
    focal = list(camera.GetFocalPoint())
    dist = camera.GetDistance()

    az = math.radians(35)
    el = math.radians(25)
    camera.SetPosition(
        focal[0] + dist * math.cos(el) * math.sin(az),
        focal[1] - dist * math.cos(el) * math.cos(az),
        focal[2] + dist * math.sin(el),
    )
    camera.SetViewUp(0, 0, 1)
    renderer.ResetCameraClippingRange()

    window.Render()

    w2i = _vtk.vtkWindowToImageFilter()
    w2i.SetInput(window)
    w2i.Update()

    if needs_downscale:
        resizer = _vtk.vtkImageResize()
        resizer.SetInputConnection(w2i.GetOutputPort())
        resizer.SetOutputDimensions(final_w, final_h, 1)
        resizer.Update()
        source = resizer.GetOutputPort()
    else:
        source = w2i.GetOutputPort()

    writer = _vtk.vtkPNGWriter()
    writer.WriteToMemoryOn()
    writer.SetInputConnection(source)
    writer.Write()

    result = writer.GetResult()
    png_bytes = bytes(
        result.GetValue(i) for i in range(result.GetNumberOfTuples())
    )

    window.Finalize()

    return png_bytes


# ===========================================================================
# §14 — Printer G-code templates
# ===========================================================================

KNOWN_PRINTERS: Tuple[str, ...] = ("COREONE", "COREONEL", "MK4S", "MINI", "XL")

_PRINTER_ALIASES: Dict[str, str] = {
    "MK4": "MK4S",
}

_PRESET_ALIASES: Dict[str, str] = {v: k for k, v in _PRINTER_ALIASES.items()}

MBL_TEMP: int = 170


@dataclass
class PrinterGCode:
    """Start and end G-code templates for a single printer model."""
    start: str
    end: str


_COREONE_START = """\
M17 ; enable steppers
M862.1 P{nozzle_dia} ; nozzle check
M862.3 P "COREONE" ; printer model check
M862.5 P2 ; g-code level check
M862.6 P"Input shaper" ; FW feature check
M115 U6.4.0+11974
M555 X{m555_x} Y{m555_y} W{m555_w} H{m555_h}
G90 ; use absolute coordinates
M83 ; extruder relative mode
M140 S{bed_temp} ; set bed temp
M109 R{mbl_temp} ; preheat nozzle to no-ooze temp for bed leveling
M84 E ; turn off E motor
G28 ; home all without mesh bed level
M104 S100 ; set idle temp
M190 R{bed_temp} ; wait for bed temp
{cool_fan}
G0 Z40 F10000
M104 S100 ; keep idle temp
M190 R{bed_temp} ; wait for bed temp (confirm after Z move)
M107
G29 G ; absorb heat
M109 R{mbl_temp} ; wait for MBL temp
M302 S155 ; lower cold extrusion limit to 155 C
G1 E-2 F2400 ; retraction
M84 E ; turn off E motor
G29 P9 X208 Y-2.5 W32 H4
;
; MBL
;
M84 E ; turn off E motor
G29 P1 ; invalidate mbl and probe print area
G29 P1 X150 Y0 W100 H20 C ; probe near purge place
G29 P3.2 ; interpolate mbl probes
G29 P3.13 ; extrapolate mbl outside probe area
G29 A ; activate mbl
; prepare for purge
M104 S{hotend_temp}
G0 X249 Y-2.5 Z15 F4800 ; move away and ready for the purge
M109 S{hotend_temp}
G92 E0
M569 S0 E ; set spreadcycle mode for extruder
M591 S0 ; disable stuck filament detection
;
; Purge line
;
G92 E0 ; reset extruder position
G1 E2 F2400 ; deretraction after the initial one
G0 E5 X235 Z0.2 F500 ; purge
G0 X225 E4 F500 ; purge
G0 X215 E4 F650 ; purge
G0 X205 E4 F800 ; purge
G0 X202 Z0.05 F8000 ; wipe, move close to the bed
G0 X199 Z0.2 F8000 ; wipe, move away from the bed
M591 R ; restore stuck filament detection
G92 E0
M221 S100 ; set flow to 100%"""

_COREONE_END = """\
G1 Z{park_z} F720 ; move print head up
M104 S0 ; turn off hotend
M140 S0 ; turn off heatbed
M141 S0 ; disable chamber temp control
M107 ; turn off fan
G1 X242 Y211 F10200 ; park
G4 ; wait
M572 S0 ; reset pressure advance (ignored on Marlin)
M900 K0 ; reset Linear Advance
M84 X Y E ; disable motors
; max_layer_z = {max_layer_z}"""

_COREONEL_START = """\
M17 ; enable steppers
M862.1 P{nozzle_dia} ; nozzle check
M862.3 P "COREONEL" ; printer model check
M862.5 P2 ; g-code level check
M862.6 P"Input shaper" ; FW feature check
M115 U6.5.1+12574
M555 X{m555_x} Y{m555_y} W{m555_w} H{m555_h}
G90 ; use absolute coordinates
M83 ; extruder relative mode
M140 S{bed_temp} ; set bed temp
M106 P5 R A125 B10 ; turn on bed fans with fade
M109 R{mbl_temp} ; preheat nozzle to no-ooze temp for bed leveling
M84 E ; turn off E motor
G28 Q ; home all without mesh bed level
G1 Z20 F720 ; lift bed to optimal bed fan height
M141 S0 ; set nominal chamber temp
{cool_fan}
M190 R{bed_temp} ; wait for bed temp
M107
M109 R{mbl_temp} ; wait for MBL temp
M302 S155 ; lower cold extrusion limit to 155 C
G1 E-2 F2400 ; retraction
M84 E ; turn off E motor
G29 P9 X208 Y-2.5 W32 H4
;
; MBL
;
M84 E ; turn off E motor
G29 P1 ; invalidate mbl and probe print area
G29 P1 X150 Y0 W100 H20 C ; probe near purge place
G29 P3.2 ; interpolate mbl probes
G29 P3.13 ; extrapolate mbl outside probe area
G29 A ; activate mbl
; prepare for purge
M104 S{hotend_temp}
G0 X249 Y-2.5 Z15 F4800 ; move away and ready for the purge
M109 S{hotend_temp}
G92 E0
M569 S0 E ; set spreadcycle mode for extruder
M591 S0 ; disable stuck filament detection
;
; Purge line
;
G92 E0 ; reset extruder position
G1 E2 F2400 ; deretraction after the initial one
G0 E5 X235 Z0.2 F500 ; purge
G0 X225 E4 F500 ; purge
G0 X215 E4 F650 ; purge
G0 X205 E4 F800 ; purge
G0 X202 Z0.05 F8000 ; wipe, move close to the bed
G0 X199 Z0.2 F8000 ; wipe, move away from the bed
M591 R ; restore stuck filament detection
G92 E0
M221 S100 ; set flow to 100%"""

_COREONEL_END = """\
G1 Z{park_z} F720 ; move print head up
M104 S0 ; turn off hotend
M140 S0 ; turn off heatbed
M141 S0 ; disable chamber temp control
M107 ; turn off fan
M107 P5 ; turn off bed fans
G1 X290 Y295 F10200 ; park
G4 ; wait
M572 S0 ; reset pressure advance (ignored on Marlin)
M900 K0 ; reset Linear Advance
M84 X Y E ; disable motors
; max_layer_z = {max_layer_z}"""

_MK4S_START = """\
M17 ; enable steppers
M862.1 P{nozzle_dia} ; nozzle check
M862.3 P "MK4S" ; printer model check
M862.5 P2 ; g-code level check
M862.6 P"Input shaper" ; FW feature check
M115 U6.4.0+11974
M555 X{m555_x} Y{m555_y} W{m555_w} H{m555_h}
G90 ; use absolute coordinates
M83 ; extruder relative mode
M140 S{bed_temp} ; set bed temp
M104 S{mbl_temp} ; set extruder temp for bed leveling
M109 R{mbl_temp} ; wait for bed leveling temp
M84 E ; turn off E motor
G28 ; home all without mesh bed level
G1 X42 Y-4 Z5 F4800
M302 S155 ; lower cold extrusion limit to 155 C
G1 E-2 F2400 ; retraction
M84 E ; turn off E motor
G29 P9 X10 Y-4 W32 H4
{cool_fan}
G0 Z40 F10000
M190 S{bed_temp} ; wait for bed temp
M107
;
; MBL
;
M84 E ; turn off E motor
G29 P1 ; invalidate mbl and probe print area
G29 P1 X0 Y0 W50 H20 C ; probe near purge place
G29 P3.2 ; interpolate mbl probes
G29 P3.13 ; extrapolate mbl outside probe area
G29 A ; activate mbl
; prepare for purge
M104 S{hotend_temp}
G0 X0 Y-4 Z15 F4800 ; move away and ready for the purge
M109 S{hotend_temp}
G92 E0
M569 S0 E ; set spreadcycle mode for extruder
;
; Purge line
;
G92 E0 ; reset extruder position
G1 E2 F2400 ; deretraction after the initial one
G0 E7 X15 Z0.2 F500 ; purge
G0 X25 E4 F500 ; purge
G0 X35 E4 F650 ; purge
G0 X45 E4 F800 ; purge
G0 X48 Z0.05 F8000 ; wipe, move close to the bed
G0 X51 Z0.2 F8000 ; wipe, move away from the bed
G92 E0
M221 S100 ; set flow to 100%"""

_MK4S_END = """\
G1 Z{park_z} F720 ; move print head up
M104 S0 ; turn off hotend
M140 S0 ; turn off heatbed
M107 ; turn off fan
G1 X241 Y170 F3600 ; park
G4 ; wait
M572 S0 ; reset pressure advance (ignored on Marlin)
M900 K0 ; reset Linear Advance
M593 X T2 F0 ; disable input shaping X
M593 Y T2 F0 ; disable input shaping Y
M84 X Y E ; disable motors
; max_layer_z = {max_layer_z}"""

_MINI_START = """\
M862.3 P "MINI" ; printer model check
M862.1 P{nozzle_dia} ; nozzle check
M862.5 P2 ; g-code level check
M862.6 P"Input shaper" ; FW feature check
M115 U6.4.0+11974
G90 ; use absolute coordinates
M83 ; extruder relative mode
M104 S{mbl_temp} ; set extruder temp for bed leveling
M140 S{bed_temp} ; set bed temp
M109 R{mbl_temp} ; wait for bed leveling temp
M190 S{bed_temp} ; wait for bed temp
M569 S1 X Y ; set stealthchop for X Y
M204 T1250 ; set travel acceleration
G28 ; home all without mesh bed level
G29 ; mesh bed leveling
M104 S{hotend_temp} ; set extruder temp
G92 E0
G1 X0 Y-2 Z3 F2400
M109 S{hotend_temp} ; wait for extruder temp
;
; Intro line
;
G1 X10 Z0.2 F1000
G1 X70 E8 F900
G1 X140 E10 F700
G92 E0
M569 S0 X Y ; set spreadcycle for X Y
M204 T1250 ; restore travel acceleration
M572 W0.06 ; set pressure advance smooth time
M221 S95 ; set flow"""

_MINI_END = """\
G1 Z{park_z} F720 ; move print head up
M104 S0 ; turn off hotend
M140 S0 ; turn off heatbed
M107 ; turn off fan
G1 X90 Y170 F3600 ; park
G4 ; wait
M900 K0 ; reset Linear Advance
M84 X Y E ; disable motors
; max_layer_z = {max_layer_z}"""

_XL_START = """\
M17 ; enable steppers
M862.3 P "XL" ; printer model check
M862.5 P2 ; g-code level check
M862.6 P"Input shaper" ; FW feature check
M115 U6.2.6+8948
G90 ; use absolute coordinates
M83 ; extruder relative mode
M555 X{m555_x} Y{m555_y} W{m555_w} H{m555_h}
M862.1 P{nozzle_dia} ; nozzle check
M140 S{bed_temp} ; set bed temp
M104 S{mbl_temp} ; set extruder temp for bed leveling
G28 XY ; home carriage
M109 R{mbl_temp} ; wait for bed leveling temp
M84 E ; turn off E motor
G28 Z ; home Z
M104 S70 ; set idle temp
M190 S{bed_temp} ; wait for bed temp
G29 G ; absorb heat
M109 R{mbl_temp} ; wait for MBL temp
; move to nozzle cleanup area
G1 X30 Y-8 Z5 F4800
M302 S155 ; lower cold extrusion limit to 155 C
G1 E-2 F2400 ; retraction
M84 E ; turn off E motor
G29 P9 X30 Y-8 W32 H7
G0 Z10 F480 ; move away in Z
M106 S100 ; cool nozzle
M107 ; stop cooling fan
;
; MBL
;
M84 E ; turn off E motor
G29 P1 ; invalidate mbl and probe print area
G29 P1 X30 Y0 W50 H20 C ; probe near purge place
G29 P3.2 ; interpolate mbl probes
G29 P3.13 ; extrapolate mbl outside probe area
G29 A ; activate mbl
M104 S{hotend_temp} ; set extruder temp
G1 Z10 F720 ; move away in Z
G0 X30 Y-8 F6000 ; move next to the sheet
M109 S{hotend_temp} ; wait for extruder temp
M591 S0 ; disable stuck filament detection
;
; Purge line
;
G92 E0 ; reset extruder position
G0 X30 Y-8 ; move close to the sheet edge
G1 E2 F2400 ; deretraction after the initial one
G0 E10 X40 Z0.2 F500 ; purge
G0 X70 E9 F800 ; purge
G0 X73 Z0.05 F8000 ; wipe, move close to the bed
G0 X76 Z0.2 F8000 ; wipe, move away from the bed
M591 R ; restore stuck filament detection
G92 E0 ; reset extruder position"""

_XL_END = """\
G1 Z{park_z} F720 ; move bed down
M104 S0 ; turn off hotend
M140 S0 ; turn off heatbed
M107 ; turn off fan
G1 X6 Y350 F6000 ; park
G4 ; wait
M900 K0 ; reset Linear Advance
M142 S36 ; reset heatbreak target temp
M221 S100 ; reset flow percentage
M84 ; disable motors
; max_layer_z = {max_layer_z}"""


_PRINTER_GCODE_TEMPLATES: Dict[str, PrinterGCode] = {
    "COREONE": PrinterGCode(start=_COREONE_START, end=_COREONE_END),
    "COREONEL": PrinterGCode(start=_COREONEL_START, end=_COREONEL_END),
    "MK4S": PrinterGCode(start=_MK4S_START, end=_MK4S_END),
    "MINI": PrinterGCode(start=_MINI_START, end=_MINI_END),
    "XL": PrinterGCode(start=_XL_START, end=_XL_END),
}


def resolve_printer(name: str) -> str:
    """Normalise a printer name and validate it has a template."""
    upper = name.upper()
    resolved = _PRINTER_ALIASES.get(upper, upper)
    if resolved not in _PRINTER_GCODE_TEMPLATES:
        names = ", ".join(sorted(_PRINTER_GCODE_TEMPLATES.keys()))
        raise ValueError(
            f"unknown printer {name!r}. "
            f"Available printers: {names}"
        )
    return resolved


def _lookup_printer_preset(printer: str) -> Optional[dict]:
    """Look up a printer preset, trying direct name and alias."""
    preset = PRINTER_PRESETS.get(printer)
    if preset is None:
        preset = PRINTER_PRESETS.get(
            _PRESET_ALIASES.get(printer, printer)
        )
    return preset


def compute_bed_center(printer: str) -> str:
    """Return ``"X,Y"`` bed centre string from ``PRINTER_PRESETS``."""
    preset = _lookup_printer_preset(printer)
    if preset is None:
        return "125,110"
    cx = int(preset["bed_x"] / 2)
    cy = int(preset["bed_y"] / 2)
    return f"{cx},{cy}"


def compute_bed_shape(printer: str) -> str:
    """Return PrusaSlicer ``--bed-shape`` string from ``PRINTER_PRESETS``."""
    preset = _lookup_printer_preset(printer)
    if preset is None:
        return "0x0,250x0,250x220,0x220"
    bx = int(preset["bed_x"])
    by = int(preset["bed_y"])
    return f"0x0,{bx}x0,{bx}x{by},0x{by}"


def compute_m555(
    bed_center: str,
    model_width: float,
    model_depth: float,
) -> Dict[str, int]:
    """Compute M555 bounding-box parameters for the print area hint."""
    parts = bed_center.split(",")
    cx, cy = float(parts[0]), float(parts[1])
    x = int(cx - model_width / 2)
    y = int(cy - model_depth / 2)
    return {
        "m555_x": x,
        "m555_y": y,
        "m555_w": int(model_width),
        "m555_h": int(model_depth),
    }


def render_start_gcode(
    printer: str,
    *,
    nozzle_dia: float,
    bed_temp: int,
    hotend_temp: int,
    bed_center: str,
    model_width: float,
    model_depth: float,
    cool_fan: bool = True,
) -> str:
    """Render the start G-code template for *printer*."""
    printer = resolve_printer(printer)
    template = _PRINTER_GCODE_TEMPLATES[printer].start
    m555 = compute_m555(bed_center, model_width, model_depth)
    mbl_temp = min(hotend_temp, MBL_TEMP)
    cool_fan_cmd = "M106 S255" if cool_fan else ""

    return template.format(
        nozzle_dia=nozzle_dia,
        bed_temp=bed_temp,
        hotend_temp=hotend_temp,
        mbl_temp=mbl_temp,
        cool_fan=cool_fan_cmd,
        **m555,
    )


def render_end_gcode(
    printer: str,
    *,
    max_layer_z: float,
) -> str:
    """Render the end G-code template for *printer*."""
    printer = resolve_printer(printer)
    template = _PRINTER_GCODE_TEMPLATES[printer].end
    preset = _lookup_printer_preset(printer)
    max_z = float(preset["max_z"]) if preset is not None else 250.0
    park_z = min(max_layer_z + 10.0, max_z)

    return template.format(
        park_z=f"{park_z:.1f}",
        max_layer_z=f"{max_layer_z:.2f}",
    )


# ===========================================================================
# §15 — Slicer dimension helpers
# ===========================================================================


def derive_slicer_dimensions(
    nozzle_size: float,
) -> Tuple[float, float]:
    """Derive layer height and extrusion width from nozzle size."""
    layer_height = round(nozzle_size * 0.5, 2)
    extrusion_width = round(nozzle_size * 1.125, 2)
    return layer_height, extrusion_width


def flow_to_feedrate(
    flow_mm3s: float,
    layer_height: float,
    extrusion_width: float,
) -> float:
    """Convert a volumetric flow rate to a linear feedrate."""
    speed_mm_s = flow_mm3s / (layer_height * extrusion_width)
    return speed_mm_s * 60.0


def resolve_filament_preset(
    filament_type: str,
    *,
    nozzle_temp: Optional[int] = None,
    bed_temp: Optional[int] = None,
    fan_speed: Optional[int] = None,
) -> Dict[str, int]:
    """Look up a filament preset and return resolved slicer settings."""
    filament_key = filament_type.upper()
    preset = FILAMENT_PRESETS.get(filament_key)

    if preset is not None:
        default_nozzle = int(preset["hotend"])
        default_bed = int(preset["bed"])
        default_fan = int(preset["fan"])
    else:
        default_nozzle = 210
        default_bed = 60
        default_fan = 100

    return {
        "nozzle_temp": nozzle_temp if nozzle_temp is not None else default_nozzle,
        "bed_temp": bed_temp if bed_temp is not None else default_bed,
        "fan_speed": fan_speed if fan_speed is not None else default_fan,
    }


# ===========================================================================
# §16 — Filename utilities
# ===========================================================================


def gcode_ext(binary: bool = True) -> str:
    """Return the G-code file extension based on format selection."""
    return ".bgcode" if binary else ".gcode"


def unique_suffix() -> str:
    """Return a 5-character hex string for unique filenames."""
    return secrets.token_hex(3)[:5]


def safe_filename_part(value: str) -> str:
    """Sanitise a user-supplied string for safe inclusion in a filename."""
    cleaned = value.replace("\x00", "").replace("/", "_").replace("\\", "_")
    cleaned = cleaned.replace("..", "_")
    return cleaned or "unknown"
