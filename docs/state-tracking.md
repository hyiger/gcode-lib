# Tracking Modal State

[< Back to README](../README.md)

## Advance state manually

```python
state = gl.ModalState()
for line in gl.parse_lines("G90\nG1 X10 Y20 Z0.2 E1.0 F3000\n"):
    gl.advance_state(state, line)

print(state.x, state.y, state.z)   # 10.0, 20.0, 0.2
print(state.e)                     # 1.0
print(state.f)                     # 3000.0
```

## Iterate with state snapshots

`iter_with_state` yields `(line, state)` where `state` is a copy taken **before** the line runs:

```python
gf = gl.load("print.gcode")

for line, state in gl.iter_with_state(gf.lines):
    if line.is_move:
        print(f"From ({state.x:.2f}, {state.y:.2f}) → {line.words}")
```

## Iterate over specific move types

```python
# G0 and G1 moves only
for line, state in gl.iter_moves(gf.lines):
    print(line.command, line.words)

# G2 and G3 arcs only
for line, state in gl.iter_arcs(gf.lines):
    print(f"Arc at Z={state.z:.3f}")

# Extruding moves only (positive E delta)
for line, state in gl.iter_extruding(gf.lines):
    e_delta = line.words.get("E", 0.0) - state.e   # absolute mode
    print(f"Extruded {e_delta:.4f} mm")
```

## Custom state with a non-zero start position

```python
initial = gl.ModalState()
initial.x = 100.0
initial.y = 50.0
initial.z = 0.3
initial.abs_xy = True

for line, state in gl.iter_moves(gf.lines, initial_state=initial):
    ...
```

## Detect mode changes

```python
gf = gl.load("print.gcode")
state = gl.ModalState()

for line in gf.lines:
    was_abs = state.abs_xy
    gl.advance_state(state, line)
    if state.abs_xy != was_abs:
        mode = "G90" if state.abs_xy else "G91"
        print(f"Switched to {mode}: {line.raw}")
```
