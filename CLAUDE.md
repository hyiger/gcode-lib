# CLAUDE.md — gcode-lib project guide

## Project overview

Single-file, stdlib-only Python library for parsing, analysing, and transforming G-code files
(both plain-text `.gcode` and Prusa binary `.bgcode`).  Everything lives in `gcode_lib.py`.

## Key constraints

- **Python 3.10+** — uses `from __future__ import annotations`.
- **No third-party runtime deps** — stdlib only (`re`, `math`, `struct`, `zlib`, `tempfile`, `os`, `dataclasses`).
- **Relative XY (G91) is not supported for XY transforms.** Callers must linearize arcs and
  confirm G90 is active before calling `apply_xy_transform`, `apply_skew`, or `translate_xy`.

## File layout

```
gcode_lib.py          # entire library (one file)
tests/
  test_gcode_lib_io.py
  test_gcode_lib_parsing.py
  test_gcode_lib_state.py
  test_gcode_lib_stats.py
  test_gcode_lib_transforms.py
```

## Public API surface

### Data classes
| Class | Purpose |
|---|---|
| `GCodeLine` | Single parsed line: `.command`, `.words`, `.comment`, `.raw`; properties `.is_move`, `.is_arc`, `.is_blank` |
| `ModalState` | Printer modal state: `abs_xy`, `abs_e`, `ij_relative`, `x/y/z/e/f`; `.copy()` |
| `GCodeFile` | Top-level container: `.lines`, `.thumbnails`, `.source_format` |
| `Bounds` | XY/Z bounding box; `.valid`, `.width`, `.height`, `.center_x`, `.center_y` |
| `GCodeStats` | Computed stats: move/arc/travel counts, feedrates, z_heights, bounds, `.layer_count` |
| `Thumbnail` | Image from .bgcode; `.width`, `.height`, `.format_code` |

### I/O
- `load(path)` — auto-detects text vs binary
- `save(gf, path)` — atomic write, preserves format
- `from_text(text)` / `to_text(gf)` — string round-trip

### Parsing utilities
- `parse_line(raw)` → `GCodeLine`
- `parse_lines(text)` → `List[GCodeLine]`
- `split_comment(line)` → `(code, comment)`
- `parse_words(code)` → `Dict[str, float]`

### State iteration
- `advance_state(state, line)` — mutates state in-place
- `iter_with_state(lines)` — yields `(line, state_before)`
- `iter_moves(lines)` — G0/G1 only
- `iter_arcs(lines)` — G2/G3 only
- `iter_extruding(lines)` — extruding moves only

### Transforms
- `linearize_arcs(lines, seg_mm, max_deg)` — G2/G3 → G1 segments
- `apply_xy_transform(lines, fn)` — arbitrary `fn(x, y) -> (x', y')`
- `apply_skew(lines, skew_deg)` — Marlin M852-compatible skew correction
- `translate_xy(lines, dx, dy)` — shift XY coordinates

### Statistics
- `compute_bounds(lines, extruding_only, include_arcs)` → `Bounds`
- `compute_stats(lines)` → `GCodeStats`

### Formatting helpers
- `fmt_float(v, places)` — trims trailing zeros
- `fmt_axis(axis, v)` — axis-aware precision
- `replace_or_append(code, axis, val)` — update/insert axis word in a code string

## Constants (tuneable defaults)
```python
DEFAULT_ARC_SEG_MM   = 0.20   # max chord length per arc segment (mm)
DEFAULT_ARC_MAX_DEG  = 5.0    # max sweep per arc segment (degrees)
DEFAULT_XY_DECIMALS  = 3      # decimal places for X/Y output
DEFAULT_OTHER_DECIMALS = 5    # decimal places for E/F/Z/I/J/K output
EPS                  = 1e-9   # float comparison tolerance
```

## Coding conventions

- **Dataclasses** for all structured data; use `field(default_factory=...)` where needed.
- **Immutable inputs** — transform functions return new lists; the input `lines` list is never mutated.
- **State snapshots** — `iter_with_state` yields `state.copy()` so callers can safely retain values.
- **Atomic saves** — `save()` writes to a temp file then `os.replace()`; never leaves a corrupt file.
- **`GCodeLine.raw` is the source of truth** for non-transformed lines — it is never reparsed.
- Internal helpers are prefixed `_` and not part of the public API.

## Testing

```bash
python -m pytest tests/
```

Tests use only pytest and stdlib fixtures (`tmp_path`). No external test data files are required;
test cases build G-code strings inline.

## Typical transform workflow

```python
import gcode_lib as gl

gf = gl.load("print.gcode")
lines = gl.linearize_arcs(gf.lines)          # must come before XY transform
lines = gl.translate_xy(lines, dx=10, dy=5)
gf.lines = lines
gl.save(gf, "print_shifted.gcode")
```

## G91 / relative-mode pitfall

`apply_xy_transform`, `apply_skew`, and `translate_xy` all raise `ValueError` if they encounter
a G0/G1 move containing X or Y words while `abs_xy` is `False`.  Callers must either:

1. Ensure the file uses G90 throughout (most sliced files do), or
2. Pre-process the file to convert relative moves to absolute before transforming.
