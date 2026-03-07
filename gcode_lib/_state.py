from __future__ import annotations

import math
import re
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from gcode_lib._constants import (
    EPS, DEFAULT_ARC_SEG_MM, DEFAULT_ARC_MAX_DEG,
    DEFAULT_XY_DECIMALS, DEFAULT_OTHER_DECIMALS,
    _MOVE_RE, _ARC_RE, _NUM_RE,
)
from gcode_lib._types import ModalState, GCodeLine


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def advance_state(state: ModalState, line: GCodeLine) -> None:
    """Update *state* in-place to reflect the given *line*.

    Handles:
    - Mode changes: G90/G91, M82/M83, G90.1/G91.1
    - G0/G1 linear moves (absolute and relative XY/Z)
    - G2/G3 arc moves (endpoint update only)
    - G92 position reset
    - E and F tracking on all motion commands
    """
    cmd = line.command
    words = line.words

    # --- Modal flag updates ---
    if cmd == "G90":
        state.abs_xy = True; return
    if cmd == "G91":
        state.abs_xy = False; return
    if cmd == "M82":
        state.abs_e = True; return
    if cmd == "M83":
        state.abs_e = False; return
    if cmd == "G90.1":
        state.ij_relative = False; return
    if cmd == "G91.1":
        state.ij_relative = True; return

    # --- G92: set position ---
    if cmd == "G92":
        if "X" in words: state.x = words["X"]
        if "Y" in words: state.y = words["Y"]
        if "Z" in words: state.z = words["Z"]
        if "E" in words: state.e = words["E"]
        return

    # --- G0/G1 linear move ---
    if _MOVE_RE.match(cmd):
        if state.abs_xy:
            if "X" in words: state.x = words["X"]
            if "Y" in words: state.y = words["Y"]
            if "Z" in words: state.z = words["Z"]
        else:
            state.x += words.get("X", 0.0)
            state.y += words.get("Y", 0.0)
            state.z += words.get("Z", 0.0)
        if "E" in words:
            state.e = words["E"] if state.abs_e else state.e + words["E"]
        if "F" in words:
            state.f = words["F"]
        return

    # --- G2/G3 arc move (update endpoint only; arc-centre handling not needed here) ---
    if _ARC_RE.match(cmd):
        if state.abs_xy:
            if "X" in words: state.x = words["X"]
            if "Y" in words: state.y = words["Y"]
            state.z = words.get("Z", state.z)
        else:
            state.x += words.get("X", 0.0)
            state.y += words.get("Y", 0.0)
            state.z += words.get("Z", 0.0)
        if "E" in words:
            state.e = words["E"] if state.abs_e else state.e + words["E"]
        if "F" in words:
            state.f = words["F"]
        return

    # --- Anything else that carries an E word (e.g. bare E-only commands) ---
    if "E" in words:
        state.e = words["E"] if state.abs_e else state.e + words["E"]


def iter_with_state(
    lines: List[GCodeLine],
    initial_state: Optional[ModalState] = None,
) -> Iterator[Tuple[GCodeLine, ModalState]]:
    """Yield ``(line, state)`` for every line in *lines*.

    *state* is the :class:`ModalState` **before** the line is processed ---
    i.e. the printer's mode when executing that line.  A snapshot copy is
    yielded; callers may safely retain it.
    """
    state = initial_state.copy() if initial_state else ModalState()
    for line in lines:
        yield line, state.copy()
        advance_state(state, line)


def iter_moves(
    lines: List[GCodeLine],
    initial_state: Optional[ModalState] = None,
) -> Iterator[Tuple[GCodeLine, ModalState]]:
    """Yield ``(line, state)`` for G0/G1 lines only."""
    for line, state in iter_with_state(lines, initial_state):
        if line.is_move:
            yield line, state


def iter_arcs(
    lines: List[GCodeLine],
    initial_state: Optional[ModalState] = None,
) -> Iterator[Tuple[GCodeLine, ModalState]]:
    """Yield ``(line, state)`` for G2/G3 lines only."""
    for line, state in iter_with_state(lines, initial_state):
        if line.is_arc:
            yield line, state


def iter_extruding(
    lines: List[GCodeLine],
    initial_state: Optional[ModalState] = None,
) -> Iterator[Tuple[GCodeLine, ModalState]]:
    """Yield ``(line, state)`` for lines that deposit material.

    A line is considered extruding when it is a G0/G1/G2/G3 move that
    carries an E word whose value is greater than the current accumulator
    (absolute E) or greater than zero (relative E).
    """
    for line, state in iter_with_state(lines, initial_state):
        if not (line.is_move or line.is_arc):
            continue
        if "E" not in line.words:
            continue
        e_word = line.words["E"]
        if state.abs_e:
            if e_word > state.e:
                yield line, state
        else:
            if e_word > 0.0:
                yield line, state


def is_extrusion_move(line: GCodeLine) -> bool:
    """Return ``True`` if *line* is a G1 move that extrudes material.

    An extrusion move has an ``E`` word **and** at least one of ``X`` or
    ``Y`` (i.e. lateral movement, not just a retraction or Z-only move).
    """
    if line.command != "G1":
        return False
    if "E" not in line.words:
        return False
    return "X" in line.words or "Y" in line.words


# ---------------------------------------------------------------------------
# Formatting utilities
# ---------------------------------------------------------------------------

def fmt_float(v: float, places: int) -> str:
    """Format *v* to *places* decimal places, trimming trailing zeros.

    >>> fmt_float(10.0, 3)
    '10'
    >>> fmt_float(10.125, 3)
    '10.125'
    >>> fmt_float(-0.0, 3)
    '0'
    """
    s = f"{v:.{places}f}".rstrip("0").rstrip(".")
    if not s or s == "-":
        return "0"
    # Negative zero: "-0" should render as "0"
    if s == "-0":
        return "0"
    return s


def fmt_axis(
    axis: str,
    v: float,
    xy_decimals: int = DEFAULT_XY_DECIMALS,
    other_decimals: int = DEFAULT_OTHER_DECIMALS,
) -> str:
    """Format an axis value with axis-appropriate precision.

    X and Y use *xy_decimals*; all other axes use *other_decimals*.
    """
    places = xy_decimals if axis.upper() in ("X", "Y") else other_decimals
    return fmt_float(v, places)


def replace_or_append(
    code: str,
    axis: str,
    val: float,
    xy_decimals: int = DEFAULT_XY_DECIMALS,
    other_decimals: int = DEFAULT_OTHER_DECIMALS,
) -> str:
    """Replace the value of *axis* in *code*, or append it if absent.

    Only the first occurrence of the axis letter is replaced.
    """
    axis = axis.upper()
    tok = f"{axis}{fmt_axis(axis, val, xy_decimals, other_decimals)}"
    pat = re.compile(rf"(?i)\b{axis}\s*({_NUM_RE})\b")
    return pat.sub(tok, code, count=1) if pat.search(code) else (code + " " + tok)


# ---------------------------------------------------------------------------
# Arc geometry helpers
# ---------------------------------------------------------------------------

def _arc_center(state: ModalState, words: Dict[str, float]) -> Tuple[float, float]:
    """Compute the absolute arc centre from I/J words and modal state."""
    I = words.get("I", 0.0)
    J = words.get("J", 0.0)
    if state.ij_relative:
        return (state.x + I, state.y + J)
    return (I, J)


def _arc_end_abs(state: ModalState, words: Dict[str, float]) -> Tuple[float, float]:
    """Compute the absolute arc endpoint from words and modal state."""
    if state.abs_xy:
        return words.get("X", state.x), words.get("Y", state.y)
    return state.x + words.get("X", 0.0), state.y + words.get("Y", 0.0)


def _sweep_angle(a0: float, a1: float, cw: bool) -> float:
    """Compute the signed sweep angle from *a0* to *a1* for CW or CCW arcs."""
    da = a1 - a0
    while da <= -math.pi: da += 2 * math.pi
    while da >   math.pi: da -= 2 * math.pi
    if cw and da > 0:     da -= 2 * math.pi
    if not cw and da < 0: da += 2 * math.pi
    return da


def linearize_arc_points(
    state: ModalState,
    words: Dict[str, float],
    cw: bool,
    seg_mm: float = DEFAULT_ARC_SEG_MM,
    max_deg: float = DEFAULT_ARC_MAX_DEG,
) -> List[Tuple[float, float]]:
    """Convert a G2/G3 arc into a list of ``(x, y)`` interpolated points.

    The last point is exactly the arc endpoint.  Returns at least one point.

    Parameters
    ----------
    state:   Current modal state (provides start position and IJ mode).
    words:   Parsed axis words for the arc command.
    cw:      True for G2 (clockwise), False for G3 (counter-clockwise).
    seg_mm:  Maximum chord length (mm) per segment.
    max_deg: Maximum sweep angle (degrees) per segment.
    """
    x0, y0 = state.x, state.y
    x1, y1 = _arc_end_abs(state, words)
    cx, cy = _arc_center(state, words)

    r0 = math.hypot(x0 - cx, y0 - cy)
    r1 = math.hypot(x1 - cx, y1 - cy)
    r  = 0.5 * (r0 + r1) if (r0 > 0 and r1 > 0) else max(r0, r1)

    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    da = _sweep_angle(a0, a1, cw=cw)

    # Full-circle arc: start == end gives da ≈ 0; detect by non-zero radius
    if abs(da) < EPS and r > EPS:
        da = -2 * math.pi if cw else 2 * math.pi

    arc_len = abs(da) * r if r > 0 else math.hypot(x1 - x0, y1 - y0)
    max_rad = math.radians(max_deg) if max_deg > 0 else abs(da)
    steps_len = int(math.ceil(arc_len / max(seg_mm, 1e-6))) if seg_mm > 0 else 1
    steps_ang = int(math.ceil(abs(da) / max(max_rad, 1e-9))) if max_deg > 0 else 1
    steps = max(1, steps_len, steps_ang)

    pts: List[Tuple[float, float]] = []
    for i in range(1, steps + 1):
        t  = i / steps
        ai = a0 + da * t
        xi = cx + r * math.cos(ai)
        yi = cy + r * math.sin(ai)
        if i == steps:
            xi, yi = x1, y1
        pts.append((xi, yi))
    return pts


# ---------------------------------------------------------------------------
# Layer iteration
# ---------------------------------------------------------------------------

def iter_layers(
    lines: List[GCodeLine],
    initial_state: Optional[ModalState] = None,
) -> Iterator[Tuple[float, List[GCodeLine]]]:
    """Yield ``(z_height, layer_lines)`` for each distinct Z level.

    A new layer group is started whenever a move changes the current Z height.
    The line that causes the Z change is included at the **start** of the new
    group (i.e. it belongs to the layer it moves *to*, not the one it left).
    The final group is always yielded, even if no Z change follows it.

    The first group has ``z_height`` equal to the initial state's Z (default
    0.0), and contains all lines before the first Z change.

    Parameters
    ----------
    lines:         Full list of :class:`GCodeLine` objects.
    initial_state: Optional starting :class:`ModalState`.
    """
    state = initial_state.copy() if initial_state else ModalState()
    current_z: float = state.z
    current_group: List[GCodeLine] = []

    for line in lines:
        # Peek at whether this line will change Z (moves and arcs both carry Z).
        z_changes = False
        next_z = current_z
        if (line.is_move or line.is_arc) and "Z" in line.words:
            next_z = line.words["Z"] if state.abs_xy else state.z + line.words["Z"]
            if abs(next_z - current_z) > EPS:
                z_changes = True

        if z_changes and current_group:
            yield (current_z, current_group)
            current_group = []
            current_z = next_z

        current_group.append(line)
        advance_state(state, line)

    if current_group:
        yield (current_z, current_group)
