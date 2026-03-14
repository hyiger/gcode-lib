# API Reference

[< Back to README](../README.md)

## Constants

| Name | Default | Description |
|---|---|---|
| `EPS` | `1e-9` | Floating-point comparison tolerance |
| `DEFAULT_ARC_SEG_MM` | `0.20` | Max chord length (mm) per arc segment |
| `DEFAULT_ARC_MAX_DEG` | `5.0` | Max sweep angle (°) per arc segment |
| `DEFAULT_XY_DECIMALS` | `3` | Output decimal places for X/Y |
| `DEFAULT_OTHER_DECIMALS` | `5` | Output decimal places for E/F/Z/I/J/K |

## Presets

| Name | Type | Description |
|---|---|---|
| `PRINTER_PRESETS` | `Dict[str, Dict]` | Bed/Z dimensions and max temperatures for Prusa printers (`COREONE`, `COREONEL`, `MK4`, `MK3S`, `MINI`, `XL`) |
| `FILAMENT_PRESETS` | `Dict[str, Dict]` | Hotend/bed temperatures, retraction, speed, density, and enclosure flag for common materials (`PLA`, `PETG`, `ASA`, `TPU`, `ABS`, `PA`, `PC`, `PCTG`, `PP`, `PPA`, `HIPS`, `PLA-CF`, `PETG-CF`, `PA-CF`) |

## Data classes

### `GCodeLine`

| Attribute | Type | Description |
|---|---|---|
| `raw` | `str` | Original line text (trailing newline stripped) |
| `command` | `str` | Uppercased command token (e.g. `"G1"`) or `""` |
| `words` | `Dict[str, float]` | Parsed axis words |
| `comment` | `str` | Comment portion including leading `;`, or `""` |
| `is_move` | `bool` | `True` if G0 or G1 |
| `is_arc` | `bool` | `True` if G2 or G3 |
| `is_blank` | `bool` | `True` if no command and no meaningful content |

### `ModalState`

| Attribute | Type | Default | Description |
|---|---|---|---|
| `abs_xy` | `bool` | `True` | G90 (absolute) / G91 (relative) XY mode |
| `abs_e` | `bool` | `True` | M82 (absolute) / M83 (relative) E mode |
| `ij_relative` | `bool` | `True` | G91.1 (relative) / G90.1 (absolute) IJ mode |
| `x` | `float` | `0.0` | Current X position |
| `y` | `float` | `0.0` | Current Y position |
| `z` | `float` | `0.0` | Current Z position |
| `e` | `float` | `0.0` | Current E accumulator |
| `f` | `Optional[float]` | `None` | Current feedrate (None until first F seen) |

### `GCodeFile`

| Attribute | Type | Description |
|---|---|---|
| `lines` | `List[GCodeLine]` | All lines in source order |
| `thumbnails` | `List[Thumbnail]` | Thumbnails extracted from `.bgcode` or plain-text files with embedded thumbnail blocks |
| `source_format` | `str` | `"text"` or `"bgcode"` |

### `Bounds`

| Member | Description |
|---|---|
| `x_min`, `x_max`, `y_min`, `y_max`, `z_min`, `z_max` | Extents |
| `valid` | `True` if at least one XY point was added |
| `width` | `x_max - x_min` |
| `height` | `y_max - y_min` |
| `center_x`, `center_y` | Midpoint of XY extents |
| `expand(x, y)` | Expand box to include point |
| `expand_z(z)` | Expand Z range |

### `GCodeStats`

| Attribute | Description |
|---|---|
| `total_lines` | Total line count |
| `blank_lines` | Lines with no command or comment |
| `comment_only_lines` | Lines with comment but no command |
| `move_count` | G0 + G1 total |
| `arc_count` | G2 + G3 total |
| `travel_count` | Moves without positive extrusion |
| `extrude_count` | Moves with positive E delta |
| `retract_count` | Moves with negative E delta |
| `total_extrusion` | Total E deposited (mm) |
| `bounds` | `Bounds` object |
| `z_heights` | Unique Z values in order seen |
| `feedrates` | Unique F values in order seen |
| `layer_count` | `len(z_heights)` |

### `PrintEstimate`

| Attribute | Type | Description |
|---|---|---|
| `time_seconds` | `float` | Estimated print time in seconds |
| `filament_length_m` | `float` | Total filament length in metres |
| `filament_weight_g` | `float` | Total filament weight in grams |
| `time_hms` | `str` (property) | Human-readable time, e.g. `"1h23m45s"`, `"5m12s"`, `"30s"` |

### `Thumbnail`

| Attribute | Description |
|---|---|
| `data` | Decompressed image bytes |
| `width` | Image width in pixels |
| `height` | Image height in pixels |
| `format_code` | Raw format code from bgcode block params |

### `OOBHit`

| Attribute | Type | Description |
|---|---|---|
| `line_number` | `int` | 0-based index of the offending line in the input list |
| `x` | `float` | X coordinate of the out-of-bounds point |
| `y` | `float` | Y coordinate of the out-of-bounds point |
| `distance_outside` | `float` | Distance (mm) from the point to the nearest polygon edge |

### `PrusaSlicerCapabilities`

| Attribute | Type | Description |
|---|---|---|
| `version_text` | `str` | Version string parsed from `--help` output |
| `has_export_gcode` | `bool` | `--export-gcode` flag is available |
| `has_load_config` | `bool` | `--load` (config) flag is available |
| `has_help_fff` | `bool` | `--help-fff` flag is available |
| `supports_binary_gcode` | `bool` | Binary G-code output is supported |
| `raw_help` | `str` | Full output of `--help` |
| `raw_help_fff` | `str \| None` | Output of `--help-fff`, or `None` |

### `RunResult`

| Attribute | Type | Description |
|---|---|---|
| `cmd` | `List[str]` | The command that was executed |
| `returncode` | `int` | Process exit code |
| `stdout` | `str` | Captured standard output |
| `stderr` | `str` | Captured standard error |
| `ok` | `bool` (property) | `True` if `returncode == 0` |

### `SliceRequest`

| Attribute | Type | Default | Description |
|---|---|---|---|
| `input_path` | `str` | — | Path to the input model file (STL, 3MF, …) |
| `output_path` | `str` | — | Path for the output G-code file |
| `config_ini` | `str \| None` | — | Path to a PrusaSlicer `.ini` config, or `None` |
| `printer_technology` | `str` | `"FFF"` | Printer technology flag |
| `extra_args` | `List[str]` | `[]` | Additional CLI arguments appended to the command |

### `PrusaLinkInfo`

| Attribute | Type | Description |
|---|---|---|
| `api` | `str` | API version string |
| `server` | `str` | Server version string |
| `original` | `str` | Original PrusaLink version string |
| `text` | `str` | Human-readable version description |

### `PrusaLinkStatus`

| Attribute | Type | Description |
|---|---|---|
| `printer_state` | `str` | Current printer state |
| `temp_nozzle` | `float \| None` | Current nozzle temperature |
| `temp_bed` | `float \| None` | Current bed temperature |
| `raw` | `dict` | Full JSON payload |

### `PrusaLinkJob`

| Attribute | Type | Description |
|---|---|---|
| `job_id` | `int \| None` | Active job ID |
| `progress` | `float \| None` | Job progress in percent |
| `time_remaining` | `int \| None` | Remaining time in seconds |
| `state` | `str` | Job state |
| `raw` | `dict` | Full JSON payload |

## Functions

### I/O

```
load(path: str) -> GCodeFile
save(gf: GCodeFile, path: str) -> None
from_text(text: str) -> GCodeFile
to_text(gf: GCodeFile) -> str
read_bgcode(data: bytes) -> GCodeFile
write_bgcode(ascii_gcode: str, thumbnails=None) -> bytes
```

### Parsing

```
parse_line(raw_line: str) -> GCodeLine
parse_lines(text: str) -> List[GCodeLine]
split_comment(line: str) -> Tuple[str, str]
parse_words(code: str) -> Dict[str, float]
```

### State

```
advance_state(state: ModalState, line: GCodeLine) -> None
iter_with_state(lines, initial_state=None) -> Iterator[Tuple[GCodeLine, ModalState]]
iter_moves(lines, initial_state=None) -> Iterator[Tuple[GCodeLine, ModalState]]
iter_arcs(lines, initial_state=None) -> Iterator[Tuple[GCodeLine, ModalState]]
iter_extruding(lines, initial_state=None) -> Iterator[Tuple[GCodeLine, ModalState]]
```

### Transforms

```
linearize_arcs(lines, seg_mm=0.20, max_deg=5.0,
               xy_decimals=3, other_decimals=5,
               initial_state=None) -> List[GCodeLine]

apply_xy_transform(lines, fn, xy_decimals=3, other_decimals=5,
                   initial_state=None,
                   skip_negative_y=True) -> List[GCodeLine]

apply_skew(lines, skew_deg, y_ref=0.0,
           xy_decimals=3, other_decimals=5,
           initial_state=None,
           skip_negative_y=True) -> List[GCodeLine]

translate_xy(lines, dx, dy,
             xy_decimals=3, other_decimals=5,
             initial_state=None,
             skip_negative_y=True) -> List[GCodeLine]

to_absolute_xy(lines, initial_state=None,
               xy_decimals=3, other_decimals=5) -> List[GCodeLine]

translate_xy_allow_arcs(lines, dx, dy,
                        xy_decimals=3, other_decimals=5,
                        initial_state=None,
                        skip_negative_y=True) -> List[GCodeLine]

rotate_xy(lines, angle_deg, *, pivot_x=None, pivot_y=None,
          bed_min_x=None, bed_max_x=None, bed_min_y=None, bed_max_y=None,
          margin=0.0, xy_decimals=3, other_decimals=5,
          initial_state=None,
          skip_negative_y=True) -> List[GCodeLine]

apply_xy_transform_by_layer(lines, transform_fn,
                            z_min=None, z_max=None,
                            xy_decimals=3, other_decimals=5,
                            initial_state=None,
                            skip_negative_y=True) -> List[GCodeLine]

recenter_to_bed(lines, bed_min_x, bed_max_x, bed_min_y, bed_max_y,
                margin=0.0, mode="center", *,
                xy_decimals=3, other_decimals=5,
                initial_state=None,
                skip_negative_y=True) -> List[GCodeLine]
```

### Statistics

```
compute_bounds(lines, extruding_only=False, include_arcs=True,
               skip_negative_y=False,
               arc_seg_mm=0.20, arc_max_deg=5.0,
               initial_state=None) -> Bounds

compute_stats(lines, initial_state=None) -> GCodeStats

estimate_print(lines, filament_type=None, filament_diameter=1.75,
               filament_density=None,
               initial_state=None) -> PrintEstimate
```

### Layer iteration

```
iter_layers(lines, initial_state=None) -> Iterator[Tuple[float, List[GCodeLine]]]
```

### Bed validation

```
find_oob_moves(lines, bed_polygon,
               initial_state=None) -> List[OOBHit]

max_oob_distance(lines, bed_polygon,
                 initial_state=None) -> float
```

### Transform analysis

```
analyze_xy_transform(lines, transform_fn,
                     initial_state=None) -> Dict[str, Any]
```

Return keys: `max_dx`, `max_dy`, `max_displacement`, `line_number`, `move_count`.

### Preset detection

```
detect_printer_preset(lines: List[GCodeLine]) -> Optional[str]
detect_print_volume(lines: List[GCodeLine]) -> Optional[Dict[str, float]]
detect_filament_type(lines: List[GCodeLine]) -> Optional[str]
```

`detect_printer_preset` scans for `M862.3 P "..."` and returns the matching `PRINTER_PRESETS` key (e.g. `"COREONE"`) or `None`.
`detect_print_volume` returns the matching preset's bed dimensions (`bed_x`, `bed_y`, `max_z`) as a dict, or `None`.
`detect_filament_type` scans for `; filament_type = ...` comments and returns the filament type string (e.g. `"PETG"`) or `None`.

### Template and thumbnail

```
render_template(template_text: str, variables: dict) -> str

encode_thumbnail_comment_block(width: int, height: int,
                               png_bytes: bytes) -> str
```

### PrusaSlicer CLI

```
find_prusaslicer_executable(prefer_console=True,
                            explicit_path=None) -> str

probe_prusaslicer_capabilities(exe: str) -> PrusaSlicerCapabilities

run_prusaslicer(exe: str, args: List[str],
                timeout_s: int = 600) -> RunResult

slice_model(exe: str, req: SliceRequest) -> RunResult

slice_batch(exe: str, inputs: List[str], output_dir: str,
            config_ini: str | None,
            naming: str = "{stem}.gcode",
            parallelism: int = 1) -> List[RunResult]
```

Notes:
- `run_prusaslicer()` returns `RunResult` for completed processes (including non-zero exits), but raises `RuntimeError` on timeout or launch failures.
- `slice_batch(..., naming=...)` supports `{stem}` placeholders.

### PrusaLink API

```
prusalink_get_version(base_url: str, api_key: str, timeout: float = 10.0) -> PrusaLinkInfo
prusalink_get_status(base_url: str, api_key: str, timeout: float = 10.0) -> PrusaLinkStatus
prusalink_get_job(base_url: str, api_key: str, timeout: float = 10.0) -> PrusaLinkJob
prusalink_upload(base_url: str, api_key: str, gcode_path: str,
                 print_after_upload: bool = False,
                 timeout: float = 120.0) -> str
```

`PrusaLinkError(status_code: int, message: str)` is raised on HTTP or connection failures.

### Formatting helpers

```
fmt_float(v: float, places: int) -> str
fmt_axis(axis: str, v: float, xy_decimals=3, other_decimals=5) -> str
replace_or_append(code: str, axis: str, val: float,
                  xy_decimals=3, other_decimals=5) -> str
```

### §11 INI Parsing

```
parse_prusaslicer_ini(path: str) -> Dict[str, Any]
```

Parse a PrusaSlicer `.ini` and return extracted/normalized keys (for example
`nozzle_diameter`, `nozzle_temp`, `bed_temp`, `fan_speed`, `layer_height`,
`extrusion_width`, `bed_center`, `printer_model`, `filament_type`) when present.

### §12 INI Editing

```
replace_ini_value(lines: List[str], key: str,
                  new_value: str) -> Tuple[List[str], bool]
```

Replace the value of `key` in INI `lines` using regex matching.  Returns the updated lines and a `bool` indicating whether the key was found.

```
pa_command(pa_value: float, printer: str) -> str
```

Return the appropriate pressure advance G-code command: `M572 S<val>` (default) or `M900 K<val>` (MINI).

```
inject_pa_into_start_gcode(lines: List[str], pa_value: float,
                           printer: str) -> List[str]
```

Inject a pressure advance command into the start G-code lines of an INI value.

### §13 Thumbnail Rendering

```
ThumbnailSpec  # dataclass: width, height
```

Dataclass holding thumbnail pixel dimensions.

```
parse_thumbnail_specs(spec: str) -> List[ThumbnailSpec]
```

Parse a PrusaSlicer thumbnail spec string (e.g. `"16x16,220x124"`) into a list of `ThumbnailSpec`.

```
render_stl_to_png(stl_path: str, width: int, height: int) -> bytes
```

Render an STL file to a PNG image using VTK off-screen rendering.  Requires VTK as an optional dependency.

```
build_thumbnail_block(png_data: bytes, width: int, height: int) -> bytes
```

Build a bgcode-format thumbnail block from raw PNG data.

```
inject_thumbnails(gf: GCodeFile, stl_path: str,
                  spec_string: str) -> None
```

Render thumbnails from an STL and inject them into a `GCodeFile`.

```
patch_slicer_metadata(gf: GCodeFile, printer_model: str,
                      nozzle_diameter: float) -> None
```

Patch the `printer_settings_id` metadata in a `GCodeFile` to match the given printer model and nozzle diameter.

### §14 Printer G-code Templates

```
KNOWN_PRINTERS  # tuple of supported printer name strings
MBL_TEMP = 170  # default mesh bed leveling temperature (°C)
```

```
PrinterGCode  # dataclass: start, end
```

Dataclass holding start and end G-code `.format(...)` templates for a printer.

```
resolve_printer(name: str) -> str
```

Normalise and validate a printer name against `KNOWN_PRINTERS`.  Raises `ValueError` if unknown.

```
compute_bed_center(printer: str) -> str
```

Return the bed centre coordinates as a string (e.g. `"125,105"`) from `PRINTER_PRESETS`.

```
compute_bed_shape(printer: str) -> str
```

Return the bed shape as a PrusaSlicer `--bed-shape` string from `PRINTER_PRESETS`.

```
compute_m555(bed_center: str, model_width: float,
             model_depth: float) -> Dict[str, int]
```

Compute M555 positioning parameters from bed centre and model dimensions.

```
render_start_gcode(printer: str, ...) -> str
render_end_gcode(printer: str, ...) -> str
```

Render start/end G-code from the printer's template with provided variables.

### §15 Slicer Dimension Helpers

```
derive_slicer_dimensions(nozzle_size: float) -> Tuple[float, float]
```

Return `(layer_height, extrusion_width)` derived from nozzle size using PrusaSlicer formulas: `layer_height = nozzle_size * 0.5`, `extrusion_width = nozzle_size * 1.125`.

```
flow_to_feedrate(flow_mm3s: float, layer_height: float,
                 extrusion_width: float) -> float
```

Convert a volumetric flow rate (mm^3/s) to a linear feedrate (mm/min).

```
resolve_filament_preset(filament_type: str, *,
                        nozzle_temp=None, bed_temp=None,
                        fan_speed=None) -> Dict
```

Look up a filament preset by type (case-insensitive) and return resolved temperatures.  Explicit keyword arguments override preset defaults.

### §16 Filename Utilities

```
gcode_ext(binary: bool = True) -> str
```

Return `".bgcode"` if binary, `".gcode"` otherwise.

```
unique_suffix() -> str
```

Return a 5-character hex string for unique filename suffixes.

```
safe_filename_part(value: str) -> str
```

Sanitise a string for use in a filename (remove/replace unsafe characters).
