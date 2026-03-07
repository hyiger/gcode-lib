# Loading and Saving Files

[< Back to README](../README.md)

## Load from disk

`load()` auto-detects the file format:

```python
gf = gl.load("print.gcode")    # plain text
gf = gl.load("print.bgcode")   # Prusa binary
```

## Load from a string

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

## Render back to a string

```python
text = gl.to_text(gf)
print(text)
```

## Save to disk

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
# code    → "G1 X10 Y20"
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
