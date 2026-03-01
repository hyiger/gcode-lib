# gcode-lib

A general-purpose Python library for parsing, analysing, and transforming G-code files.
Supports both plain-text `.gcode` and Prusa binary `.bgcode` formats, with a full planar
post-processing toolkit optimised for PrusaSlicer FDM workflows.

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
- [G91 and relative-mode handling](#g91-and-relative-mode-handling)
- [Translate arcs without linearization](#translate-arcs-without-linearization)
- [Bed placement and validation](#bed-placement-and-validation)
- [Layer iteration](#layer-iteration)
- [Transform analysis](#transform-analysis)
- [Statistics and bounds](#statistics-and-bounds)
- [Printer and filament presets](#printer-and-filament-presets)
- [Template rendering](#template-rendering)
- [Thumbnail encoding](#thumbnail-encoding)
- [Binary .bgcode files](#binary-bgcode-files)
- [BGCode bytes API](#bgcode-bytes-api)
- [PrusaSlicer CLI integration](#prusaslicer-cli-integration)
- [Slicer and vendor compatibility](#slicer-and-vendor-compatibility)
- [API reference](#api-reference)
- [Limitations](#limitations)
- [Running the tests](#running-the-tests)

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
gf.lines = gl.translate_xy_allow_arcs(gf.lines, dx=5.0, dy=0.0)
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

G2/G3 arc commands can be converted to G1 segments when an XY transform cannot preserve arc
geometry (e.g. rotation, scaling, skew).  For simple translations, prefer
[`translate_xy_allow_arcs`](#translate-arcs-without-linearization) which avoids this step.

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

### Translate (shift) — requires linearized arcs

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

## G91 and relative-mode handling

Many slicer-generated files use `G91` for short relative moves (for example retraction and
unretraction sequences).  `to_absolute_xy()` converts all relative XY motion to absolute G90
coordinates so the file can then be passed to any XY transform.

```python
import gcode_lib as gl

gf = gl.load("print.gcode")

# Convert any G91 segments to absolute G90 equivalents
lines = gl.to_absolute_xy(gf.lines)

# Now all transforms work safely — no more G91 ValueError
lines = gl.translate_xy(lines, dx=5.0, dy=0.0)
gf.lines = lines
gl.save(gf, "output.gcode")
```

`to_absolute_xy` drops all `G91` commands, rewrites the affected `G0`/`G1` lines with their
accumulated absolute XY positions, and prepends a single `G90` line when any relative moves
were found.  Z, E, F, and comments are always preserved unchanged.

```python
# Supply an explicit starting state if the file begins mid-print
initial = gl.ModalState()
initial.x = 50.0
initial.y = 50.0

lines = gl.to_absolute_xy(gf.lines, initial_state=initial)
```

---

## Translate arcs without linearization

`translate_xy_allow_arcs()` shifts XY coordinates without first requiring arc linearization.
It translates `G0`/`G1` endpoints **and** `G2`/`G3` arc endpoints in one pass, leaving arc
parameters (`I`, `J`) untouched (they are always relative to the arc start point in default
`G91.1` mode).

```python
import gcode_lib as gl

gf = gl.load("print.gcode")

# Shift without destroying arc commands — no linearize_arcs needed
lines = gl.translate_xy_allow_arcs(gf.lines, dx=10.0, dy=5.0)
gf.lines = lines
gl.save(gf, "shifted.gcode")
```

> **Absolute IJ mode (`G90.1`):** If the file uses absolute IJ offsets, `I` and `J` are also
> shifted by `(dx, dy)` so that arc centres remain correct.

> **G91 in file:** `translate_xy_allow_arcs` raises `ValueError` for relative XY moves, the
> same as `translate_xy`.  Pre-process with `to_absolute_xy()` if needed.

---

## Bed placement and validation

### Out-of-bounds detection

`find_oob_moves()` reports every XY move that lands outside a given bed polygon:

```python
import gcode_lib as gl

gf = gl.load("print.gcode")

# Rectangular bed 0..250 x 0..220
bed = [(0, 0), (250, 0), (250, 220), (0, 220)]

hits = gl.find_oob_moves(gf.lines, bed_polygon=bed)
for hit in hits:
    print(
        f"Line {hit.line_number}: ({hit.x:.2f}, {hit.y:.2f})  "
        f"{hit.distance_outside:.3f} mm outside bed"
    )

# Quick check: how far out is the worst offender?
worst = gl.max_oob_distance(gf.lines, bed_polygon=bed)
print(f"Max OOB distance: {worst:.3f} mm")
```

The `bed_polygon` is any sequence of `(x, y)` tuples; the polygon is automatically closed.
Non-rectangular (e.g. delta or custom-shape) beds are fully supported.

```python
# Validate before saving
if gl.max_oob_distance(gf.lines, bed_polygon=bed) > 0.0:
    raise ValueError("Print exceeds bed boundaries!")
gl.save(gf, "safe.gcode")
```

### Recenter or fit to bed

`recenter_to_bed()` positions the print on the bed in one call:

```python
p = gl.PRINTER_PRESETS["MK4"]

lines = gl.recenter_to_bed(
    gf.lines,
    bed_min_x=0.0, bed_max_x=p["bed_x"],
    bed_min_y=0.0, bed_max_y=p["bed_y"],
    margin=5.0,    # mm clearance on each side
    mode="center", # "center" or "fit"
)
gf.lines = lines
gl.save(gf, "recentered.gcode")
```

| Mode | Effect |
|---|---|
| `"center"` | Translates the print so its bounding box is centred within the usable bed area (bed minus margin). Arc commands are preserved — no linearization required. |
| `"fit"` | Scales **and** centres the print using the largest uniform scale factor that keeps it within the usable area. Arcs are consumed during the scale; the result contains only `G1` lines. |

---

## Layer iteration

### Iterate over layers

`iter_layers()` groups lines by Z height, yielding each layer as a `(z_height, [lines])` pair:

```python
import gcode_lib as gl

gf = gl.load("print.gcode")

for z, layer_lines in gl.iter_layers(gf.lines):
    print(f"Layer Z={z:.3f}  lines={len(layer_lines)}")
```

The Z-change line (the `G1 Z…` that initiates the new layer) is included as the **first** line
of its new layer, not the last line of the previous one.

```python
# Count lines per layer and find the thickest
layer_sizes = {z: len(ll) for z, ll in gl.iter_layers(gf.lines)}
busiest_z = max(layer_sizes, key=layer_sizes.get)
print(f"Busiest layer: Z={busiest_z:.3f}  ({layer_sizes[busiest_z]} lines)")
```

### Apply a transform to selected layers only

`apply_xy_transform_by_layer()` runs a transform on a subset of layers, identified by Z range:

```python
import math

angle = math.radians(45)

def rotate(x, y):
    return (
        x * math.cos(angle) - y * math.sin(angle),
        x * math.sin(angle) + y * math.cos(angle),
    )

# Only rotate layers at Z >= 2.0 mm
lines = gl.apply_xy_transform_by_layer(
    gf.lines,
    transform_fn=rotate,
    z_min=2.0,   # skip layers below this Z
    z_max=None,  # no upper limit
)
gf.lines = lines
```

Both `z_min` and `z_max` are inclusive bounds.  Set either to `None` to leave that bound open.
Layers outside the Z range pass through unchanged.

```python
# Apply a different shift to a specific Z band
lines = gl.apply_xy_transform_by_layer(
    gf.lines,
    transform_fn=lambda x, y: (x + 2.0, y),
    z_min=1.0,
    z_max=3.0,
)
```

---

## Transform analysis

`analyze_xy_transform()` performs a **dry run** of any transform function and returns a summary
dict — without modifying any G-code.  Use it to validate a transform before committing the
result to disk.

```python
import gcode_lib as gl

gf = gl.load("print.gcode")

def my_shift(x, y):
    return (x + 10.0, y + 5.0)

info = gl.analyze_xy_transform(gf.lines, my_shift)
print(f"Max X displacement : {info['max_dx']:.3f} mm")
print(f"Max Y displacement : {info['max_dy']:.3f} mm")
print(f"Max total displace : {info['max_displacement']:.3f} mm")
print(f"Worst line         : {info['line_number']}")
print(f"Total moves        : {info['move_count']}")
```

### Validate against bed limits before transforming

```python
bed = [(0, 0), (250, 0), (250, 220), (0, 220)]

# Check the transform stays in bounds before applying it
info = gl.analyze_xy_transform(gf.lines, my_shift)
worst_x = info["max_dx"]
worst_y = info["max_dy"]

# Then apply
lines = gl.translate_xy_allow_arcs(gf.lines, dx=10.0, dy=5.0)
hits = gl.find_oob_moves(lines, bed_polygon=bed)
if hits:
    raise ValueError(f"{len(hits)} moves outside bed after transform")
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

### Centre a print on the bed (manual method)

```python
gf = gl.load("print.gcode")

bounds = gl.compute_bounds(gf.lines)
bed_cx, bed_cy = 125.0, 110.0   # MK4 bed centre

dx = bed_cx - bounds.center_x
dy = bed_cy - bounds.center_y

lines = gl.translate_xy_allow_arcs(gf.lines, dx=dx, dy=dy)
gf.lines = lines
gl.save(gf, "centred.gcode")
```

Or use `recenter_to_bed()` for a one-call equivalent — see [Bed placement and validation](#bed-placement-and-validation).

---

## Printer and filament presets

Built-in presets provide common bed dimensions and printing parameters for Prusa printers.

### Printer presets

```python
print(list(gl.PRINTER_PRESETS.keys()))
# ['COREONE', 'MK4', 'MK3S', 'MINI', 'XL']

p = gl.PRINTER_PRESETS["MK4"]
print(p["bed_x"], p["bed_y"], p["max_z"])   # 250.0  220.0  220.0
```

| Key | `bed_x` mm | `bed_y` mm | `max_z` mm |
|---|---|---|---|
| `COREONE` | 250.0 | 220.0 | 250.0 |
| `MK4` | 250.0 | 220.0 | 220.0 |
| `MK3S` | 250.0 | 210.0 | 210.0 |
| `MINI` | 180.0 | 180.0 | 180.0 |
| `XL` | 360.0 | 360.0 | 360.0 |

### Filament presets

```python
print(list(gl.FILAMENT_PRESETS.keys()))
# ['PLA', 'PETG', 'ASA', 'TPU', 'ABS']

f = gl.FILAMENT_PRESETS["PLA"]
print(f["hotend"], f["bed"], f["fan"], f["retract"])
# 215  60  100  0.8
```

| Key | `hotend` °C | `bed` °C | `fan` % | `retract` mm |
|---|---|---|---|---|
| `PLA` | 215 | 60 | 100 | 0.8 |
| `PETG` | 240 | 80 | 40 | 0.8 |
| `ASA` | 255 | 90 | 20 | 1.0 |
| `TPU` | 225 | 45 | 30 | 1.5 |
| `ABS` | 245 | 100 | 30 | 1.0 |

### Using presets for bed operations

```python
p = gl.PRINTER_PRESETS["MK4"]

lines = gl.recenter_to_bed(
    gf.lines,
    bed_min_x=0.0, bed_max_x=p["bed_x"],
    bed_min_y=0.0, bed_max_y=p["bed_y"],
    margin=5.0,
    mode="center",
)
```

---

## Template rendering

`render_template()` substitutes `{variable}` placeholders in G-code start/end scripts.

Only **simple `{lowercase_identifier}` patterns** are replaced — identifiers that start with a
lowercase letter and contain only lowercase letters, digits, and underscores.  All other `{…}`
tokens (PrusaSlicer conditionals like `{if …}`, `{elsif …}`, `{else}`, `{endif}`, and any
uppercase or complex expressions) are left **exactly as written**.

```python
import gcode_lib as gl

template = """\
M104 S{hotend_temp}   ; set hotend
M140 S{bed_temp}      ; set bed
G28                   ; home
{if is_first_layer}
M106 S0               ; fan off first layer
{endif}
"""

variables = {
    "hotend_temp": 215,
    "bed_temp": 60,
}

rendered = gl.render_template(template, variables)
print(rendered)
# M104 S215   ; set hotend
# M140 S60    ; set bed
# G28         ; home
# {if is_first_layer}   ← preserved (not a simple lowercase identifier)
# M106 S0               ; fan off first layer
# {endif}               ← preserved
```

### Combine with filament presets

```python
pla = gl.FILAMENT_PRESETS["PLA"]

rendered = gl.render_template(template, {
    "hotend_temp": pla["hotend"],
    "bed_temp":    pla["bed"],
})
```

Unknown `{keys}` that are not in the `variables` dict are left untouched (no `KeyError`).

---

## Thumbnail encoding

`encode_thumbnail_comment_block()` creates a PrusaSlicer-compatible thumbnail comment block
from raw PNG bytes.  The resulting string can be prepended to any G-code file.

```python
import gcode_lib as gl

# Read a PNG thumbnail from disk
with open("thumb_16x16.png", "rb") as f:
    png_bytes = f.read()

block = gl.encode_thumbnail_comment_block(16, 16, png_bytes)
print(block)
# ; thumbnail begin 16x16 584
# ; iVBORw0KGgoAAAANSUhEUgAAAA...
# ; thumbnail end
```

### Embed a thumbnail into a plain-text G-code file

```python
gf = gl.load("print.gcode")

with open("thumb_220x124.png", "rb") as f:
    png_bytes = f.read()

header_block = gl.encode_thumbnail_comment_block(220, 124, png_bytes)
thumb_lines = gl.parse_lines(header_block)

# Prepend the thumbnail block before the G-code body
gf.lines = thumb_lines + gf.lines
gl.save(gf, "print_with_thumb.gcode")
```

The format produced is identical to PrusaSlicer's output and is automatically read back into
`gf.thumbnails` on the next `load()`.

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

# Arc-safe translation — no linearization needed for a simple shift
lines = gl.translate_xy_allow_arcs(gf.lines, dx=10.0, dy=0.0)
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

## BGCode bytes API

In addition to `load()` / `save()` which work with file paths, two functions work directly with
`bytes` objects for in-memory or streaming workflows:

```python
import gcode_lib as gl

# Decode raw BGCode bytes (e.g. received over a network socket)
with open("print.bgcode", "rb") as f:
    raw = f.read()

gf = gl.read_bgcode(raw)
print(f"Lines: {len(gf.lines)}")
print(f"Thumbnails: {len(gf.thumbnails)}")

# Transform the G-code
gf.lines = gl.translate_xy_allow_arcs(gf.lines, dx=5.0, dy=0.0)

# Re-encode as BGCode bytes — thumbnails preserved
output_bytes = gl.write_bgcode(gl.to_text(gf), thumbnails=gf.thumbnails)

with open("output.bgcode", "wb") as f:
    f.write(output_bytes)
```

```python
# Create a brand-new BGCode file from plain-text G-code (no thumbnails)
gcode_text = "G28\nG90\nG1 X50 Y50 Z0.2 F3000\n"
bgcode_bytes = gl.write_bgcode(gcode_text)
```

> **Note:** `write_bgcode` produces a valid BGCode v2 file with DEFLATE-compressed G-code.
> The same Heatshrink limitation described in [Slicer and vendor compatibility](#slicer-and-vendor-compatibility)
> applies to reading: only DEFLATE-compressed and uncompressed G-code blocks can be decoded.

---

## PrusaSlicer CLI integration

A set of helpers wraps the PrusaSlicer command-line interface for scripted slicing workflows.

### Discover the executable

```python
import gcode_lib as gl

exe = gl.find_prusaslicer_executable()
print(exe)
# e.g. /Applications/PrusaSlicer.app/Contents/MacOS/prusa-slicer-console
```

`find_prusaslicer_executable` searches `PATH` and a list of well-known install locations.

| Parameter | Default | Description |
|---|---|---|
| `prefer_console` | `True` | Prefer the headless console binary over the GUI binary |
| `explicit_path` | `None` | Use this exact path (skip discovery) |

Raises `FileNotFoundError` if no binary can be found.

### Probe capabilities

```python
caps = gl.probe_prusaslicer_capabilities(exe)
print(caps.version_text)           # "PrusaSlicer-2.8.0+win64 ..."
print(caps.has_export_gcode)       # True
print(caps.has_load_config)        # True
print(caps.supports_binary_gcode)  # True / False
print(caps.has_help_fff)           # True / False
```

### Run with arbitrary arguments

```python
result = gl.run_prusaslicer(exe, ["--version"])
if result.ok:
    print(result.stdout)
else:
    print("Error:", result.stderr)
    print("Return code:", result.returncode)
```

`run_prusaslicer` captures stdout and stderr, enforces a configurable timeout, and always
returns a `RunResult` — it never raises on non-zero exit codes.

### Slice a single model

```python
req = gl.SliceRequest(
    input_path="model.stl",
    output_path="model.gcode",
    config_ini="my_profile.ini",   # path to a PrusaSlicer .ini config, or None for defaults
)

result = gl.slice_model(exe, req)
if not result.ok:
    raise RuntimeError(f"Slice failed:\n{result.stderr}")

print(f"Sliced OK → {req.output_path}")
```

```python
# Add extra CLI flags (e.g. override layer height)
req = gl.SliceRequest(
    input_path="model.stl",
    output_path="model_draft.gcode",
    config_ini="base.ini",
    extra_args=["--layer-height", "0.3"],
)
result = gl.slice_model(exe, req)
```

### Batch slicing

`slice_batch` slices multiple STL files in parallel using a thread pool:

```python
import os

stl_files = [
    os.path.join("models", f)
    for f in os.listdir("models")
    if f.endswith(".stl")
]

results = gl.slice_batch(
    exe,
    inputs=stl_files,
    output_dir="sliced/",
    config_ini="my_profile.ini",
    naming="{stem}.gcode",   # {stem} = input filename without extension
    parallelism=4,           # up to 4 concurrent PrusaSlicer processes
)

for r in results:
    status = "OK" if r.ok else "FAILED"
    print(f"{status}: {r.cmd[-1]}")
```

The `naming` pattern supports `{stem}` (filename without extension) and `{name}` (full
filename).  Output files are written to `output_dir`.

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

### Presets

| Name | Type | Description |
|---|---|---|
| `PRINTER_PRESETS` | `Dict[str, Dict]` | Bed and Z dimensions for Prusa printers (`COREONE`, `MK4`, `MK3S`, `MINI`, `XL`) |
| `FILAMENT_PRESETS` | `Dict[str, Dict]` | Hotend/bed temperatures and retraction for common materials (`PLA`, `PETG`, `ASA`, `TPU`, `ABS`) |

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

#### `OOBHit`

| Attribute | Type | Description |
|---|---|---|
| `line_number` | `int` | 0-based index of the offending line in the input list |
| `x` | `float` | X coordinate of the out-of-bounds point |
| `y` | `float` | Y coordinate of the out-of-bounds point |
| `distance_outside` | `float` | Distance (mm) from the point to the nearest polygon edge |

#### `PrusaSlicerCapabilities`

| Attribute | Type | Description |
|---|---|---|
| `version_text` | `str` | Raw version string from `--version` |
| `has_export_gcode` | `bool` | `--export-gcode` flag is available |
| `has_load_config` | `bool` | `--load` (config) flag is available |
| `has_help_fff` | `bool` | `--help-fff` flag is available |
| `supports_binary_gcode` | `bool` | Binary G-code output is supported |
| `raw_help` | `str` | Full output of `--help` |
| `raw_help_fff` | `str \| None` | Output of `--help-fff`, or `None` |

#### `RunResult`

| Attribute | Type | Description |
|---|---|---|
| `cmd` | `List[str]` | The command that was executed |
| `returncode` | `int` | Process exit code |
| `stdout` | `str` | Captured standard output |
| `stderr` | `str` | Captured standard error |
| `ok` | `bool` (property) | `True` if `returncode == 0` |

#### `SliceRequest`

| Attribute | Type | Default | Description |
|---|---|---|---|
| `input_path` | `str` | — | Path to the input model file (STL, 3MF, …) |
| `output_path` | `str` | — | Path for the output G-code file |
| `config_ini` | `str \| None` | — | Path to a PrusaSlicer `.ini` config, or `None` |
| `printer_technology` | `str` | `"FFF"` | Printer technology flag |
| `extra_args` | `List[str]` | `[]` | Additional CLI arguments appended to the command |

### Functions

#### I/O

```
load(path: str) -> GCodeFile
save(gf: GCodeFile, path: str) -> None
from_text(text: str) -> GCodeFile
to_text(gf: GCodeFile) -> str
read_bgcode(data: bytes) -> GCodeFile
write_bgcode(ascii_gcode: str, thumbnails=None) -> bytes
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

to_absolute_xy(lines, initial_state=None,
               xy_decimals=3, other_decimals=5) -> List[GCodeLine]

translate_xy_allow_arcs(lines, dx, dy,
                        xy_decimals=3, other_decimals=5,
                        initial_state=None) -> List[GCodeLine]

apply_xy_transform_by_layer(lines, transform_fn,
                            z_min=None, z_max=None,
                            xy_decimals=3, other_decimals=5,
                            initial_state=None) -> List[GCodeLine]

recenter_to_bed(lines, bed_min_x, bed_max_x, bed_min_y, bed_max_y,
                margin=0.0, mode="center") -> List[GCodeLine]
```

#### Statistics

```
compute_bounds(lines, extruding_only=False, include_arcs=True,
               arc_seg_mm=0.20, arc_max_deg=5.0,
               initial_state=None) -> Bounds

compute_stats(lines, initial_state=None) -> GCodeStats
```

#### Layer iteration

```
iter_layers(lines, initial_state=None) -> Iterator[Tuple[float, List[GCodeLine]]]
```

#### Bed validation

```
find_oob_moves(lines, bed_polygon,
               initial_state=None) -> List[OOBHit]

max_oob_distance(lines, bed_polygon,
                 initial_state=None) -> float
```

#### Transform analysis

```
analyze_xy_transform(lines, transform_fn,
                     initial_state=None) -> Dict[str, Any]
```

Return keys: `max_dx`, `max_dy`, `max_displacement`, `line_number`, `move_count`.

#### Template and thumbnail

```
render_template(template_text: str, variables: dict) -> str

encode_thumbnail_comment_block(width: int, height: int,
                               png_bytes: bytes) -> str
```

#### PrusaSlicer CLI

```
find_prusaslicer_executable(prefer_console=True,
                            explicit_path=None) -> str

probe_prusaslicer_capabilities(exe: str) -> PrusaSlicerCapabilities

run_prusaslicer(exe: str, args: List[str],
                timeout_s: int = 600) -> RunResult

slice_model(exe: str, req: SliceRequest) -> RunResult

slice_batch(exe: str, inputs: List[str], output_dir: str,
            config_ini: str | None,
            naming: str = "{stem}.gcode",
            parallelism: int = 1) -> List[RunResult]
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

- **G91 relative XY in transforms:** `apply_xy_transform`, `apply_skew`, `translate_xy`, and
  `translate_xy_allow_arcs` raise `ValueError` if a `G0`/`G1` move with X/Y words is encountered
  while the modal state is in G91 mode.  Use `to_absolute_xy()` to convert relative segments to
  absolute before transforming — see [G91 and relative-mode handling](#g91-and-relative-mode-handling).
- **Arc endpoint tracking only.**  `advance_state` updates position to the G2/G3 endpoint but
  does not interpolate intermediate arc positions.  Use `linearize_arcs` if you need full path
  coverage.
- **No helical arc support.**  G2/G3 with a simultaneous Z move (helical arcs) are not supported.
  All arcs are treated as planar (XY only).
- **No G-code validation.**  The library parses and transforms; it does not validate that the
  resulting G-code is printable or within machine limits.  Use `find_oob_moves` for basic bed
  boundary checking.
- **Heatshrink BGCode decompression not supported.**  See [Slicer and vendor compatibility](#slicer-and-vendor-compatibility).

---

## Running the tests

```bash
python -m pytest tests/ -v
```

Tests cover I/O, parsing, state tracking, statistics, all transform functions, bed placement,
layer iteration, presets, template rendering, thumbnail encoding, BGCode round-trips, and
PrusaSlicer CLI helpers — using only stdlib and pytest.
