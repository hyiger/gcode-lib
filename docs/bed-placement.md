# Bed Placement and Validation

[< Back to README](../README.md)

## Out-of-bounds detection

`find_oob_moves()` reports every G0/G1 move that ends outside a given bed polygon.  Arcs are not
checked, so run `linearize_arcs()` first if an arc could leave the bed:

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

PrusaSlicer's purge line sits below Y=0 on purpose, so these functions report it on a normal
file.  There is no option to skip it, so filter the hits when you only care about the print:

```python
# Validate before saving, ignoring the purge line
hits = [hit for hit in gl.find_oob_moves(gf.lines, bed_polygon=bed) if hit.y >= 0]
if hits:
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
    mode="center", # "center" or "fit"
)
gf.lines = lines
gl.save(gf, "recentered.gcode")
```

| Mode | Effect |
|---|---|
| `"center"` | Translates the print so its bounding box is centred on the bed. Arc commands are preserved — no linearization required. `margin` is ignored, and the print is not checked against the bed, so use `find_oob_moves()` if it might not fit. |
| `"fit"` | Scales **and** centres the print using the largest uniform scale factor that keeps it within the bed minus `margin` on each side. This can enlarge a small print as well as shrink a large one. Arcs are linearized first, so the result contains no `G2`/`G3` lines. |
