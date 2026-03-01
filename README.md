# gcode-lib

A general-purpose Python library for parsing, analysing, and transforming G-code files.
Supports both plain-text `.gcode` and Prusa binary `.bgcode` formats.

**Requirements:** Python 3.10+ · stdlib only (no third-party dependencies)

---

## Table of contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Concepts](#concepts)
- [Loading and saving files](#loading-and-saving-files)
- [Parsing G-code](#parsing-g-code)
- [Tracking modal state](#tracking-modal-state)
- [Arc linearization](#arc-linearization)
- [XY transforms](#xy-transforms)
- [Statistics and bounds](#statistics-and-bounds)
- [Binary .bgcode files](#binary-bgcode-files)
- [Slicer and vendor compatibility](#slicer-and-vendor-compatibility)
- [API reference](#api-reference)

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

# Shift the print 10 mm to the right, 5 mm forward
lines = gl.linearize_arcs(gf.lines)     # required before any XY transform
lines = gl.translate_xy(lines, dx=10.0, dy=5.0)
gf.lines = lines

gl.save(gf, "benchy_shifted.gcode")
```

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

## Loading and saving files

### Load from disk

`load()` auto-detects the file format:

```python
gf = gl.load("print.gcode")    # plain text
gf = gl.load("print.bgcode")   # Prusa binary
```

### Load from a string

```python
gcode_text = """\
G28 ; home all axes
G90 ; absolute positioning
G1 X50 Y50 Z0.2 F3000
G1 X100 Y50 E5.0 F1500
"""

gf = gl.from_text(gcode_text)
print(len(gf.lines))   # 4
```

### Render back to a string

```python
text = gl.to_text(gf)
print(text)
```

### Save to disk

`save()` writes atomically (temp file + rename) and preserves the original format:

```python
gl.save(gf, "output.gcode")

# Save a .bgcode source back as .bgcode (thumbnails and metadata preserved)
gf = gl.load("print.bgcode")
gf.lines = gl.translate_xy(gl.linearize_arcs(gf.lines), dx=5.0, dy=0.0)
gl.save(gf, "print_shifted.bgcode")
```

---

## Parsing G-code

### Parse individual lines

```python
# Single line
line = gl.parse_line("G1 X10 Y20 E0.5 F1500")

# Multi-line string
lines = gl.parse_lines("G28\nG90\nG1 X0 Y0\n")
```

### Low-level utilities

```python
# Split a line into code and comment portions
code, comment = gl.split_comment("G1 X10 Y20 ; move to start")
# code    → "G1 X10 Y20 "
# comment → "; move to start"

# Parse axis words from a code string
words = gl.parse_words("G1 X10.5 Y-3.2 E0.012 F3600")
# words → {"X": 10.5, "Y": -3.2, "E": 0.012, "F": 3600.0}
```

### Filtering moves and arcs

```python
gf = gl.load("print.gcode")

move_lines = [line for line in gf.lines if line.is_move]
arc_lines  = [line for line in gf.lines if line.is_arc]
non_blank  = [line for line in gf.lines if not line.is_blank]
```

---

## Tracking modal state

### Advance state manually

```python
state = gl.ModalState()
for line in gl.parse_lines("G90\nG1 X10 Y20 Z0.2 E1.0 F3000\n"):
    gl.advance_state(state, line)

print(state.x, state.y, state.z)   # 10.0, 20.0, 0.2
print(state.e)                     # 1.0
print(state.f)                     # 3000.0
```

### Iterate with state snapshots

`iter_with_state` yields `(line, state)` where `state` is a copy taken **before** the line runs:

```python
gf = gl.load("print.gcode")

for line, state in gl.iter_with_state(gf.lines):
    if line.is_move:
        print(f"From ({state.x:.2f}, {state.y:.2f}) → {line.words}")
```

### Iterate over specific move types

```python
# G0 and G1 moves only
for line, state in gl.iter_moves(gf.lines):
    print(line.command, line.words)

# G2 and G3 arcs only
for line, state in gl.iter_arcs(gf.lines):
    print(f"Arc at Z={state.z:.3f}")

# Extruding moves only (positive E delta)
for line, state in gl.iter_extruding(gf.lines):
    e_delta = line.words.get("E", 0.0) - state.e   # absolute mode
    print(f"Extruded {e_delta:.4f} mm")
```

### Custom state with a non-zero start position

```python
initial = gl.ModalState()
initial.x = 100.0
initial.y = 50.0
initial.z = 0.3
initial.abs_xy = True

for line, state in gl.iter_moves(gf.lines, initial_state=initial):
    ...
```

### Detect mode changes

```python
gf = gl.load("print.gcode")
state = gl.ModalState()

for line in gf.lines:
    was_abs = state.abs_xy
    gl.advance_state(state, line)
    if state.abs_xy != was_abs:
        mode = "G90" if state.abs_xy else "G91"
        print(f"Switched to {mode}: {line.raw}")
```

---

## Arc linearization

G2/G3 arc commands must be converted to G1 segments before any XY transform can be applied.

### Basic linearization

```python
gf = gl.load("print.gcode")

# Replace all G2/G3 with G1 segments (default 0.2 mm chord, 5° max sweep)
lines = gl.linearize_arcs(gf.lines)
gf.lines = lines
```

### Adjust precision

```python
# Finer segments: 0.05 mm chord, 1° max sweep
lines = gl.linearize_arcs(
    gf.lines,
    seg_mm=0.05,
    max_deg=1.0,
)

# Coarser (faster) segments
lines = gl.linearize_arcs(gf.lines, seg_mm=0.5, max_deg=10.0)
```

### Count arcs before and after

```python
before = sum(1 for l in gf.lines if l.is_arc)
lines = gl.linearize_arcs(gf.lines)
after = sum(1 for l in lines if l.is_arc)

print(f"Arcs before: {before}, after: {after}")   # after should be 0
```

---

## XY transforms

All transform functions return a **new list** and do not mutate their input.
Arcs must be linearized first.

### Translate (shift)

```python
gf = gl.load("print.gcode")
lines = gl.linearize_arcs(gf.lines)

# Move print 10 mm right, 5 mm forward
lines = gl.translate_xy(lines, dx=10.0, dy=5.0)
gf.lines = lines
gl.save(gf, "shifted.gcode")
```

### Skew correction

Corrects XY skew in the same convention as Marlin's M852 parameter:

```python
gf = gl.load("print.gcode")
lines = gl.linearize_arcs(gf.lines)

# Correct 0.5° of XY skew, relative to Y=0
lines = gl.apply_skew(lines, skew_deg=0.5, y_ref=0.0)
gf.lines = lines
gl.save(gf, "corrected.gcode")
```

The transform applied is: `x' = x + (y - y_ref) * tan(skew_deg)`, `y' = y`.

### Arbitrary XY transform

Supply any `fn(x, y) -> (x_new, y_new)` function:

```python
import math
import gcode_lib as gl

gf = gl.load("print.gcode")
lines = gl.linearize_arcs(gf.lines)

# Rotate 45° around the origin
angle = math.radians(45)
def rotate(x, y):
    return (
        x * math.cos(angle) - y * math.sin(angle),
        x * math.sin(angle) + y * math.cos(angle),
    )

lines = gl.apply_xy_transform(lines, fn=rotate)
gf.lines = lines
gl.save(gf, "rotated.gcode")
```

```python
# Mirror across X=100
def mirror_x(x, y):
    return (200.0 - x, y)

lines = gl.apply_xy_transform(gl.linearize_arcs(gf.lines), fn=mirror_x)
```

```python
# Scale uniformly around the bed centre (150, 150)
cx, cy = 150.0, 150.0
scale = 0.95

def scale_around_centre(x, y):
    return (cx + (x - cx) * scale, cy + (y - cy) * scale)

lines = gl.apply_xy_transform(gl.linearize_arcs(gf.lines), fn=scale_around_centre)
```

### Controlling output precision

All transform functions accept optional decimal place parameters:

```python
lines = gl.translate_xy(
    lines,
    dx=5.0,
    dy=0.0,
    xy_decimals=4,      # default 3
    other_decimals=6,   # default 5 (E, F, Z, I, J, K)
)
```

---

## Statistics and bounds

### Print statistics

```python
gf = gl.load("print.gcode")
stats = gl.compute_stats(gf.lines)

print(f"Total lines      : {stats.total_lines}")
print(f"Blank lines      : {stats.blank_lines}")
print(f"Comment-only     : {stats.comment_only_lines}")
print(f"G0/G1 moves      : {stats.move_count}")
print(f"G2/G3 arcs       : {stats.arc_count}")
print(f"Travel moves     : {stats.travel_count}")
print(f"Extrude moves    : {stats.extrude_count}")
print(f"Retract moves    : {stats.retract_count}")
print(f"Total extrusion  : {stats.total_extrusion:.2f} mm")
print(f"Layers           : {stats.layer_count}")
print(f"Z heights        : {stats.z_heights}")
print(f"Feedrates (mm/m) : {stats.feedrates}")
```

### Bounding box

```python
bounds = stats.bounds   # included in GCodeStats

if bounds.valid:
    print(f"X: {bounds.x_min:.2f} – {bounds.x_max:.2f}  ({bounds.width:.2f} mm)")
    print(f"Y: {bounds.y_min:.2f} – {bounds.y_max:.2f}  ({bounds.height:.2f} mm)")
    print(f"Z: {bounds.z_min:.2f} – {bounds.z_max:.2f}")
    print(f"Centre: ({bounds.center_x:.2f}, {bounds.center_y:.2f})")
```

### Bounds from extruding moves only

Useful for finding the actual printed area without including travel moves:

```python
extruding_bounds = gl.compute_bounds(
    gf.lines,
    extruding_only=True,
    include_arcs=True,
)
print(f"Extruded area: {extruding_bounds.width:.1f} x {extruding_bounds.height:.1f} mm")
```

### Centre a print on the bed

```python
gf = gl.load("print.gcode")
lines = gl.linearize_arcs(gf.lines)

bounds = gl.compute_bounds(lines)
bed_cx, bed_cy = 150.0, 150.0   # your bed centre

dx = bed_cx - bounds.center_x
dy = bed_cy - bounds.center_y

lines = gl.translate_xy(lines, dx=dx, dy=dy)
gf.lines = lines
gl.save(gf, "centred.gcode")
```

---

## Binary .bgcode files

Prusa `.bgcode` files are handled transparently.  Thumbnails and all other metadata blocks are
preserved automatically on save.

### Load and inspect thumbnails

```python
gf = gl.load("print.bgcode")

print(f"Thumbnails: {len(gf.thumbnails)}")
for thumb in gf.thumbnails:
    print(f"  {thumb.width}×{thumb.height} px  format_code={thumb.format_code}")
    print(f"  {len(thumb.data)} bytes of image data")
```

### Round-trip transform on .bgcode

```python
gf = gl.load("print.bgcode")

# Transform (linearize arcs first)
lines = gl.linearize_arcs(gf.lines)
lines = gl.translate_xy(lines, dx=10.0, dy=0.0)
gf.lines = lines

# Save back as .bgcode — thumbnails and metadata are preserved
gl.save(gf, "print_shifted.bgcode")
```

### Convert .bgcode to plain text

```python
gf = gl.load("print.bgcode")
gf.source_format = "text"          # tell save() to write plain text
gl.save(gf, "print_converted.gcode")
```

---

## Slicer and vendor compatibility

### G-code parsing and transforms

All parsing, state tracking, arc linearization, XY transforms, and statistics functions are
**fully vendor-agnostic**.  Any standards-compliant FFF G-code file produced by any slicer —
PrusaSlicer, SuperSlicer, OrcaSlicer, Cura, ideaMaker, Simplify3D, Bambu Studio, or any other
— can be loaded, parsed, and transformed.

### Plain-text thumbnails

Embedded thumbnails in plain-text `.gcode` files use the comment-block convention established
by PrusaSlicer:

```
; thumbnail begin 16x16 584
; <base64 data lines>
; thumbnail end
```

The following slicers write thumbnails in this format and are **fully supported**:

| Slicer | Notes |
|---|---|
| **PrusaSlicer** | All three image formats: `thumbnail` (PNG), `thumbnail_JPG`, `thumbnail_QOI` |
| **SuperSlicer** | Same convention as PrusaSlicer |
| **OrcaSlicer** | Same convention as PrusaSlicer |
| **Cura** | Uses `thumbnail` (PNG) blocks |

**Bambu Lab slicers** (Bambu Studio, OrcaSlicer for Bambu) use an incompatible format:
thumbnail data is written as a single long comment line prefixed with `;gimage:` or `;simage:`.
This format is **not supported**.  Bambu thumbnail lines will be left as ordinary comment lines
in `gf.lines` and `gf.thumbnails` will be empty.

### Binary `.bgcode` format

The Prusa binary G-code format (`.bgcode`) is a **Prusa-specific** format.  No other slicer
produces `.bgcode` files.

Two limitations apply when loading `.bgcode`:

- **Heatshrink-compressed GCode blocks are not supported.**  Current releases of PrusaSlicer
  compress the embedded G-code using Heatshrink (compression type 3).  Attempting to load such
  a file raises `ValueError: Heatshrink decompression is not supported`.
  *Workaround:* export as plain `.gcode` from PrusaSlicer's export dialog.
- **DEFLATE-compressed and uncompressed GCode blocks** are fully supported.

Thumbnail and metadata blocks in `.bgcode` are unaffected by this limitation and are always
read correctly regardless of GCode block compression type.

---

## API reference

### Constants

| Name | Default | Description |
|---|---|---|
| `EPS` | `1e-9` | Floating-point comparison tolerance |
| `DEFAULT_ARC_SEG_MM` | `0.20` | Max chord length (mm) per arc segment |
| `DEFAULT_ARC_MAX_DEG` | `5.0` | Max sweep angle (°) per arc segment |
| `DEFAULT_XY_DECIMALS` | `3` | Output decimal places for X/Y |
| `DEFAULT_OTHER_DECIMALS` | `5` | Output decimal places for E/F/Z/I/J/K |

### Data classes

#### `GCodeLine`

| Attribute | Type | Description |
|---|---|---|
| `raw` | `str` | Original line text (trailing newline stripped) |
| `command` | `str` | Uppercased command token (e.g. `"G1"`) or `""` |
| `words` | `Dict[str, float]` | Parsed axis words |
| `comment` | `str` | Comment portion including leading `;`, or `""` |
| `is_move` | `bool` | `True` if G0 or G1 |
| `is_arc` | `bool` | `True` if G2 or G3 |
| `is_blank` | `bool` | `True` if no command and no meaningful content |

#### `ModalState`

| Attribute | Type | Default | Description |
|---|---|---|---|
| `abs_xy` | `bool` | `True` | G90 (absolute) / G91 (relative) XY mode |
| `abs_e` | `bool` | `True` | M82 (absolute) / M83 (relative) E mode |
| `ij_relative` | `bool` | `True` | G91.1 (relative) / G90.1 (absolute) IJ mode |
| `x` | `float` | `0.0` | Current X position |
| `y` | `float` | `0.0` | Current Y position |
| `z` | `float` | `0.0` | Current Z position |
| `e` | `float` | `0.0` | Current E accumulator |
| `f` | `Optional[float]` | `None` | Current feedrate (None until first F seen) |

#### `GCodeFile`

| Attribute | Type | Description |
|---|---|---|
| `lines` | `List[GCodeLine]` | All lines in source order |
| `thumbnails` | `List[Thumbnail]` | Thumbnails extracted from `.bgcode` or plain-text files with embedded thumbnail blocks |
| `source_format` | `str` | `"text"` or `"bgcode"` |

#### `Bounds`

| Member | Description |
|---|---|
| `x_min`, `x_max`, `y_min`, `y_max`, `z_min`, `z_max` | Extents |
| `valid` | `True` if at least one XY point was added |
| `width` | `x_max - x_min` |
| `height` | `y_max - y_min` |
| `center_x`, `center_y` | Midpoint of XY extents |
| `expand(x, y)` | Expand box to include point |
| `expand_z(z)` | Expand Z range |

#### `GCodeStats`

| Attribute | Description |
|---|---|
| `total_lines` | Total line count |
| `blank_lines` | Lines with no command or comment |
| `comment_only_lines` | Lines with comment but no command |
| `move_count` | G0 + G1 total |
| `arc_count` | G2 + G3 total |
| `travel_count` | Moves without positive extrusion |
| `extrude_count` | Moves with positive E delta |
| `retract_count` | Moves with negative E delta |
| `total_extrusion` | Total E deposited (mm) |
| `bounds` | `Bounds` object |
| `z_heights` | Unique Z values in order seen |
| `feedrates` | Unique F values in order seen |
| `layer_count` | `len(z_heights)` |

#### `Thumbnail`

| Attribute | Description |
|---|---|
| `data` | Decompressed image bytes |
| `width` | Image width in pixels |
| `height` | Image height in pixels |
| `format_code` | Raw format code from bgcode block params |

### Functions

#### I/O

```
load(path: str) -> GCodeFile
save(gf: GCodeFile, path: str) -> None
from_text(text: str) -> GCodeFile
to_text(gf: GCodeFile) -> str
```

#### Parsing

```
parse_line(raw_line: str) -> GCodeLine
parse_lines(text: str) -> List[GCodeLine]
split_comment(line: str) -> Tuple[str, str]
parse_words(code: str) -> Dict[str, float]
```

#### State

```
advance_state(state: ModalState, line: GCodeLine) -> None
iter_with_state(lines, initial_state=None) -> Iterator[Tuple[GCodeLine, ModalState]]
iter_moves(lines, initial_state=None) -> Iterator[Tuple[GCodeLine, ModalState]]
iter_arcs(lines, initial_state=None) -> Iterator[Tuple[GCodeLine, ModalState]]
iter_extruding(lines, initial_state=None) -> Iterator[Tuple[GCodeLine, ModalState]]
```

#### Transforms

```
linearize_arcs(lines, seg_mm=0.20, max_deg=5.0,
               xy_decimals=3, other_decimals=5,
               initial_state=None) -> List[GCodeLine]

apply_xy_transform(lines, fn, xy_decimals=3, other_decimals=5,
                   initial_state=None) -> List[GCodeLine]

apply_skew(lines, skew_deg, y_ref=0.0,
           xy_decimals=3, other_decimals=5,
           initial_state=None) -> List[GCodeLine]

translate_xy(lines, dx, dy,
             xy_decimals=3, other_decimals=5,
             initial_state=None) -> List[GCodeLine]
```

#### Statistics

```
compute_bounds(lines, extruding_only=False, include_arcs=True,
               arc_seg_mm=0.20, arc_max_deg=5.0,
               initial_state=None) -> Bounds

compute_stats(lines, initial_state=None) -> GCodeStats
```

#### Formatting helpers

```
fmt_float(v: float, places: int) -> str
fmt_axis(axis: str, v: float, xy_decimals=3, other_decimals=5) -> str
replace_or_append(code: str, axis: str, val: float,
                  xy_decimals=3, other_decimals=5) -> str
```

---

## Limitations

- **Relative XY (G91) transforms are not supported.**  `apply_xy_transform`, `apply_skew`, and
  `translate_xy` raise `ValueError` if a G0/G1 move with X/Y words is encountered while the
  modal state is in G91 mode.  Linearize arcs first and confirm G90 is active throughout, or
  pre-convert relative segments to absolute before calling transforms.
- **Arc endpoint tracking only.**  `advance_state` updates position to the G2/G3 endpoint but
  does not interpolate intermediate arc positions.  Use `linearize_arcs` if you need full path
  coverage.
- **No G-code validation.**  The library parses and transforms; it does not validate that the
  resulting G-code is printable or within machine limits.

---

## Running the tests

```bash
python -m pytest tests/ -v
```

Tests cover I/O, parsing, state tracking, statistics, and all transform functions using only
stdlib and pytest.
