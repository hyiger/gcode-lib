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
