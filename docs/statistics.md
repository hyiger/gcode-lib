# Statistics and Bounds

[< Back to README](../README.md)

## Print statistics

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

## Bounding box

```python
bounds = stats.bounds   # included in GCodeStats

if bounds.valid:
    print(f"X: {bounds.x_min:.2f} – {bounds.x_max:.2f}  ({bounds.width:.2f} mm)")
    print(f"Y: {bounds.y_min:.2f} – {bounds.y_max:.2f}  ({bounds.height:.2f} mm)")
    print(f"Z: {bounds.z_min:.2f} – {bounds.z_max:.2f}")
    print(f"Centre: ({bounds.center_x:.2f}, {bounds.center_y:.2f})")
```

## Bounds from extruding moves only

Useful for finding the actual printed area without including travel moves:

```python
extruding_bounds = gl.compute_bounds(
    gf.lines,
    extruding_only=True,
    include_arcs=True,
)
print(f"Extruded area: {extruding_bounds.width:.1f} x {extruding_bounds.height:.1f} mm")
```

## Centre a print on the bed (manual method)

```python
gf = gl.load("print.gcode")

bounds = gl.compute_bounds(gf.lines)
bed_cx, bed_cy = 125.0, 105.0   # MK4 bed centre

dx = bed_cx - bounds.center_x
dy = bed_cy - bounds.center_y

lines = gl.translate_xy_allow_arcs(gf.lines, dx=dx, dy=dy)
gf.lines = lines
gl.save(gf, "centred.gcode")
```

Or use `recenter_to_bed()` for a one-call equivalent — see [Bed placement and validation](bed-placement.md).

## Layer iteration

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
