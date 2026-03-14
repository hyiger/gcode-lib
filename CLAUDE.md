# CLAUDE.md — gcode-lib project guide

## Project overview

Single-file, stdlib-only Python library for parsing, analysing, and transforming G-code files
(both plain-text `.gcode` and Prusa binary `.bgcode`).  Everything lives in `gcode_lib.py`.

## Key constraints

- **Python 3.10+** — uses `from __future__ import annotations`.
- **No third-party runtime deps** — stdlib only (`re`, `math`, `struct`, `zlib`, `base64`,
  `tempfile`, `os`, `sys`, `dataclasses`, `subprocess`, `shutil`, `concurrent.futures`,
  `pathlib`, `typing`, `json`, `uuid`, `urllib.request`, `urllib.error`, `configparser`,
  `multiprocessing`, `platform`, `secrets`, `warnings`).  VTK is an optional dependency
  for thumbnail rendering (`render_stl_to_png`); functions degrade gracefully if absent.
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
  test_gcode_lib_prusalink.py
  test_gcode_lib_ini.py
  test_gcode_lib_thumbnails_render.py
  test_gcode_lib_printer_gcode.py
  test_gcode_lib_slicer_helpers.py
  test_gcode_lib_filename_utils.py
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
| `PrintEstimate` | Estimated print time and filament usage: `.time_seconds`, `.time_hms`, `.filament_length_m`, `.filament_weight_g` |
| `Thumbnail` | Image from .bgcode or plain-text; `.width`, `.height`, `.format_code` |
| `OOBHit` | Out-of-bounds result: `.line_number`, `.x`, `.y`, `.distance_outside` |
| `PrusaSlicerCapabilities` | Detected slicer flags: `.version_text`, `.has_export_gcode`, … |
| `RunResult` | CLI result: `.cmd`, `.returncode`, `.stdout`, `.stderr`, `.ok` |
| `SliceRequest` | Slicing job params: `.input_path`, `.output_path`, `.config_ini`, … |
| `PrusaLinkError` | Exception for PrusaLink API failures: `.status_code`, `.message` |
| `PrusaLinkInfo` | Printer identification from `/api/version`: `.api`, `.server`, `.original`, `.text` |
| `PrusaLinkStatus` | Printer status from `/api/v1/status`: `.printer_state`, `.temp_nozzle`, `.temp_bed`, `.raw` |
| `PrusaLinkJob` | Active job from `/api/v1/job`: `.job_id`, `.progress`, `.time_remaining`, `.state`, `.raw` |

### I/O
- `load(path)` — auto-detects text vs binary
- `save(gf, path)` — atomic write, preserves format
- `from_text(text)` / `to_text(gf)` — string round-trip
- `read_bgcode(data)` — load `GCodeFile` from raw `.bgcode` bytes (supports DEFLATE, Heatshrink, and MeatPack)
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
- `is_extrusion_move(line)` — `True` if G1 with E + X/Y

### Transforms

All transform functions accept `skip_negative_y=True` (default) to skip moves whose effective
absolute Y position is negative — this prevents PrusaSlicer purge lines and nozzle wipes from
being modified.  Pass `skip_negative_y=False` to transform all moves.

- `to_absolute_xy(lines)` — convert all G91 relative XY moves to absolute G90 (**resolves G91 pitfall**)
- `linearize_arcs(lines, seg_mm, max_deg)` — G2/G3 → G1 segments
- `translate_xy_allow_arcs(lines, dx, dy, skip_negative_y=True)` — shift XY including arcs (no prior linearization needed)
- `apply_xy_transform(lines, fn, skip_negative_y=True)` — arbitrary `fn(x, y) -> (x', y')`
- `apply_xy_transform_by_layer(lines, fn, z_min, z_max, skip_negative_y=True)` — transform only layers within Z range
- `apply_skew(lines, skew_deg, skip_negative_y=True)` — Marlin M852-compatible skew correction
- `rotate_xy(lines, angle_deg, pivot_x, pivot_y, bed_min/max_x/y, margin, skip_negative_y=True)` — rotate XY with optional bed validation; arc-safe
- `translate_xy(lines, dx, dy, skip_negative_y=True)` — shift XY coordinates (G1 only; use `translate_xy_allow_arcs` for arcs)

### Statistics
- `compute_bounds(lines, extruding_only, include_arcs, skip_negative_y=False)` → `Bounds`
- `compute_stats(lines)` → `GCodeStats`
- `estimate_print(lines, filament_type, filament_diameter, filament_density)` → `PrintEstimate` — estimated print time, filament length (m), and weight (g); auto-detects filament type from `; filament_type` comments
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

### PrusaSlicer INI parsing
- `parse_prusaslicer_ini(path)` → `Dict` — extract settings from .ini file

### PrusaSlicer INI editing
- `replace_ini_value(lines, key, new_value)` → `(List[str], bool)` — regex-based INI editing
- `pa_command(pa_value, printer)` → `str` — M572 S (default) or M900 K (MINI)
- `inject_pa_into_start_gcode(lines, pa_value, printer)` → `List[str]` — inject PA into INI value

### Thumbnail rendering
- `ThumbnailSpec` — dataclass for thumbnail dimensions
- `parse_thumbnail_specs(spec)` → `List[ThumbnailSpec]` — parse PrusaSlicer spec string
- `render_stl_to_png(stl_path, width, height)` → `bytes` — VTK off-screen render (optional dep)
- `build_thumbnail_block(png_data, width, height)` → `bytes` — bgcode thumbnail block
- `inject_thumbnails(gf, stl_path, spec_string)` — inject rendered thumbnails into GCodeFile
- `patch_slicer_metadata(gf, printer_model, nozzle_diameter)` — patch printer_settings_id

### Printer G-code templates
- `KNOWN_PRINTERS` — tuple of supported printer names
- `PrinterGCode` — dataclass for start/end templates
- `MBL_TEMP` — default mesh bed leveling temp (170)
- `resolve_printer(name)` → `str` — normalise/validate printer name (raises ValueError)
- `compute_bed_center(printer)` → `str` — bed centre from PRINTER_PRESETS
- `compute_bed_shape(printer)` → `str` — bed shape from PRINTER_PRESETS
- `compute_m555(bed_center, model_width, model_depth)` → `Dict` — M555 params
- `render_start_gcode(printer, ...)` → `str` — render start G-code template
- `render_end_gcode(printer, ...)` → `str` — render end G-code template

### Slicer dimension helpers
- `derive_slicer_dimensions(nozzle_size)` → `(float, float)` — (layer_height, extrusion_width)
- `flow_to_feedrate(flow_mm3s, layer_height, extrusion_width)` → `float` — mm/min
- `resolve_filament_preset(filament_type, *, nozzle_temp, bed_temp, fan_speed)` → `Dict` — resolved temps

### Filename utilities
- `gcode_ext(binary=True)` → `str` — ".bgcode" or ".gcode"
- `unique_suffix()` → `str` — 5-char hex
- `safe_filename_part(value)` → `str` — sanitise for filename

### Presets
- `PRINTER_PRESETS` — dict of `{name: {bed_x, bed_y, max_z, max_nozzle_temp, max_bed_temp}}` (COREONE, COREONEL, MK4, MK3S, MINI, XL)
- `FILAMENT_PRESETS` — dict of `{name: {hotend, bed, fan, retract, temp_min, temp_max, speed, enclosure, density}}` (PLA, PETG, ASA, TPU, ABS, PA, PC, PCTG, PP, PPA, HIPS, PLA-CF, PETG-CF, PA-CF)
- `detect_printer_preset(lines)` → `Optional[str]` — detect preset name from `M862.3 P` command in G-code
- `detect_filament_type(lines)` → `Optional[str]` — detect filament type from `; filament_type` comment in G-code
- `detect_print_volume(lines)` → `Optional[Dict[str, float]]` — detect print volume (`bed_x`, `bed_y`, `max_z`) from G-code

### PrusaSlicer CLI helpers
- `find_prusaslicer_executable(prefer_console, explicit_path)` → `str`
- `probe_prusaslicer_capabilities(exe)` → `PrusaSlicerCapabilities`
- `run_prusaslicer(exe, args, timeout_s)` → `RunResult`
- `slice_model(exe, req)` → `RunResult`
- `slice_batch(exe, inputs, output_dir, config_ini, naming, parallelism)` → `List[RunResult]`

### PrusaLink API client
- `prusalink_get_version(base_url, api_key)` → `PrusaLinkInfo` — connectivity test via `GET /api/version`
- `prusalink_get_status(base_url, api_key)` → `PrusaLinkStatus` — printer state via `GET /api/v1/status`
- `prusalink_get_job(base_url, api_key)` → `PrusaLinkJob` — active job via `GET /api/v1/job`
- `prusalink_upload(base_url, api_key, gcode_path, print_after_upload)` → `str` — upload G-code via `PUT /api/v1/files/usb/<filename>`

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
