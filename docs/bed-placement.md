# Bed Placement and Validation

[< Back to README](../README.md)

## Out-of-bounds detection

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

## Recenter or fit to bed

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
