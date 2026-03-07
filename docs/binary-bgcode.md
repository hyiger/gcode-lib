# Binary .bgcode Files

[< Back to README](../README.md)

Prusa `.bgcode` files are handled transparently.  Thumbnails and all other metadata blocks are
preserved automatically on save.

## Load and inspect thumbnails

```python
gf = gl.load("print.bgcode")

print(f"Thumbnails: {len(gf.thumbnails)}")
for thumb in gf.thumbnails:
    print(f"  {thumb.width}×{thumb.height} px  format_code={thumb.format_code}")
    print(f"  {len(thumb.data)} bytes of image data")
```

## Round-trip transform on .bgcode

```python
gf = gl.load("print.bgcode")

# Arc-safe translation — no linearization needed for a simple shift
lines = gl.translate_xy_allow_arcs(gf.lines, dx=10.0, dy=0.0)
gf.lines = lines

# Save back as .bgcode — thumbnails and metadata are preserved
gl.save(gf, "print_shifted.bgcode")
```

## Convert .bgcode to plain text

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

> **Note:** `write_bgcode` produces a valid BGCode v2 file with an uncompressed
> (type 0) G-code block encoded as raw UTF-8.
> Reading supports all BGCode compression types (None, DEFLATE, Heatshrink) and all encoding
> types (raw UTF-8, MeatPack, MeatPack with comments).
