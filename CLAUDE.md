# CLAUDE.md — gcode-lib project guide

## Project overview

Single-file, stdlib-only Python library for parsing, analysing, and transforming G-code files
(both plain-text `.gcode` and Prusa binary `.bgcode`).  Everything lives in `gcode_lib.py`.

## Key constraints

- **Python 3.10+** — uses `from __future__ import annotations`.
- **No third-party runtime deps** — stdlib only (`re`, `math`, `struct`, `zlib`, `base64`,
  `tempfile`, `os`, `sys`, `dataclasses`, `subprocess`, `shutil`, `concurrent.futures`,
  `pathlib`, `typing`).
- **G91 support**: `apply_xy_transform`, `apply_skew`, and `translate_xy` raise `ValueError`
  for relative moves. Use `to_absolute_xy()` to normalise first.  `translate_xy_allow_arcs`
  also requires G90.

## File layout

```
gcode_lib.py          # entire library (one file)
tests/
  test_gcode_lib_io.py
  test_gcode_lib_parsing.py
  test_gcode_lib_state.py
  test_gcode_lib_stats.py
  test_gcode_lib_transforms.py
  test_gcode_lib_thumbnails.py
  test_gcode_lib_integration.py
  test_gcode_lib_extensions.py
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
| `Thumbnail` | Image from .bgcode or plain-text; `.width`, `.height`, `.format_code` |
| `OOBHit` | Out-of-bounds result: `.line_number`, `.x`, `.y`, `.distance_outside` |
| `PrusaSlicerCapabilities` | Detected slicer flags: `.version_text`, `.has_export_gcode`, … |
| `RunResult` | CLI result: `.cmd`, `.returncode`, `.stdout`, `.stderr`, `.ok` |
| `SliceRequest` | Slicing job params: `.input_path`, `.output_path`, `.config_ini`, … |

### I/O
- `load(path)` — auto-detects text vs binary
- `save(gf, path)` — atomic write, preserves format
- `from_text(text)` / `to_text(gf)` — string round-trip
- `read_bgcode(data)` — load `GCodeFile` from raw `.bgcode` bytes
- `write_bgcode(ascii_gcode, thumbnails)` → `bytes` — serialise to `.bgcode`

### Parsing utilities
- `parse_line(raw)` → `GCodeLine`
- `parse_lines(text)` → `List[GCodeLine]`
- `split_comment(line)` → `(code, comment)`
- `parse_words(code)` → `Dict[str, float]`  *(axes X/Y/Z/E/F/I/J/K/R)*

### State iteration
- `advance_state(state, line)` — mutates state in-place
- `iter_with_state(lines)` — yields `(line, state_before)`
- `iter_moves(lines)` — G0/G1 only
- `iter_arcs(lines)` — G2/G3 only
- `iter_extruding(lines)` — extruding moves only
- `iter_layers(lines)` → yields `(z_height, layer_lines)` — group lines by Z level

### Transforms
- `to_absolute_xy(lines)` — convert all G91 relative XY moves to absolute G90 (**resolves G91 pitfall**)
- `linearize_arcs(lines, seg_mm, max_deg)` — G2/G3 → G1 segments
- `translate_xy_allow_arcs(lines, dx, dy)` — shift XY including arcs (no prior linearization needed)
- `apply_xy_transform(lines, fn)` — arbitrary `fn(x, y) -> (x', y')`
- `apply_xy_transform_by_layer(lines, fn, z_min, z_max)` — transform only layers within Z range
- `apply_skew(lines, skew_deg)` — Marlin M852-compatible skew correction
- `translate_xy(lines, dx, dy)` — shift XY coordinates (G1 only; use `translate_xy_allow_arcs` for arcs)

### Statistics
- `compute_bounds(lines, extruding_only, include_arcs)` → `Bounds`
- `compute_stats(lines)` → `GCodeStats`
- `analyze_xy_transform(lines, fn)` → `dict` — dry-run: max_dx, max_dy, max_displacement, line_number, move_count

### Bed / placement helpers
- `find_oob_moves(lines, bed_polygon)` → `List[OOBHit]`
- `max_oob_distance(lines, bed_polygon)` → `float`
- `recenter_to_bed(lines, bed_min_x, bed_max_x, bed_min_y, bed_max_y, margin, mode)` — `"center"` or `"fit"`

### Formatting helpers
- `fmt_float(v, places)` — trims trailing zeros
- `fmt_axis(axis, v)` — axis-aware precision
- `replace_or_append(code, axis, val)` — update/insert axis word in a code string

### Template rendering
- `render_template(template_text, variables)` — substitute `{lowercase_key}` only; PrusaSlicer conditionals left intact

### Thumbnail helpers
- `encode_thumbnail_comment_block(width, height, png_bytes)` → `str` — PrusaSlicer-compatible block

### Presets
- `PRINTER_PRESETS` — dict of `{name: {bed_x, bed_y, max_z}}` (COREONE, COREONEL, MK4, MK3S, MINI, XL)
- `FILAMENT_PRESETS` — dict of `{name: {hotend, bed, fan, retract}}` (PLA, PETG, ASA, TPU, ABS)
- `detect_printer_preset(lines)` → `Optional[str]` — detect preset name from `M862.3 P` command in G-code

### PrusaSlicer CLI helpers
- `find_prusaslicer_executable(prefer_console, explicit_path)` → `str`
- `probe_prusaslicer_capabilities(exe)` → `PrusaSlicerCapabilities`
- `run_prusaslicer(exe, args, timeout_s)` → `RunResult`
- `slice_model(exe, req)` → `RunResult`
- `slice_batch(exe, inputs, output_dir, config_ini, naming, parallelism)` → `List[RunResult]`

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
- Z and E are **never** modified by XY transform functions.

## Testing

```bash
python -m pytest tests/
```

Tests use only pytest and stdlib fixtures (`tmp_path`). No external test data files are required;
test cases build G-code strings inline.  Integration tests skip gracefully if real printer files
are absent.

## Typical transform workflow

```python
import gcode_lib as gl

gf = gl.load("print.gcode")
lines = gl.linearize_arcs(gf.lines)          # must come before XY transform
lines = gl.translate_xy(lines, dx=10, dy=5)
gf.lines = lines
gl.save(gf, "print_shifted.gcode")
```

### With arc translation (no linearization needed)
```python
lines = gl.translate_xy_allow_arcs(gf.lines, dx=10, dy=5)
```

### Handling G91 files before transform
```python
lines = gl.to_absolute_xy(gf.lines)   # converts all G91 → G90
lines = gl.translate_xy(lines, dx=10, dy=5)
```

### Fit print to bed
```python
lines = gl.linearize_arcs(gf.lines)   # required for fit mode (scale needs G1 segments)
lines = gl.recenter_to_bed(
    lines,
    bed_min_x=0, bed_max_x=250,
    bed_min_y=0, bed_max_y=220,
    margin=5.0, mode="fit",
)
```

### PrusaSlicer CLI
```python
exe = gl.find_prusaslicer_executable()
result = gl.slice_model(exe, gl.SliceRequest(
    input_path="model.stl",
    output_path="model.gcode",
    config_ini="my_profile.ini",
))
print(result.ok, result.returncode)
```

## G91 / relative-mode pitfall

`apply_xy_transform`, `apply_skew`, and `translate_xy` all raise `ValueError` if they encounter
a G0/G1 move containing X or Y words while `abs_xy` is `False`.  Use `to_absolute_xy()` to
pre-process the file, or ensure the source uses G90 throughout (most sliced files do).
