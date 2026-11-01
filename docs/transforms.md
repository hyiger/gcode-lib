# Transforms

[< Back to README](../README.md)

## Arc linearization

G2/G3 arc commands can be converted to G1 segments when an XY transform cannot preserve arc
geometry (e.g. scaling, skew, or any function passed to `apply_xy_transform`).  Translation and
rotation don't need this step: use
[`translate_xy_allow_arcs`](#translate-arcs-without-linearization) or
[`rotate_xy`](#rotation--arc-safe-with-optional-bed-validation), which handle arcs natively.

Both I/J and R-format arcs are supported, and a negative `R` selects the major arc.  Under G91,
the segments are written as relative moves.  Rotary A/B/C words are interpolated across the
segments, but a Z word on the arc is applied in full on the first segment.

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

By default, the XY transforms skip moves whose effective absolute Y position is negative
(`skip_negative_y=True`).  This prevents PrusaSlicer purge lines and nozzle wipes (which dip
below Y=0) from being modified.  Pass `skip_negative_y=False` to transform all moves regardless
of Y position.  `linearize_arcs` and `to_absolute_xy` have no such option because they don't
move the print.

`translate_xy`, `apply_skew`, `apply_xy_transform` and `apply_xy_transform_by_layer` only change
G0/G1 moves.  G2/G3 arcs pass through unchanged, with no error, so linearize first or the arcs
will be left behind.

Rotary A/B/C words pass through XY transforms exactly as written.  Parenthesised comments are
kept, but a rewritten line carries them at the end: `G1 X10 (fast) Y20` becomes
`G1 X11 Y21 (fast)`.

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

### Rotation — arc-safe, with optional bed validation

`rotate_xy()` rotates the entire print by a given angle.  It handles G2/G3 arcs natively
(endpoints and I/J offsets are rotated, and R-format arcs keep their radius) so no linearization
is required.  Rotated lines always carry both X and Y, and both I and J on arcs that use them.

```python
gf = gl.load("print.gcode")

# Rotate 30° counter-clockwise around the print's centre
lines = gl.rotate_xy(gf.lines, angle_deg=30.0)
gf.lines = lines
gl.save(gf, "rotated.gcode")
```

Supply bed dimensions to automatically re-centre and validate boundaries:

```python
# Rotate and ensure the result fits within the bed
lines = gl.rotate_xy(
    gf.lines,
    angle_deg=45.0,
    bed_min_x=0, bed_max_x=250,
    bed_min_y=0, bed_max_y=220,
    margin=5.0,
)
```

If the rotated print does not fit within `(bed − 2×margin)`, a `ValueError` is raised.

You can specify a custom pivot point (default is the print's bounding-box centre):

```python
lines = gl.rotate_xy(gf.lines, angle_deg=90.0, pivot_x=125.0, pivot_y=110.0)
```

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
    other_decimals=6,   # default 5 (every axis except X and Y)
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

`to_absolute_xy` drops all `G91` commands, rewrites the affected `G0`/`G1`/`G2`/`G3` lines with
their accumulated absolute positions, and prepends a single `G90` line when any `G91` command
was found.  X, Y, Z and rotary A/B/C words are all converted, so `G1 Z0.2` repeated twice becomes
`Z0.2` then `Z0.4`.  E, F, arc I/J offsets and comments are left as they were.

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
`G91.1` mode).  Rewritten lines always carry both X and Y, so a move that omitted an axis still
receives the full offset.

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

## Layer-selective transforms

### Apply a transform to selected layers only

`apply_xy_transform_by_layer()` runs a transform on a subset of layers, identified by Z range.
It only changes G0/G1 moves, so linearize first or any arcs in the range will be left behind:

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
    gl.linearize_arcs(gf.lines),
    transform_fn=rotate,
    z_min=2.0,   # skip layers below this Z
    z_max=None,  # no upper limit
)
gf.lines = lines
```

Both `z_min` and `z_max` are inclusive bounds.  Set either to `None` to leave that bound open.
Layers outside the Z range pass through unchanged.  As in `iter_layers`, a line that changes Z
belongs to the layer it moves to.

```python
# Apply a different shift to a specific Z band
lines = gl.apply_xy_transform_by_layer(
    gl.linearize_arcs(gf.lines),
    transform_fn=lambda x, y: (x + 2.0, y),
    z_min=1.0,
    z_max=3.0,
)
```

---

## Transform analysis

`analyze_xy_transform()` performs a **dry run** of any transform function and returns a summary
dict — without modifying any G-code.  Use it to validate a transform before committing the
result to disk.  It only measures G0/G1 moves, so linearize first to include arcs.

```python
import gcode_lib as gl

gf = gl.load("print.gcode")

def my_shift(x, y):
    return (x + 10.0, y + 5.0)

info = gl.analyze_xy_transform(gl.linearize_arcs(gf.lines), my_shift)
print(f"Max X displacement : {info['max_dx']:.3f} mm")
print(f"Max Y displacement : {info['max_dy']:.3f} mm")
print(f"Max total displace : {info['max_displacement']:.3f} mm")
print(f"Worst line         : {info['line_number']}")
print(f"Total moves        : {info['move_count']}")
```

### Validate against bed limits after transforming

`analyze_xy_transform` reports how far moves shift, not whether they stay on the bed, so check
the transformed lines:

```python
bed = [(0, 0), (250, 0), (250, 220), (0, 220)]

lines = gl.translate_xy_allow_arcs(gf.lines, dx=10.0, dy=5.0)

# Ignore PrusaSlicer's purge line, which sits below Y=0 on purpose
hits = [hit for hit in gl.find_oob_moves(lines, bed_polygon=bed) if hit.y >= 0]
if hits:
    raise ValueError(f"{len(hits)} moves outside bed after transform")
```

`find_oob_moves` checks every move, including the end-of-print park position, so a shift that
keeps the model on the bed can still be reported if it pushes the park move off the edge.
