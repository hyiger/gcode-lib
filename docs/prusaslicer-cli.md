# PrusaSlicer CLI Integration

[< Back to README](../README.md)

A set of helpers wraps the PrusaSlicer command-line interface for scripted slicing workflows.

## Discover the executable

```python
import gcode_lib as gl

exe = gl.find_prusaslicer_executable()
print(exe)
# e.g. /Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer-console
```

`find_prusaslicer_executable` searches `PATH` and a list of well-known install locations.

| Parameter | Default | Description |
|---|---|---|
| `prefer_console` | `True` | Prefer the headless console binary over the GUI binary |
| `explicit_path` | `None` | Use this exact path (skip discovery) |

Raises `FileNotFoundError` if no binary can be found.

## Probe capabilities

```python
caps = gl.probe_prusaslicer_capabilities(exe)
print(caps.version_text)           # "PrusaSlicer-2.8.0+win64 ..."
print(caps.has_export_gcode)       # True
print(caps.has_load_config)        # True
print(caps.supports_binary_gcode)  # True / False
print(caps.has_help_fff)           # True / False
```

## Run with arbitrary arguments

```python
result = gl.run_prusaslicer(exe, ["--version"])
if result.ok:
    print(result.stdout)
else:
    print("Error:", result.stderr)
    print("Return code:", result.returncode)
```

`run_prusaslicer` captures stdout and stderr, enforces a configurable timeout, and returns a
`RunResult` for completed processes (including non-zero exit codes). It raises `RuntimeError`
on timeout or process-launch failures.

## Slice a single model

```python
req = gl.SliceRequest(
    input_path="model.stl",
    output_path="model.gcode",
    config_ini="my_profile.ini",   # path to a PrusaSlicer .ini config, or None for defaults
)

result = gl.slice_model(exe, req)
if not result.ok:
    raise RuntimeError(f"Slice failed:\n{result.stderr}")

print(f"Sliced OK → {req.output_path}")
```

```python
# Add extra CLI flags (e.g. override layer height)
req = gl.SliceRequest(
    input_path="model.stl",
    output_path="model_draft.gcode",
    config_ini="base.ini",
    extra_args=["--layer-height", "0.3"],
)
result = gl.slice_model(exe, req)
```

## Batch slicing

`slice_batch` slices multiple STL files in parallel using a thread pool:

```python
import os

stl_files = [
    os.path.join("models", f)
    for f in os.listdir("models")
    if f.endswith(".stl")
]

results = gl.slice_batch(
    exe,
    inputs=stl_files,
    output_dir="sliced/",
    config_ini="my_profile.ini",
    naming="{stem}.gcode",   # {stem} = input filename without extension
    parallelism=4,           # up to 4 concurrent PrusaSlicer processes
)

for r in results:
    status = "OK" if r.ok else "FAILED"
    print(f"{status}: {r.cmd[-1]}")
```

The `naming` pattern supports `{stem}` (filename without extension). Unknown placeholders are
left unchanged. Output files are written to `output_dir`.

---

## Slicer and vendor compatibility

### G-code parsing and transforms

All parsing, state tracking, arc linearization, XY transforms, and statistics functions are
**fully vendor-agnostic**.  Any standards-compliant FFF G-code file produced by any slicer —
PrusaSlicer, SuperSlicer, OrcaSlicer, Cura, ideaMaker, Simplify3D, Bambu Studio, or any other
— can be loaded, parsed, and transformed.

### Plain-text thumbnails

Embedded thumbnails in plain-text `.gcode` files use the comment-block convention established
by PrusaSlicer:

```
; thumbnail begin 16x16 584
; <base64 data lines>
; thumbnail end
```

The following slicers write thumbnails in this format and are **fully supported**:

| Slicer | Notes |
|---|---|
| **PrusaSlicer** | All three image formats: `thumbnail` (PNG), `thumbnail_JPG`, `thumbnail_QOI` |
| **SuperSlicer** | Same convention as PrusaSlicer |
| **OrcaSlicer** | Same convention as PrusaSlicer |
| **Cura** | Uses `thumbnail` (PNG) blocks |

**Bambu Lab slicers** (Bambu Studio, OrcaSlicer for Bambu) use an incompatible format:
thumbnail data is written as a single long comment line prefixed with `;gimage:` or `;simage:`.
This format is **not supported**.  Bambu thumbnail lines will be left as ordinary comment lines
in `gf.lines` and `gf.thumbnails` will be empty.

### Binary `.bgcode` format

The Prusa binary G-code format (`.bgcode`) is a **Prusa-specific** format.  No other slicer
produces `.bgcode` files.

All BGCode compression types are fully supported:

- **Uncompressed** (type 0) and **DEFLATE** (type 1) G-code blocks
- **Heatshrink** (types 2 and 3) — pure-Python LZSS decompression, no third-party deps
- **MeatPack** encoding (types 1 and 2) — nibble-based G-code encoding used by PrusaSlicer

Thumbnail and metadata blocks are always read correctly regardless of compression type.
