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

> **Note:** by default `write_bgcode` produces a BGCode v2 file with a single uncompressed
> (type 0) G-code block encoded as raw UTF-8, which is no smaller than plain text.
> Reading supports all BGCode compression types (None, DEFLATE, Heatshrink) and all encoding
> types (raw UTF-8, MeatPack, MeatPack with comments).

## Compression

Pass `compress=True` to write the G-code the way PrusaSlicer does: Heatshrink 12/4 compression
over MeatPack encoding with comments kept, in blocks of up to 64 KiB of text. A file is typically
about 60% smaller than plain text.

```python
bgcode_bytes = gl.write_bgcode(gl.to_text(gf), thumbnails=gf.thumbnails, compress=True)
```

The commands the printer runs stay the same, but the text does not. Lines starting with `G` and a
digit lose their spaces and any comment after the command, so `G1 X10 Y20 ; move` is stored as
`G1X10Y20`, and blank lines are dropped. Other lines stay as written, because commands such as
`M117` can hold text.

`save()` keeps a loaded file's blocks but always writes the G-code uncompressed, so a compressed
file comes back larger after `load()` and `save()`. To keep it small, write it again with
`write_bgcode(gl.to_text(gf), thumbnails=gf.thumbnails, compress=True)`.

Compression works with the standard library alone, at about 1 second per megabyte. Installing the
optional extra uses a C encoder that is about 25 times faster:

```
pip install "gcode-lib[compression]"
```
