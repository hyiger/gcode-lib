# gcode-lib

A general-purpose Python library for parsing, analysing, and transforming G-code files.
Supports both plain-text `.gcode` and Prusa binary `.bgcode` formats, with a full planar
post-processing toolkit optimised for PrusaSlicer FDM workflows.

**Requirements:** Python 3.10+ · stdlib only (no third-party dependencies)

---

## Installation

Copy `gcode_lib.py` into your project (or onto `PYTHONPATH`).  No package installation required.

```bash
cp gcode_lib.py /your/project/
```

---

## Quick start

```python
import gcode_lib as gl

# Load any .gcode or .bgcode file
gf = gl.load("benchy.gcode")

# Inspect basic statistics
stats = gl.compute_stats(gf.lines)
print(f"Moves: {stats.move_count}")
print(f"Layers: {stats.layer_count}")
print(f"Total extrusion: {stats.total_extrusion:.2f} mm")

bounds = stats.bounds
print(f"Print size: {bounds.width:.1f} x {bounds.height:.1f} mm")
print(f"Centred at: ({bounds.center_x:.1f}, {bounds.center_y:.1f})")

# Shift the print 10 mm to the right, 5 mm forward (arc-safe, no linearization needed)
lines = gl.translate_xy_allow_arcs(gf.lines, dx=10.0, dy=5.0)
gf.lines = lines

gl.save(gf, "benchy_shifted.gcode")
```

---

## Features

- **[Loading and saving](docs/loading-and-saving.md)** — `load()` / `save()` for `.gcode` and `.bgcode`, `from_text()` / `to_text()`, line and word parsing
- **[State tracking](docs/state-tracking.md)** — `ModalState`, `advance_state()`, iterators for moves, arcs, and extruding segments
- **[Transforms](docs/transforms.md)** — arc linearization, translate, rotate, skew, arbitrary XY transform, layer-selective transforms, G91→G90 conversion, transform analysis
- **[Bed placement](docs/bed-placement.md)** — out-of-bounds detection, recenter/fit to bed
- **[Statistics](docs/statistics.md)** — bounding box, move/arc/travel counts, layer iteration
- **[Presets](docs/presets.md)** — printer bed dimensions and filament parameters for Prusa printers, auto-detection from G-code
- **[Utilities](docs/utilities.md)** — template rendering, thumbnail encoding
- **[Binary .bgcode](docs/binary-bgcode.md)** — full read/write support including DEFLATE, Heatshrink, and MeatPack
- **[PrusaSlicer CLI](docs/prusaslicer-cli.md)** — executable discovery, capability probing, single and batch slicing, slicer compatibility notes
- **[API reference](docs/api-reference.md)** — complete function signatures, data classes, and constants

---

## Concepts

### GCodeLine

Every line of text becomes a `GCodeLine`:

```python
line = gl.parse_line("G1 X10.5 Y20.0 E0.12345 F3600 ; perimeter")
print(line.command)          # "G1"
print(line.words)            # {"X": 10.5, "Y": 20.0, "E": 0.12345, "F": 3600.0}
print(line.comment)          # "; perimeter"
print(line.raw)              # "G1 X10.5 Y20.0 E0.12345 F3600 ; perimeter"
print(line.is_move)          # True  (G0 or G1)
print(line.is_arc)           # False
print(line.is_blank)         # False
```

### ModalState

G-code is stateful.  `ModalState` tracks the printer's current mode and position:

```python
state = gl.ModalState()
print(state.abs_xy)    # True  (G90 absolute XY by default)
print(state.abs_e)     # True  (M82 absolute E by default)
print(state.x, state.y, state.z)   # 0.0, 0.0, 0.0
```

### GCodeFile

The top-level container returned by `load()` or `from_text()`:

```python
gf = gl.load("print.gcode")
print(gf.source_format)         # "text" or "bgcode"
print(len(gf.lines))            # number of GCodeLine objects
print(len(gf.thumbnails))       # populated for .bgcode and plain-text files with embedded thumbnails
```

---

## Limitations

- **G91 relative XY in transforms:** `apply_xy_transform`, `apply_skew`, `translate_xy`, and
  `translate_xy_allow_arcs` raise `ValueError` if a `G0`/`G1` move with X/Y words is encountered
  while the modal state is in G91 mode.  Use `to_absolute_xy()` to convert relative segments to
  absolute before transforming — see [G91 and relative-mode handling](docs/transforms.md#g91-and-relative-mode-handling).
- **Arc endpoint tracking only.**  `advance_state` updates position to the G2/G3 endpoint but
  does not interpolate intermediate arc positions.  Use `linearize_arcs` if you need full path
  coverage.
- **No helical arc support.**  G2/G3 with a simultaneous Z move (helical arcs) are not supported.
  All arcs are treated as planar (XY only).
- **No G-code validation.**  The library parses and transforms; it does not validate that the
  resulting G-code is printable or within machine limits.  Use `find_oob_moves` for basic bed
  boundary checking.

---

## Running the tests

```bash
python -m pytest tests/ -v
```

Tests cover I/O, parsing, state tracking, statistics, all transform functions, bed placement,
layer iteration, presets, preset detection, template rendering, thumbnail encoding, BGCode
round-trips (including Heatshrink decompression and MeatPack decoding), and PrusaSlicer CLI
helpers — using only stdlib and pytest.
