# Printer and Filament Presets

[< Back to README](../README.md)

Built-in presets provide common bed dimensions and printing parameters for Prusa printers.

## Printer presets

```python
print(list(gl.PRINTER_PRESETS.keys()))
# ['COREONE', 'COREONEL', 'MK4', 'MK3S', 'MINI', 'XL']

p = gl.PRINTER_PRESETS["MK4"]
print(p["bed_x"], p["bed_y"], p["max_z"])   # 250.0  210.0  220.0
```

| Key | `bed_x` mm | `bed_y` mm | `max_z` mm |
|---|---|---|---|
| `COREONE` | 250.0 | 220.0 | 250.0 |
| `COREONEL` | 300.0 | 300.0 | 330.0 |
| `MK4` | 250.0 | 210.0 | 220.0 |
| `MK3S` | 250.0 | 210.0 | 210.0 |
| `MINI` | 180.0 | 180.0 | 180.0 |
| `XL` | 360.0 | 360.0 | 360.0 |

## Filament presets

```python
print(list(gl.FILAMENT_PRESETS.keys()))
# ['PLA', 'PETG', 'ASA', 'TPU', 'ABS', 'PA', 'PC', 'PCTG', 'PP', 'PPA', 'HIPS', 'PLA-CF', 'PETG-CF', 'PA-CF']

f = gl.FILAMENT_PRESETS["PLA"]
print(f["hotend"], f["bed"], f["fan"], f["retract"])
# 215  60  100  0.8
```

| Key | `hotend` °C | `bed` °C | `fan` % | `retract` mm | `speed` mm/s | `enclosure` |
|---|---|---|---|---|---|---|
| `PLA` | 215 | 60 | 100 | 0.8 | 60 | No |
| `PETG` | 240 | 80 | 40 | 0.8 | 50 | No |
| `ASA` | 260 | 100 | 20 | 0.8 | 45 | Yes |
| `TPU` | 230 | 50 | 50 | 1.5 | 25 | No |
| `ABS` | 255 | 100 | 20 | 0.8 | 45 | Yes |
| `PA` | 260 | 80 | 30 | 1.0 | 40 | Yes |
| `PC` | 275 | 110 | 20 | 0.8 | 40 | Yes |
| `PCTG` | 250 | 80 | 50 | 0.8 | 50 | No |
| `PP` | 240 | 85 | 30 | 1.2 | 35 | Yes |
| `PPA` | 280 | 100 | 20 | 0.8 | 40 | Yes |
| `HIPS` | 230 | 100 | 20 | 0.8 | 45 | Yes |
| `PLA-CF` | 220 | 60 | 100 | 0.8 | 50 | No |
| `PETG-CF` | 250 | 80 | 30 | 0.8 | 45 | No |
| `PA-CF` | 270 | 80 | 20 | 1.0 | 40 | Yes |

Each preset also includes `temp_min` and `temp_max` (°C) for safe temperature range validation.

## Using presets for bed operations

```python
p = gl.PRINTER_PRESETS["MK4"]

lines = gl.recenter_to_bed(
    gf.lines,
    bed_min_x=0.0, bed_max_x=p["bed_x"],
    bed_min_y=0.0, bed_max_y=p["bed_y"],
    margin=5.0,
    mode="center",
)
```

## Auto-detecting printer preset from G-code

PrusaSlicer embeds an `M862.3 P "PRINTERNAME"` command in the G-code to identify the target
printer.  `detect_printer_preset` scans for this command and returns the matching preset key,
or `None` if no match is found.

```python
gf = gl.load("print.gcode")
preset = gl.detect_printer_preset(gf.lines)
print(preset)   # e.g. "COREONE", "MK4", or None
```

`detect_print_volume` does the same lookup and returns the matching bed dimensions as a dict:

```python
vol = gl.detect_print_volume(gf.lines)
if vol:
    print(vol)   # {"bed_x": 250.0, "bed_y": 220.0, "max_z": 250.0}
```

## Resolving filament presets

`resolve_filament_preset()` looks up a filament type (case-insensitive) and returns a dict with
resolved `nozzle_temp`, `bed_temp`, and `fan_speed`.  Explicit keyword arguments override preset
defaults.  Unknown filament types fall back to safe defaults (210 / 60 / 100).

```python
result = gl.resolve_filament_preset("PETG")
print(result)  # {"nozzle_temp": 240, "bed_temp": 80, "fan_speed": 40}

# Override bed temp from the preset
result = gl.resolve_filament_preset("PETG", bed_temp=90)
print(result["bed_temp"])  # 90
```

## Printer G-code helpers

### KNOWN_PRINTERS and MBL_TEMP

`KNOWN_PRINTERS` is a tuple of all supported printer name strings.  `MBL_TEMP` is the default
mesh bed leveling temperature (170 C).

```python
print(gl.KNOWN_PRINTERS)  # ('COREONE', 'COREONEL', 'MK4S', 'MINI', 'XL')
print(gl.MBL_TEMP)         # 170
```

### resolve_printer

`resolve_printer()` normalises a printer name (case-insensitive) and validates
it against `KNOWN_PRINTERS` (with aliases such as `MK4 -> MK4S`).  Raises `ValueError` if the name
is not recognised.

```python
printer = gl.resolve_printer("mk4")   # "MK4S"
gl.resolve_printer("unknown")          # raises ValueError
```

### compute_bed_center and compute_bed_shape

`compute_bed_center()` returns the bed centre as a string (e.g. `"125,105"`).
`compute_bed_shape()` returns the bed shape as a PrusaSlicer `--bed-shape` argument string.

```python
print(gl.compute_bed_center("MK4"))   # "125,105"
print(gl.compute_bed_shape("MK4"))    # "0x0,250x0,250x210,0x210"
```
