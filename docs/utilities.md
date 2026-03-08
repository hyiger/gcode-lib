# Utilities

[< Back to README](../README.md)

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

## INI editing helpers

### replace_ini_value

Replace a key's value in a list of INI-format lines.  Returns the updated lines and a boolean
indicating whether the key was found and replaced.

```python
lines = ["first_layer_temperature = 215\n", "bed_temperature = 60\n"]
new_lines, found = gl.replace_ini_value(lines, "bed_temperature", "80")
# found == True, new_lines[1] == "bed_temperature = 80\n"
```

### pa_command

Return the printer-appropriate pressure advance G-code command.  Uses `M572 S<val>` for most
printers and `M900 K<val>` for MINI (Linear Advance).

```python
gl.pa_command(0.04, "MK4")   # "M572 S0.0400"
gl.pa_command(0.04, "MINI")  # "M900 K0.0400"
```

### inject_pa_into_start_gcode

Inject a pressure advance command into start G-code lines (as stored in an INI value).

```python
start_lines = ["G28\n", "G1 Z5\n"]
updated = gl.inject_pa_into_start_gcode(start_lines, 0.04, "MK4")
# Appends "M572 S0.0400" to the start G-code
```

---

## Slicer dimension helpers

### derive_slicer_dimensions

Derive layer height and extrusion width from nozzle size using PrusaSlicer formulas.

```python
layer_h, ext_w = gl.derive_slicer_dimensions(0.4)
# layer_h == 0.2, ext_w == 0.45
```

### flow_to_feedrate

Convert a volumetric flow rate (mm^3/s) to a linear feedrate (mm/min).

```python
feedrate = gl.flow_to_feedrate(10.0, 0.2, 0.45)
# feedrate in mm/min
```

---

## Filename utilities

### gcode_ext

Return the file extension for G-code output: `".bgcode"` for binary, `".gcode"` for text.

```python
gl.gcode_ext(binary=True)   # ".bgcode"
gl.gcode_ext(binary=False)  # ".gcode"
```

### unique_suffix

Generate a 5-character hex string for creating unique filenames.

```python
suffix = gl.unique_suffix()  # e.g. "a3f1b"
```

### safe_filename_part

Sanitise a string for safe use in a filename by removing NUL bytes, replacing `/` and `\` with
`_`, and collapsing `..` to `_`.

```python
gl.safe_filename_part("../prints/part.gcode")  # "__prints_part.gcode"
```

---

## State inspection

### is_extrusion_move

Return `True` if a `GCodeLine` is a G1 move that includes an E parameter along with X and/or Y.

```python
line = gl.parse_line("G1 X10 Y20 E0.5 F1200")
gl.is_extrusion_move(line)  # True

line = gl.parse_line("G1 X10 Y20 F1200")
gl.is_extrusion_move(line)  # False (no E)
```
