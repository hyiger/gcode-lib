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

| Key | `bed_x` mm | `bed_y` mm | `max_z` mm | `max_nozzle_temp` °C | `max_bed_temp` °C |
|---|---|---|---|---|---|
| `COREONE` | 250.0 | 220.0 | 250.0 | 290 | 120 |
| `COREONEL` | 300.0 | 300.0 | 330.0 | 290 | 120 |
| `MK4` | 250.0 | 210.0 | 220.0 | 290 | 120 |
| `MK3S` | 250.0 | 210.0 | 210.0 | 290 | 120 |
| `MINI` | 180.0 | 180.0 | 180.0 | 280 | 100 |
| `XL` | 360.0 | 360.0 | 360.0 | 290 | 120 |

## Filament presets

```python
print(list(gl.FILAMENT_PRESETS.keys()))
# ['PLA', 'PETG', 'ASA', 'TPU', 'ABS', 'PA', 'PC', 'PCTG', 'PP', 'PPA', 'HIPS', 'PLA-CF', 'PETG-CF', 'PA-CF']

f = gl.FILAMENT_PRESETS["PLA"]
print(f["hotend"], f["bed"], f["fan"], f["retract"])
# 215  60  100  0.8
```

| Key | `hotend` °C | `bed` °C | `fan` % | `retract` mm | `speed` mm/s | `density` g/cm³ | `enclosure` |
|---|---|---|---|---|---|---|---|
| `PLA` | 215 | 60 | 100 | 0.8 | 60 | 1.24 | No |
| `PETG` | 240 | 80 | 40 | 0.8 | 50 | 1.27 | No |
| `ASA` | 260 | 100 | 20 | 0.8 | 45 | 1.07 | Yes |
| `TPU` | 230 | 50 | 50 | 1.5 | 25 | 1.21 | No |
| `ABS` | 255 | 100 | 20 | 0.8 | 45 | 1.04 | Yes |
| `PA` | 260 | 80 | 30 | 1.0 | 40 | 1.14 | Yes |
| `PC` | 275 | 110 | 20 | 0.8 | 40 | 1.20 | Yes |
| `PCTG` | 250 | 80 | 50 | 0.8 | 50 | 1.27 | No |
| `PP` | 240 | 85 | 30 | 1.2 | 35 | 0.90 | Yes |
| `PPA` | 280 | 100 | 20 | 0.8 | 40 | 1.14 | Yes |
| `HIPS` | 230 | 100 | 20 | 0.8 | 45 | 1.05 | Yes |
| `PLA-CF` | 220 | 60 | 100 | 0.8 | 50 | 1.29 | No |
| `PETG-CF` | 250 | 80 | 30 | 0.8 | 45 | 1.32 | No |
| `PA-CF` | 270 | 80 | 20 | 1.0 | 40 | 1.19 | Yes |

Each preset also includes `temp_min` and `temp_max` (°C) for safe temperature range validation, and
`density` (g/cm³) used by `estimate_print()` for filament weight calculation.

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

## Auto-detecting filament type from G-code

PrusaSlicer embeds `; filament_type = PLA` (or PETG, ASA, etc.) comments in the G-code.
`detect_filament_type()` scans for this and returns the type string, or `None` if not found.

```python
gf = gl.load("print.gcode")
filament = gl.detect_filament_type(gf.lines)
print(filament)   # e.g. "PETG", "PLA", or None
```

This is used automatically by `estimate_print()` to select the correct filament density for
weight calculation — see [Statistics](statistics.md#print-time-and-filament-estimation).

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
